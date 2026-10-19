/* 琴光：无外部依赖。曲谱、指法、虚拟琴键与实物帧共享源时间轴。 */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
  const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const finite = (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;
  const palette = {L1:'#68D2E7',L2:'#62A8F5',L3:'#9D8AEF',L4:'#C88CE8',L5:'#E994B8',R1:'#FA7B63',R2:'#F4B95A',R3:'#D8DF65',R4:'#8FCB78',R5:'#4AD8AC'};
  const fiveFingerColors = ['#FF0000','#FFFF00','#00FF00','#0080FF','#FF00FF'];
  const pitchClasses = ['C','C♯','D','E♭','E','F','F♯','G','A♭','A','B♭','B'];
  const STORAGE_KEY = 'piano-light-studio-calibration-v1';
  const PAGE_SIZE = 80;
  let config = readConfig();
  const state = {project:null, noteById:new Map(), time:0, playing:false, mode:'timed', hand:'both', rate:1, mappedOnly:readMappedOnly(), fiveColors:readFiveColors(),
    groupIndex:0, scorePage:0, activeSignature:'', activeNotes:[], lastClockPaint:0, anchorTime:0, anchorNow:0,
    loop:false, loopA:0, loopB:0, lookahead:config.lookahead, serialConnected:false, serialBusy:false,
    serialLastSent:0, serialLastFrame:'', serialForceClear:false, importing:false, loadRevision:0,
    maxNoteDuration:0, testUntil:0, testNotes:[], testPixels:null, renderedCurrent:-1,
    midiAccess:null, midiInput:null, midiBleConnection:null, midiMatched:new Set(), midiHeld:new Set(), midiJudgedGroup:-1,
    midiFeedback:'点“搜索并连接蓝牙钢琴”，再从浏览器弹出的列表中选择设备。', midiFeedbackType:''};
  const keyElements = new Map();
  let ledElements = [];
  let scoreElements = new Map();
  let resizeTimer;

  function makeMapping(first, count, leds) {
    const mapping = {};
    for (let i = 0; i < count; i++) mapping[first + i] = [Math.round(i * (leds - 1) / Math.max(1, count - 1))];
    return mapping;
  }
  function readConfig() {
    const defaults = {firstPitch:21, keyCount:88, ledCount:144, brightness:0.15, lookahead:0.4, confirmed:false, mapping:makeMapping(21,88,144)};
    try {
      const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
      if (!saved || typeof saved !== 'object') return defaults;
      const firstPitch = clamp(Math.round(finite(saved.firstPitch,21)),21,108);
      const keyCount = clamp(Math.round(finite(saved.keyCount,88)),1,Math.min(88,109-firstPitch));
      const ledCount = clamp(Math.round(finite(saved.ledCount,144)),1,512);
      const mapping = {};
      // Missing mappings remain empty; never guess another key's LEDs.
      for (let pitch = firstPitch; pitch < firstPitch + keyCount; pitch++) {
        const indices = saved.mapping?.[pitch];
        mapping[pitch] = Array.isArray(indices) ? [...new Set(indices.filter(n => Number.isInteger(n) && n >= 0 && n < ledCount))] : [];
      }
      return {firstPitch,keyCount,ledCount,mapping,brightness:clamp(finite(saved.brightness,0.15),0.01,0.35),lookahead:clamp(finite(saved.lookahead,0.4),0,1),confirmed:!!saved.confirmed};
    } catch (_) { return defaults; }
  }
  function persistConfig() {
    try { localStorage.setItem(STORAGE_KEY,JSON.stringify({...config,lookahead:state.lookahead})); }
    catch (_) { toast('浏览器未允许保存设置；本次会话仍可继续练习。','error'); }
  }
  function colorFor(note) {
    if(state.fiveColors&&fiveFingerColors[note.finger-1])return fiveFingerColors[note.finger-1];
    const key = `${note.hand}${note.finger}`;
    const value = note.color || state.project?.palette?.[key] || palette[key];
    return /^#[0-9a-f]{6}$/i.test(value || '') ? value : palette[key] || '#E7BC78';
  }
  function readFiveColors(){try{return localStorage.getItem('piano-light-five-colors-v1')==='true';}catch(_){return false;}}
  function setFiveColors(enabled){
    state.fiveColors=!!enabled;
    try{localStorage.setItem('piano-light-five-colors-v1',String(state.fiveColors));}catch(_){toast('本次已切换颜色，但浏览器未能保存开关设置。','error');}
    $('five-color-mode').checked=state.fiveColors;
    renderLegend();renderScore();updateActive(true);syncSerial();
  }
  function installFiveColors(){
    const controls=document.createElement('div');controls.style.cssText='padding:0 24px 14px';
    controls.innerHTML='<label class="checkbox-label"><input type="checkbox" id="five-color-mode">五色指法：左右手同指同色</label><p class="setting-help" style="margin:6px 0 0">开启：拇指红、食指黄、中指绿、无名指蓝、小指紫红；关闭：恢复原十指配色。</p>';
    $('finger-legend').before(controls);$('five-color-mode').checked=state.fiveColors;
    $('five-color-mode').addEventListener('change',event=>setFiveColors(event.target.checked));
  }
  function pitchName(pitch) { return `${pitchClasses[((pitch % 12) + 12) % 12]}${Math.floor(pitch/12)-1}`; }
  function timeLabel(seconds, tenths = false) {
    const positive = Math.max(0,finite(seconds));
    const mins = Math.floor(positive/60), secs = Math.floor(positive%60);
    return `${String(mins).padStart(2,'0')}:${String(secs).padStart(2,'0')}${tenths ? `.${Math.floor((positive%1)*10)}` : ''}`;
  }
  function rangeFill(element) {
    const fraction = (finite(element.value)-finite(element.min))/(finite(element.max,100)-finite(element.min) || 1);
    element.style.setProperty('--fill',`${clamp(fraction,0,1)*100}%`);
  }
  function toast(message, type = '') {
    const element = document.createElement('div');
    element.className = `toast ${type}`;
    element.textContent = message;
    $('toast-container').append(element);
    setTimeout(() => element.remove(),type === 'error' ? 8000 : 4200);
  }
  async function request(path, options = {}) {
    const response = await fetch(path,options);
    if (!response.ok) {
      let message = `${response.status} ${response.statusText}`;
      try {
        const payload = await response.json();
        message = payload.error || payload.message || payload.detail || message;
      } catch (_) { /* Preserve HTTP status when the server did not return JSON. */ }
      throw new Error(typeof message === 'string' ? message : JSON.stringify(message));
    }
    return response.json();
  }
  function post(path, data) { return request(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}); }
  function safeJianpu(pitch, tonic) {
    const semitones = ['1','#1','2','#2','3','4','#4','5','#5','6','#6','7'];
    const offset = pitch - (60 + tonic);
    return {degree:semitones[((offset%12)+12)%12], octave:Math.floor(offset/12)};
  }
  function normalizeProject(raw) {
    if (!raw || !Array.isArray(raw.notes) || !raw.notes.length) throw new Error('未找到可练习的音符，请尝试另一首音乐或 MIDI 文件。');
    const tonic = clamp(Math.round(finite(raw.tonic,0)),0,11);
    const bpm = clamp(finite(raw.bpm,90),20,300);
    const notes = raw.notes.map((note,index) => {
      const pitch = clamp(Math.round(finite(note.pitch,60)),0,127);
      const start = Math.max(0,finite(note.start));
      const end = Math.max(start+0.02,finite(note.end,start+0.4));
      const hand = note.hand === 'L' ? 'L' : 'R';
      const finger = clamp(Math.round(finite(note.finger,1)),1,5);
      return {...note,id:note.id ?? index,pitch,start,end,hand,finger,
        color:/^#[0-9a-f]{6}$/i.test(note.color || '') ? note.color : (raw.palette?.[`${hand}${finger}`] || palette[`${hand}${finger}`]),
        beat_duration:Math.max(0.03125,finite(note.beat_duration,(end-start)*bpm/60)),
        jianpu:note.jianpu && note.jianpu.degree ? note.jianpu : safeJianpu(pitch,tonic)};
    }).sort((a,b) => a.start-b.start || a.pitch-b.pitch);
    const ids = new Set(notes.map(note => String(note.id)));
    let groups = Array.isArray(raw.groups) ? raw.groups.map(group => ({...group,time:Math.max(0,finite(group.time)),note_ids:(group.note_ids || []).filter(id => ids.has(String(id)))})).filter(group => group.note_ids.length).sort((a,b) => a.time-b.time) : [];
    if (!groups.length) {
      for (const note of notes) {
        let group = groups[groups.length-1];
        if (!group || Math.abs(group.time-note.start)>0.025) { group={time:note.start,note_ids:[]}; groups.push(group); }
        group.note_ids.push(note.id);
      }
    }
    return {...raw,title:raw.title || '未命名练习',bpm,tonic,notes,groups,
      duration:notes.reduce((max,note)=>Math.max(max,note.end),finite(raw.duration)),palette:{...palette,...raw.palette},warnings:Array.isArray(raw.warnings)?raw.warnings:[]};
  }
  function loadProject(raw, notify = false) {
    const project = normalizeProject(raw);
    pause();
    state.loadRevision++;
    state.project = project;
    state.noteById = new Map(project.notes.map(note => [String(note.id),note]));
    state.maxNoteDuration = project.notes.reduce((max,note) => Math.max(max,note.end-note.start),0);
    state.time=0;state.groupIndex=0;state.scorePage=0;state.loopA=0;state.loopB=project.duration;
    state.renderedCurrent=-1;state.activeSignature='';state.midiJudgedGroup=-1;state.midiMatched.clear();
    $('song-title').textContent=project.title;
    $('song-key').textContent=project.key_label || `1 = ${pitchClasses[project.tonic]}`;
    $('song-bpm').textContent=`${Math.round(project.bpm)} BPM`;
    $('song-count').textContent=`${project.notes.length} 音符 · ${timeLabel(project.duration)}`;
    const engine = String(project.transcription?.engine || '');
    $('song-source').textContent=project.source?.kind==='midi-search'?'自动找到 MIDI':project.source?.kind==='ncm'?'NCM → MP3':project.source?.kind==='demo'||/demo|示例|built-in/i.test(engine)?'示例':/midi/i.test(engine)?'MIDI':'音频转谱';
    const convertedLink=$('converted-audio-download');convertedLink.hidden=true;convertedLink.removeAttribute('href');
    if(project.source?.converted_audio_url){
      try{
        const url=new URL(project.source.converted_audio_url,location.href);
        if(url.origin===location.origin && /^\/api\/jobs\/[^/]+\/audio\.mp3$/.test(url.pathname)){
          convertedLink.href=url.href;convertedLink.download=filename('.mp3');convertedLink.hidden=false;
        }
      }catch(_){ /* Only link to this local service's converted audio endpoint. */ }
    }
    $('project-badge').innerHTML=`<svg class="icon"><use href="#i-check"/></svg>${project.fingering?.simplified_count?'自动练习编配':'自动生成指法'}`;
    if(['S','M','L'].includes(project.hand_size || project.fingering?.hand_size))$('hand-size').value=project.hand_size || project.fingering.hand_size;
    $('rebuild-bpm').value=String(Math.round(project.bpm));
    $('rebuild-tonic').value=String(project.tonic);
    $('timeline').max=String(project.duration);
    $('time-total').textContent=timeLabel(project.duration);
    $('loop-start').value='0';$('loop-end').value=String(Number(project.duration.toFixed(1)));
    $('loop-start').max=$('loop-end').max=String(project.duration);
    renderLegend();renderScore();renderProjectInfo();updateClock(true);updateActive(true);renderTransport();
    if (notify) toast(`已生成 ${project.groups.length} 组练习，简谱、指法与灯光已同步。`,'success');
    window.dispatchEvent(new CustomEvent('piano-project-loaded',{detail:project}));
  }
  function renderProjectInfo() {
    const project=state.project;
    if (!project) return;
    const transcription=project.transcription?.engine || '项目内已有音符';
    const fingering=project.fingering?.engine || '自动指法';
    const messages=[...project.warnings];
    if(['audio','ncm'].includes(project.source?.kind))messages.unshift('音频转谱是自动生成的练习参考稿，音符和持续时长可能有误，目前尚不能保证与原曲逐音一致。');
    const warnings=messages.map(item => `<li>${escapeHTML(typeof item === 'string' ? item : JSON.stringify(item))}</li>`).join('');
    const sourceCount=project.fingering?.source_note_count || project.notes.length;
    const arrangement=sourceCount!==project.notes.length?`从 ${sourceCount} 个源音符自动编配为 ${project.notes.length} 个练习音符，原始音符保留在项目中。`:`共 ${project.notes.length} 个音符，${project.groups.length} 组同时发音。`;
    const provenance=project.source?.kind==='midi-search'?`<p>搜索曲名：${escapeHTML(project.source.query)}<br>曲库：${escapeHTML(project.source.provider)}<br>来源许可：${escapeHTML(project.source.license || '未注明')}<br>自动指法是为练习安排的建议，不代表原版谱的指法。</p>`:'';
    $('project-info-body').innerHTML=`<p>转谱：${escapeHTML(transcription)}<br>指法：${escapeHTML(fingering)}<br>${arrangement}简谱为练习视图，按 4/4 参考分组，保留识别所得的起止时间。</p>${provenance}<p>蓝牙 MIDI 输入连接后，可按当前高亮音组校对实时音高；音频转谱稿可能有误。定速模式按时间自动推进，练习校对建议使用手动模式固定当前音组。</p>${warnings?`<ul>${warnings}</ul>`:''}`;
    $('project-info').open=!!warnings;
  }
  function readMappedOnly(){try{return localStorage.getItem('piano-light-studio-mapped-only-v1')==='true';}catch(_){return false;}}
  function mappedPitch(pitch){return (config.mapping[pitch] || []).some(index=>Number.isInteger(index)&&index>=0&&index<config.ledCount);}
  function selected(note) { return !!note && (state.hand === 'both' || note.hand === state.hand) && (!state.mappedOnly || mappedPitch(note.pitch)); }
  function mappedOnlyStats(){
    let black=0,white=0;const blackKeys=new Set(),whiteKeys=new Set();
    for(const note of state.project?.notes || []){
      if((state.hand!=='both'&&note.hand!==state.hand)||mappedPitch(note.pitch))continue;
      if([1,3,6,8,10].includes(note.pitch%12)){black++;blackKeys.add(note.pitch);}
      else{white++;whiteKeys.add(note.pitch);}
    }
    return {black,white,blackKeys:blackKeys.size,whiteKeys:whiteKeys.size};
  }
  function renderMappedOnlySummary(){
    const input=$('mapped-only'),summary=$('mapped-only-summary');if(!input||!summary)return;
    input.checked=state.mappedOnly;const counts=mappedOnlyStats();
    summary.textContent=`${state.mappedOnly?'已':'开启将'}省略黑键音符 ${counts.black} 次、白键音符 ${counts.white} 次（涉及黑键 ${counts.blackKeys} 个、白键 ${counts.whiteKeys} 个；按当前手别统计）。`;
  }
  function setMappedOnly(enabled){
    const resume=state.playing;pause();state.mappedOnly=enabled;
    try{localStorage.setItem('piano-light-studio-mapped-only-v1',String(enabled));}catch(_){}
    if(state.project&&!groupHasSelected(state.groupIndex)){
      const next=state.project.groups.findIndex((group,index)=>index>=state.groupIndex&&groupHasSelected(index));
      if(next>=0){state.groupIndex=next;state.time=state.project.groups[next].time;state.scorePage=Math.floor(next/PAGE_SIZE);}
    }
    resetMidiJudgement();renderScore();renderTransport();updateActive(true);updateClock(true);
    if(resume)play();
  }
  function notesInGroup(group) { return (group?.note_ids || []).map(id => state.noteById.get(String(id))).filter(Boolean); }
  function groupHasSelected(index) { return notesInGroup(state.project?.groups[index]).some(selected); }
  function midiExpectedPitches() {
    return [...new Set(notesInGroup(state.project?.groups[state.groupIndex]).filter(selected).map(note=>note.pitch))];
  }
  function renderMidiJudgement() {
    const feedback=$('midi-feedback');
    if(feedback) { feedback.textContent=state.midiFeedback;feedback.dataset.state=state.midiFeedbackType; }
    document.querySelectorAll('.score-note').forEach(element=>{
      const note=state.noteById.get(element.dataset.note);
      element.classList.toggle('midi-correct',!!note && state.midiJudgedGroup===state.groupIndex && state.midiMatched.has(note.pitch));
    });
  }
  function setMidiFeedback(message,type='') {
    state.midiFeedback=message;state.midiFeedbackType=type;renderMidiJudgement();
  }
  function resetMidiJudgement() {
    state.midiJudgedGroup=state.groupIndex;state.midiMatched.clear();state.midiFeedbackType='';
    state.midiFeedback=(state.midiInput||state.midiBleConnection)?'请弹奏当前高亮音组。':'点击“搜索并连接蓝牙钢琴”，直接连接琴的蓝牙 MIDI 服务。';
    renderMidiJudgement();
  }
  function matchHeldMidiPitches(expected=midiExpectedPitches()) {
    const held=new Set([...state.midiHeld].map(token=>Number(token.split(':')[1])));
    state.midiJudgedGroup=state.groupIndex;
    state.midiMatched=new Set(expected.filter(pitch=>held.has(pitch)));
    return expected.filter(pitch=>!held.has(pitch));
  }
  function judgeMidiPitch(pitch) {
    const pressed=`${pitchName(pitch)}（音符编号 ${pitch}）`;
    if(window.PianoLightCalibration?.active)return;
    if(state.mode==='correct'&&!state.playing){setMidiFeedback(`检测到 ${pressed}；点击「开始练习」后，弹对当前音组自动推进。`,'help');return;}
    const expected=midiExpectedPitches();
    if(!expected.length) { setMidiFeedback(`检测到 ${pressed}；当前音组在所选手别下没有音符，请调整左手／右手筛选。`,'help');return; }
    const remaining=matchHeldMidiPitches(expected);
    if(expected.includes(pitch)) {
      if(!remaining.length) {
        if(state.mode==='correct'&&state.playing){
          step(1);
          if(!state.playing)setMidiFeedback('正确！这一段练习已完成。','correct');
        }else setMidiFeedback(`正确！本组 ${expected.length} 个不同音高已同时按住，按「下一组」继续。`,'correct');
      }
      else setMidiFeedback(`当前同时按住 ${state.midiMatched.size}/${expected.length} 个音，还需同时按住 ${remaining.map(pitchName).join('、')}。`,'help');
    } else {
      setMidiFeedback(`弹错 ${pressed}；当前组需要 ${expected.map(pitchName).join('、')}。`,'wrong');
    }
  }
  function setMidiConnection(message,type='') {
    if(type==='connected'||type==='error'||message==='已断开')state.midiHeld.clear();
    const status=$('midi-connection-status');status.textContent=message;status.dataset.state=type;
  }
  function midiInputs() {
    return [...(state.midiAccess?.inputs.values() || [])].filter(input=>input.state!=='disconnected');
  }
  function renderMidiInputs() {
    const select=$('midi-input');
    const inputs=midiInputs();
    const selectedId=state.midiInput?.id || select.value;
    select.innerHTML=`<option value="">${inputs.length?'选择 MIDI 输入设备':'未发现 MIDI 输入设备'}</option>${inputs.map((input,index)=>{
      const label=[input.name,input.manufacturer].filter(Boolean).join(' · ') || `MIDI 输入 ${index+1}`;
      return `<option value="${escapeHTML(input.id)}">${escapeHTML(label)}</option>`;
    }).join('')}`;
    select.disabled=!inputs.length;
    if(inputs.some(input=>input.id===selectedId)) select.value=selectedId;
    else if(inputs.length===1) select.value=inputs[0].id;
    return inputs;
  }
  async function ensureMidiAccess() {
    if(typeof navigator.requestMIDIAccess!=='function') throw new Error('此浏览器不支持网页 MIDI，请使用新版 Edge 或 Chrome。');
    if(state.midiAccess)return state.midiAccess;
    state.midiAccess=await navigator.requestMIDIAccess({sysex:false});
    state.midiAccess.onstatechange=handleMidiStateChange;
    return state.midiAccess;
  }
  function handleMidiMessage(event) {
    const [status,pitch,velocity]=event.data || [];
    window.dispatchEvent(new CustomEvent('piano-midi-message',{detail:Array.from(event.data || [])}));
    const token=`${status&15}:${pitch}`;
    if((status&0xf0)===0x80||((status&0xf0)===0x90&&velocity===0)){
      state.midiHeld.delete(token);
      if(!window.PianoLightCalibration?.active&&(state.mode!=='correct'||state.playing)){
        const expected=midiExpectedPitches(),remaining=matchHeldMidiPitches(expected);
        if(expected.length&&remaining.length)setMidiFeedback(`当前同时按住 ${state.midiMatched.size}/${expected.length} 个音，还需同时按住 ${remaining.map(pitchName).join('、')}。`,'help');
        else renderMidiJudgement();
      }
      return;
    }
    if((status & 0xf0)===0x90 && velocity>0) {
      if(state.midiHeld.has(token))return;
      state.midiHeld.add(token);
      judgeMidiPitch(pitch);
    }
  }
  async function toggleBluetoothMidi(includeAllDevices=false) {
    if(state.midiBleConnection) {
      const connection=state.midiBleConnection;state.midiBleConnection=null;connection.disconnect();
      $('midi-ble-connect').textContent='搜索并连接蓝牙钢琴';
      $('midi-ble-all').disabled=false;
      setMidiConnection('已断开');resetMidiJudgement();return;
    }
    try {
      let closingInput=Promise.resolve();
      if(state.midiInput) {
        const input=state.midiInput;state.midiInput=null;input.onmidimessage=null;
        closingInput=input.close().catch(()=>{});
        $('midi-connect').textContent='连接 MIDI';
      }
      setMidiConnection('等待选择钢琴');setMidiFeedback('请在浏览器弹出的蓝牙设备列表中选择钢琴。');
      let connection=null;
      const pendingConnection=window.BleMidi.connect({includeAllDevices,
        onMessage:data=>handleMidiMessage({data}),
        onDisconnected:()=>{
          if(!state.midiBleConnection && !connection)return;
          if(state.midiBleConnection!==connection)return;
          state.midiBleConnection=null;$('midi-ble-connect').textContent='搜索并连接蓝牙钢琴';
          $('midi-ble-all').disabled=false;
          setMidiConnection('蓝牙已断开','error');resetMidiJudgement();
        }});
      connection=await pendingConnection;
      state.midiBleConnection=connection;
      await closingInput;
      $('midi-ble-connect').textContent='断开蓝牙 MIDI';
      $('midi-ble-all').disabled=true;
      setMidiConnection(`已连接：${connection.name}`,'connected');resetMidiJudgement();
    } catch(error) {
      $('midi-ble-connect').textContent='搜索并连接蓝牙钢琴';
      $('midi-ble-all').disabled=false;
      setMidiConnection('蓝牙连接失败','error');
      let message=error.message || '无法连接蓝牙 MIDI 设备。';
      if(error.name==='NotFoundError') message='未选择设备或列表中没有可见设备。请确认钢琴已开机，并先断开手机的 MIDI 连接；找不到时再试“全部设备”。';
      else if(error.name==='SecurityError') message='浏览器没有蓝牙权限，请在新版 Chrome 或 Edge 中打开本机页面。';
      else if(error.name==='NetworkError') message='蓝牙连接中断，或所选设备没有可用的 MIDI 蓝牙服务。';
      setMidiFeedback(message,'help');
    }
  }
  function handleMidiStateChange(event) {
    const port=event.port;
    renderMidiInputs();
    if(state.midiInput && port?.id===state.midiInput.id && port.state==='disconnected') {
      state.midiInput.onmidimessage=null;state.midiInput=null;
      $('midi-connect').textContent='连接 MIDI';
      setMidiConnection('MIDI 设备已断开','error');resetMidiJudgement();
    } else if(port?.type==='input' && port.state==='connected' && !state.midiInput) {
      setMidiConnection('发现 MIDI 输入');setMidiFeedback('已发现输入设备，请选择后连接。');
    }
  }
  async function scanMidiDevices() {
    try {
      await ensureMidiAccess();
      const inputs=renderMidiInputs();
      if(!inputs.length) {
        setMidiConnection('未发现输入设备');
        setMidiFeedback('电脑没有提供 MIDI 输入端口。蓝牙琴请点上方“搜索并连接蓝牙钢琴”，不依赖 Windows 的设备分类。','help');
      } else {
        setMidiConnection(state.midiInput?`已连接：${state.midiInput.name || 'MIDI 输入'}`:`发现 ${inputs.length} 个输入`,state.midiInput?'connected':'');
        if(!state.midiInput)setMidiFeedback('选择 MIDI 输入设备后，点击「连接 MIDI」。');
      }
    } catch(error) {
      setMidiConnection('无法扫描','error');setMidiFeedback(error.message || '浏览器拒绝了 MIDI 访问。','wrong');
    }
  }
  async function connectMidiInput(input) {
    if(!input) { setMidiFeedback('请先选择一个 MIDI 输入设备。','help');return; }
    if(state.midiInput?.id===input.id) return;
    const previous=state.midiInput;
    if(previous) { previous.onmidimessage=null;try{await previous.close();}catch(_){} }
    state.midiInput=null;
    try {
      await input.open();
      if(input.state==='disconnected')throw new Error('连接时 MIDI 设备已断开，请重新扫描。');
      state.midiInput=input;input.onmidimessage=handleMidiMessage;
      $('midi-connect').textContent='断开 MIDI';
      setMidiConnection(`已连接：${input.name || 'MIDI 输入'}`,'connected');resetMidiJudgement();
    } catch(error) {
      $('midi-connect').textContent='连接 MIDI';setMidiConnection('连接失败','error');setMidiFeedback(error.message || '无法打开这个 MIDI 输入设备。','wrong');
    }
  }
  async function toggleMidiConnection() {
    if(state.midiInput) {
      const input=state.midiInput;state.midiInput=null;input.onmidimessage=null;
      try{await input.close();}catch(_){}
      $('midi-connect').textContent='连接 MIDI';setMidiConnection('已断开');resetMidiJudgement();return;
    }
    try {
      const access=await ensureMidiAccess();
      const inputs=renderMidiInputs();
      const input=access.inputs.get($('midi-input').value) || (inputs.length===1?inputs[0]:null);
      if(!input) {
        setMidiConnection(inputs.length?'请选择输入设备':'未发现输入设备',inputs.length?'':'error');
        setMidiFeedback(inputs.length?'请选择一个 MIDI 输入设备后再连接。':'请先在 Windows 蓝牙设置中配对键盘，再扫描设备。','help');return;
      }
      await connectMidiInput(input);
    } catch(error) {
      setMidiConnection('无法连接','error');setMidiFeedback(error.message || '浏览器拒绝了 MIDI 访问。','wrong');
    }
  }
  function indexAt(time) {
    const groups=state.project?.groups || [];
    let low=0,high=groups.length;
    while(low<high) { const mid=(low+high)>>1;if(groups[mid].time<=time+0.001) low=mid+1;else high=mid; }
    return clamp(low-1,0,Math.max(0,groups.length-1));
  }
  function degreeMarkup(note) {
    const jianpu=note.jianpu;
    const degree=String(jianpu.degree || '1');
    const accidentals=(degree.match(/^[#♯b♭]+/) || [''])[0].replaceAll('#','♯').replaceAll('b','♭');
    const number=degree.slice((degree.match(/^[#♯b♭]+/) || [''])[0].length);
    const octave=clamp(Math.round(finite(jianpu.octave)), -4,4);
    const beats=note.beat_duration;
    let under=0,extension='',dot=false;
    if(beats<0.3) under=2;else if(beats<0.7) under=1;
    if(beats<0.16) under=3;
    if(beats>=1.75) extension='–'.repeat(Math.min(3,Math.max(1,Math.floor(beats)-1)));
    const approximateBase=beats<0.75?0.5:beats<1.75?1:beats<3.5?2:4;
    dot=Math.abs(beats-approximateBase*1.5)<0.12;
    const rhythm=under?`under-${under}`:'';
    return `<span class="numbered-note ${rhythm}" title="${escapeHTML(pitchName(note.pitch))} · ${Number(beats.toFixed(2))} 拍"><span class="octave-dots">${octave>0?'·'.repeat(octave):'&nbsp;'}</span><span class="note-value">${accidentals?`<span class="accidental">${escapeHTML(accidentals)}</span>`:''}${escapeHTML(number)}${extension?`<span class="extension">${extension}</span>`:''}${dot?'<span class="duration-dot">·</span>':''}</span><span class="octave-dots">${octave<0?'·'.repeat(-octave):'&nbsp;'}</span></span>`;
  }
  function renderScore() {
    renderMappedOnlySummary();
    const groups=state.project?.groups || [];
    const start=state.scorePage*PAGE_SIZE,end=Math.min(groups.length,start+PAGE_SIZE);
    const maxChord=groups.slice(start,end).reduce((max,group)=>{const notes=notesInGroup(group);return Math.max(max,notes.filter(note=>note.hand==='L').length,notes.filter(note=>note.hand==='R').length);},1);
    document.querySelector('.score-wrapper').style.setProperty('--staff-height',`${Math.max(132,maxChord*48+16)}px`);
    scoreElements=new Map();
    if(!groups.length) { $('score-grid').innerHTML='<div class="empty-score">导入一首音乐，开始你的练习。</div>';return; }
    $('score-grid').innerHTML=groups.slice(start,end).map((group,offset) => {
      const index=start+offset;
      const notes=notesInGroup(group).filter(note=>!state.mappedOnly||mappedPitch(note.pitch));
      if(state.mappedOnly&&!notes.some(selected))return '';
      const handMarkup=hand => {
        const handNotes=notes.filter(note => note.hand===hand).sort((a,b)=>b.pitch-a.pitch);
        return `<div class="score-hand ${state.hand!=='both' && state.hand!==hand?'filtered':''}">${handNotes.length?handNotes.map(note=>`<span class="score-note" data-note="${escapeHTML(note.id)}" style="--finger-color:${colorFor(note)}">${degreeMarkup(note)}<span class="note-finger" title="${hand==='R'?'右':'左'}手 ${note.finger} 指">${note.finger}</span></span>`).join(''):'<span class="score-rest">·</span>'}</div>`;
      };
      return `<button class="score-group ${index===state.groupIndex?'current':''} ${index<state.groupIndex?'played':''}" data-index="${index}" aria-label="第 ${index+1} 音组，${timeLabel(group.time,true)}，${notes.map(note=>pitchName(note.pitch)).join('、')}"><span class="group-label"><strong>${String(index+1).padStart(2,'0')}</strong><span>${timeLabel(group.time)}</span></span>${handMarkup('R')}${handMarkup('L')}</button>`;
    }).join('');
    $('score-grid').querySelectorAll('.score-group').forEach(element=>scoreElements.set(Number(element.dataset.index),element));
    $('score-range').textContent=`${start+1}–${end} / ${groups.length} 组`;
    $('score-page-prev').disabled=start===0;$('score-page-next').disabled=end===groups.length;
    state.renderedCurrent=-1;
    updateScoreCurrent(false);
  }
  function updateScoreCurrent(autoscroll=true) {
    if(state.midiJudgedGroup!==state.groupIndex) {
      state.midiJudgedGroup=state.groupIndex;state.midiMatched.clear();state.midiFeedbackType='';
      state.midiFeedback=(state.midiInput||state.midiBleConnection)?'请弹奏当前高亮音组。':'点击“搜索并连接蓝牙钢琴”，直接连接琴的蓝牙 MIDI 服务。';
    }
    renderMidiJudgement();
    if(state.renderedCurrent===state.groupIndex)return;
    const previous=scoreElements.get(state.renderedCurrent);
    if(previous) { previous.classList.remove('current');previous.removeAttribute('aria-current'); }
    if(autoscroll && !scoreElements.has(state.groupIndex)) { state.scorePage=Math.floor(state.groupIndex/PAGE_SIZE);renderScore();return; }
    scoreElements.forEach((element,index)=>element.classList.toggle('played',index<state.groupIndex));
    const current=scoreElements.get(state.groupIndex);
    if(current) {
      current.classList.add('current');current.setAttribute('aria-current','step');
      if(autoscroll) {
        const scroller=$('score-scroll');
        const left=current.offsetLeft-scroller.offsetLeft;
        if(left<scroller.scrollLeft+10 || left+current.offsetWidth>scroller.scrollLeft+scroller.clientWidth-10) {
          scroller.scrollTo({left:Math.max(0,left-scroller.clientWidth/2+current.offsetWidth/2),behavior:'smooth'});
        }
      }
    }
    state.renderedCurrent=state.groupIndex;
    $('current-group').textContent=`第 ${state.groupIndex+1} / ${state.project?.groups.length || 0} 组`;
  }
  function renderLegend() {
    const names=['拇指','食指','中指','无名指','小指'];
    $('finger-legend').innerHTML=['L','R'].map(hand=>`<div class="legend-hand"><span class="legend-hand-label">${hand==='L'?'左手':'右手'}</span>${names.map((name,index)=>`<span class="finger-item" style="--finger-color:${colorFor({hand,finger:index+1})}"><span class="finger-swatch">${index+1}</span>${name}</span>`).join('')}</div>`).join('');
  }
  function renderKeyboard() {
    keyElements.clear();
    const first=config.firstPitch,last=first+config.keyCount-1;
    const isBlack=pitch=>[1,3,6,8,10].includes(pitch%12);
    const whites=[];
    for(let pitch=first;pitch<=last;pitch++)if(!isBlack(pitch))whites.push(pitch);
    const available=$('keyboard-scroll').clientWidth-46;
    const width=Math.max(650,available);
    const whiteWidth=width/Math.max(1,whites.length);
    $('keyboard').style.width=`${width}px`;
    let whiteIndex=0;
    $('keyboard').innerHTML=Array.from({length:config.keyCount},(_,index)=>{
      const pitch=first+index,black=isBlack(pitch);
      let left;
      if(black)left=(whiteIndex-0.32)*whiteWidth;
      else {left=whiteIndex*whiteWidth;whiteIndex++;}
      left=Math.max(0,left);
      const keyWidth=black?whiteWidth*0.64:whiteWidth-1;
      const label=(pitch%12===0 || pitch===first || pitch===last)?pitchName(pitch):'';
      return `<button class="piano-key ${black?'black-key':'white-key'}" style="left:${left}px;width:${keyWidth}px" data-pitch="${pitch}" title="${escapeHTML(pitchName(pitch))} · 点击测试对应灯珠" aria-label="测试 ${escapeHTML(pitchName(pitch))}"><span class="key-finger"></span><span class="key-name">${escapeHTML(label)}</span></button>`;
    }).join('');
    $('keyboard').querySelectorAll('.piano-key').forEach(element=>keyElements.set(Number(element.dataset.pitch),element));
    $('led-track').innerHTML=Array.from({length:config.ledCount},(_,index)=>`<span class="led-pixel" title="灯珠 ${index}"></span>`).join('');
    ledElements=[...$('led-track').children];
    state.activeSignature='';updateActive(true);updateMappingLabels();
  }
  function activeNotes(now=performance.now()) {
    if(state.testUntil>now)return state.testNotes;
    if(!state.playing || !state.project)return [];
    if(state.mode!=='timed')return notesInGroup(state.project.groups[state.groupIndex]).filter(selected);
    const time=state.time,notes=state.project.notes;
    let low=0,high=notes.length;
    const earliest=time-state.maxNoteDuration;
    while(low<high){const mid=(low+high)>>1;if(notes[mid].start<earliest)low=mid+1;else high=mid;}
    const result=[];
    for(let index=low;index<notes.length;index++){
      const note=notes[index];
      if(note.start>time+state.lookahead+0.00001)break;
      if(note.end>time+0.00001 && selected(note))result.push(note);
    }
    return result;
  }
  function pixelsFor(notes, mapping=config.mapping) {
    const pixels=new Map();
    // Later onsets win only when an explicitly configured LED is shared.
    for(const note of notes.slice().sort((a,b)=>a.start-b.start || a.pitch-b.pitch)) {
      const color=colorFor(note).slice(1);
      const r=parseInt(color.slice(0,2),16),g=parseInt(color.slice(2,4),16),b=parseInt(color.slice(4,6),16);
      const indices=mapping[note.pitch];
      if(!Array.isArray(indices))continue;
      const index=indices.find(index=>Number.isInteger(index) && index>=0 && index<config.ledCount);
      if(index!==undefined)pixels.set(index,{index,r,g,b});
    }
    return [...pixels.values()].sort((a,b)=>a.index-b.index);
  }
  function currentPixels(now=performance.now()) {
    if(state.testUntil>now && state.testPixels)return state.testPixels;
    return pixelsFor(activeNotes(now));
  }
  function updateActive(force=false) {
    const notes=activeNotes();
    const isPending=note=>state.playing && state.mode==='timed' && note.start>state.time+0.005;
    const signature=notes.map(note=>`${String(note.id ?? `test-${note.pitch}`)}${isPending(note)?'p':'a'}`).join(',')+`/${state.testUntil>performance.now()?state.testUntil:''}/${state.playing}`;
    if(!force && signature===state.activeSignature)return;
    state.activeSignature=signature;state.activeNotes=notes;
    for(const element of keyElements.values()){element.classList.remove('lit','preview');element.style.removeProperty('--key-color');element.querySelector('.key-finger').textContent='';}
    for(const note of notes){
      const key=keyElements.get(note.pitch);
      if(!key)continue;
      key.classList.add('lit');key.style.setProperty('--key-color',colorFor(note));
      key.classList.toggle('preview',isPending(note));
      key.querySelector('.key-finger').textContent=String(note.finger);
    }
    for(const element of ledElements){element.classList.remove('lit');element.style.removeProperty('--led-color');}
    for(const pixel of currentPixels()){
      const element=ledElements[pixel.index];if(!element)continue;
      element.classList.add('lit');element.style.setProperty('--led-color',`rgb(${pixel.r},${pixel.g},${pixel.b})`);
    }
    const activeIds=new Set(notes.map(note=>String(note.id)));
    $('score-grid').querySelectorAll('.score-note').forEach(element=>element.classList.toggle('sounding',activeIds.has(element.dataset.note)));
    $('live-notes').innerHTML=notes.length?notes.map(note=>`<span class="live-note ${isPending(note)?'pending':''}" style="--finger-color:${colorFor(note)}">${isPending(note)?'<span class="pending-label">预亮</span>':''}${escapeHTML(pitchName(note.pitch))}<span>${note.hand==='L'?'左':'右'}${note.finger}</span></span>`).join(''):`<span class="muted">${state.playing?'等待下一组音符…':'点击开始，查看音符与指法'}</span>`;
    $('playing-dot').classList.toggle('active',!!notes.length);
    $('live-status').textContent=state.testUntil>performance.now()?'灯珠测试':state.playing?(state.mode==='correct'?'等待弹对':state.mode==='manual'?'等待你推进':'跟灯弹奏'):state.time>0?'已暂停':'准备就绪';
  }
  function renderTransport() {
    $('play-label').textContent=state.playing?'暂停练习':state.mode==='manual'?'点亮这一组':'开始练习';
    $('play-icon').querySelector('use').setAttribute('href',state.playing?'#i-pause':'#i-play');
    $('play-button').classList.toggle('is-playing',state.playing);
    $('play-button').setAttribute('aria-label',state.playing?'暂停练习':'开始练习');
    $('mode-hint').textContent=state.mode==='correct'?'当前音组持续亮灯，要求的琴键必须同时按住才进入下一组；松开即取消，逐个弹不累计。空格暂停／继续，需要连接钢琴。':state.mode==='manual'?'当前音组持续亮灯，按 → 或「下一组」推进；空格熄灯／继续。普通钢琴无需接入电子琴键。':`灯光提前 ${state.lookahead.toFixed(2)} 秒提示。空格播放／暂停，← → 跳转音组；普通钢琴按设定速度跟练。`;
    $('speed-range').disabled=state.mode!=='timed';
    $('speed-control')?.classList.toggle('disabled',state.mode!=='timed');
    $('loop-button').classList.toggle('active',state.loop);$('loop-button').setAttribute('aria-pressed',String(state.loop));
    $('loop-settings').hidden=!state.loop;
    document.querySelectorAll('[data-mode]').forEach(button=>{button.classList.toggle('selected',button.dataset.mode===state.mode);button.setAttribute('aria-pressed',String(button.dataset.mode===state.mode));});
    document.querySelectorAll('[data-hand]').forEach(button=>{button.classList.toggle('selected',button.dataset.hand===state.hand);button.setAttribute('aria-pressed',String(button.dataset.hand===state.hand));});
  }
  function updateClock(force=false) {
    const now=performance.now();
    if(!force && now-state.lastClockPaint<80)return;
    state.lastClockPaint=now;
    $('time-current').textContent=state.time<0?`-${Math.abs(state.time).toFixed(1)}`:timeLabel(state.time);
    $('timeline').value=String(Math.max(0,state.time));rangeFill($('timeline'));
  }
  function currentTimedPosition(now=performance.now()) {
    return state.anchorTime+(now-state.anchorNow)/1000*state.rate;
  }
  function clearTest(){state.testUntil=0;state.testNotes=[];state.testPixels=null;}
  function pause() {
    if(state.playing && state.mode==='timed')state.time=currentTimedPosition();
    state.playing=false;clearTest();
    state.serialForceClear=true;
    if(state.project)state.time=clamp(state.time,0,state.project.duration);
    updateActive(true);renderTransport();updateClock(true);syncSerial();
  }
  function play() {
    if(!state.project)return;
    if(state.mode==='correct'&&!state.playing){
      if(!state.midiInput&&!state.midiBleConnection){toast('请先连接钢琴，再使用弹对推进。','error');return;}
      resetMidiJudgement();
    }
    clearTest();
    if(state.playing){pause();return;}
    if(state.mode==='timed'){
      if(state.time>=state.project.duration-0.02)state.time=state.loop?state.loopA:0;
      if(state.loop && (state.time<state.loopA || state.time>=state.loopB))state.time=state.loopA;
      if(state.time===0 && state.lookahead>0)state.time=-state.lookahead;
      state.anchorTime=state.time;state.anchorNow=performance.now();
    } else if(!groupHasSelected(state.groupIndex)) {
      const next=state.project.groups.findIndex((group,index)=>index>=state.groupIndex && groupHasSelected(index));
      if(next<0){toast('当前位置之后没有所选手别的音符。');return;}
      state.groupIndex=next;state.time=state.project.groups[next].time;
    }
    state.playing=true;state.serialForceClear=false;renderTransport();updateScoreCurrent();updateActive(true);
  }
  function seek(time, groupIndex=null) {
    pause();
    state.time=clamp(finite(time),0,state.project?.duration || 0);
    state.groupIndex=groupIndex ?? indexAt(state.time);
    updateScoreCurrent();updateClock(true);updateActive(true);
  }
  function step(direction) {
    if(!state.project)return;
    if(state.mode==='timed'){const index=clamp(state.groupIndex+direction,0,state.project.groups.length-1);seek(state.project.groups[index].time,index);return;}
    const groups=state.project.groups;
    let next=state.groupIndex+direction;
    while(next>=0 && next<groups.length && (!groupHasSelected(next) || (state.loop && (groups[next].time<state.loopA || groups[next].time>=state.loopB))))next+=direction;
    if(next<0 || next>=groups.length){
      if(state.loop){const candidates=groups.map((group,index)=>index).filter(index=>groupHasSelected(index)&&groups[index].time>=state.loopA&&groups[index].time<state.loopB);next=direction>0?candidates[0]:candidates[candidates.length-1];}
      if(next===undefined || next<0 || next>=groups.length){pause();toast(direction>0?'这一段练习完成。可回到开头再来一遍。':'已到第一组。');return;}
    }
    clearTest();state.groupIndex=next;state.time=groups[next].time;state.playing=true;state.serialForceClear=false;
    if(state.mode==='correct')resetMidiJudgement();
    updateScoreCurrent();updateClock(true);updateActive(true);renderTransport();
  }
  function animate(now) {
    if(state.playing && state.mode==='timed' && state.project){
      state.time=currentTimedPosition(now);
      if(state.loop && state.time>=state.loopB){
        const length=state.loopB-state.loopA;
        state.time=state.loopA+(state.time-state.loopB)%Math.max(0.1,length);state.anchorTime=state.time;state.anchorNow=now;
      }
      if(state.time>=state.project.duration){state.time=state.project.duration;state.playing=false;state.serialForceClear=true;renderTransport();}
      const index=indexAt(state.time+state.lookahead);
      if(index!==state.groupIndex){state.groupIndex=index;updateScoreCurrent();}
      updateClock();
    }
    if(state.testUntil && state.testUntil<=now)clearTest();
    updateActive();
    requestAnimationFrame(animate);
  }
  async function syncSerial() {
    if(window.PianoLightCalibration?.active)return;
    if(!state.serialConnected || state.serialBusy)return;
    const now=performance.now();
    // Maximum 12.5 Hz; unchanged frames are sent only as a 500 ms watchdog heartbeat.
    if(now-state.serialLastSent<80)return;
    const pixels=state.serialForceClear?[]:currentPixels(now);
    const frame={pixels,brightness:config.brightness};
    const signature=JSON.stringify(frame);
    if(signature===state.serialLastFrame && now-state.serialLastSent<500 && !state.serialForceClear)return;
    state.serialBusy=true;state.serialLastSent=now;state.serialLastFrame=signature;state.serialForceClear=false;
    try{await post('/api/serial/frame',frame);}
    catch(error){
      state.serialConnected=false;setDeviceState();
      $('serial-message').textContent=`灯带连接已中断：${error.message}`;
      toast(`灯带连接已中断：${error.message}`,'error');
    } finally{state.serialBusy=false;}
  }
  function setDeviceState() {
    $('device-title').textContent=state.serialConnected?'实物灯带已连接':'灯带预览模式';
    $('device-subtitle').textContent=state.serialConnected?'与当前练习时间轴同步':'连接 ESP32 后同步到实物';
    $('device-dot').classList.toggle('neutral',!state.serialConnected);
    $('connect-button').innerHTML=`<svg class="icon"><use href="#i-plug"/></svg>${state.serialConnected?'断开灯带':'连接灯带'}`;
    $('connect-button').classList.toggle('primary',!state.serialConnected);
    $('connect-button').classList.toggle('secondary',state.serialConnected);
    $('serial-port').disabled=state.serialConnected;
  }
  function fillPorts(ports) {
    const previous=$('serial-port').value;
    $('serial-port').innerHTML=`<option value="">${ports.length?'选择 ESP32 串口':'未发现可用串口'}</option>`+ports.map(port=>`<option value="${escapeHTML(port.device)}">${escapeHTML(port.device)}${port.description?` · ${escapeHTML(port.description)}`:''}</option>`).join('');
    if(ports.some(port=>port.device===previous))$('serial-port').value=previous;
    else if(ports.length===1)$('serial-port').value=ports[0].device;
  }
  async function refreshPorts(showFeedback=true) {
    $('refresh-ports').disabled=true;
    try{const data=await request('/api/ports');fillPorts(Array.isArray(data.ports)?data.ports:[]);if(showFeedback && !data.ports?.length)toast('未发现串口。请连接 ESP32，再点刷新。');}
    catch(error){if(showFeedback)toast(`无法读取串口：${error.message}`,'error');}
    finally{$('refresh-ports').disabled=false;}
  }
  async function toggleConnection() {
    $('connect-button').disabled=true;
    try{
      if(state.serialConnected){
        pause();
        // Disconnect endpoint also clears the LEDs, including when a frame is still in flight.
        await post('/api/serial/disconnect',{});state.serialConnected=false;
        $('serial-message').textContent='灯带已熄灭并断开，软件预览仍可使用。';toast('灯带已断开。');
      }else{
        const port=$('serial-port').value;
        if(!port){toast('请先选择 ESP32 串口。');return;}
        await post('/api/serial/connect',{port,baud:115200});
        state.serialConnected=true;state.serialLastFrame='';state.serialLastSent=0;state.serialForceClear=true;
        $('serial-message').textContent=`已连接 ${port} · 亮度 ${Math.round(config.brightness*100)}%${config.confirmed?'':' · 当前为示例映射，请先核对琴键位置。'}`;
        await syncSerial();toast('灯带已连接，开始练习即可同步。','success');
      }
      setDeviceState();
    }catch(error){toast(`连接操作失败：${error.message}`,'error');$('serial-message').textContent=error.message;}
    finally{$('connect-button').disabled=false;}
  }
  function updateMappingLabels() {
    $('mapping-badge').textContent=config.confirmed?'已保存安装校准':'示例映射 · 安装后请校准';
    $('mapping-badge').classList.toggle('confirmed',config.confirmed);
    $('calibration-summary').textContent=config.confirmed?'已核对映射':'示例映射';
    $('led-count-label').textContent=`${config.ledCount} 颗 · 亮度 ${Math.round(config.brightness*100)}%`;
    $('brightness-value').textContent=`${Math.round(config.brightness*100)}%`;
    $('mapping-confirmed').checked=config.confirmed;
    const unmapped=Object.values(config.mapping).filter(indices=>!indices.length).length;
    const counts=new Map();
    for(const indices of Object.values(config.mapping))for(const index of indices)counts.set(index,(counts.get(index)||0)+1);
    const shared=[...counts.values()].filter(count=>count>1).length;
    $('mapping-message').textContent=`${pitchName(config.firstPitch)}–${pitchName(config.firstPitch+config.keyCount-1)} · ${config.keyCount} 键 / ${config.ledCount} 灯珠。${config.confirmed?'已保存安装校准。':'初始映射仅作示例，尚未确认实物位置。'}${unmapped?` ${unmapped} 个琴键未映射，不会点亮邻键。`:''}${shared?` ${shared} 颗灯珠被多个琴键共用，和弦时以较晚音符颜色为准。`:''}`;
  }
  function populateCalibration() {
    $('first-pitch').innerHTML=Array.from({length:88},(_,i)=>`<option value="${i+21}">${escapeHTML(pitchName(i+21))}${i+21===60?' · 中央 C':''}</option>`).join('');
    $('first-pitch').value=String(config.firstPitch);$('key-count').value=String(config.keyCount);$('led-count').value=String(config.ledCount);
    $('brightness-range').value=String(Math.round(config.brightness*100));rangeFill($('brightness-range'));
    $('lookahead-range').value=String(Math.round(state.lookahead*100));rangeFill($('lookahead-range'));
    $('lookahead-value').textContent=`${state.lookahead.toFixed(2)} 秒`;
    populateCalibrationKeys();updateMappingLabels();
  }
  function populateCalibrationKeys() {
    const previous=finite($('calibration-pitch').value,60);
    $('calibration-pitch').innerHTML=Array.from({length:config.keyCount},(_,i)=>`<option value="${config.firstPitch+i}">${escapeHTML(pitchName(config.firstPitch+i))}${config.firstPitch+i===60?' · 中央 C':''}</option>`).join('');
    $('calibration-pitch').value=String(clamp(previous,config.firstPitch,config.firstPitch+config.keyCount-1));
    showKeyMapping();
  }
  function showKeyMapping() {
    const pitch=Number($('calibration-pitch').value);
    $('calibration-leds').value=(config.mapping[pitch] || []).join(',');
  }
  function readLedInput() {
    const text=$('calibration-leds').value.trim();
    if(!text)return [];
    const fragments=text.split(/[,，\s]+/).filter(Boolean);
    if(fragments.some(fragment=>!/^\d+$/.test(fragment)))throw new Error('灯珠编号须为整数，多个编号用逗号分隔。');
    const values=fragments.map(Number);
    if(values.some(value=>value<0 || value>=config.ledCount))throw new Error(`灯珠编号范围为 0–${config.ledCount-1}。`);
    return [...new Set(values)];
  }
  function testKey(pitch=Number($('calibration-pitch').value),indices=null) {
    pause();
    try{
      const leds=indices ?? readLedInput();
      if(!leds.length){toast(`${pitchName(pitch)} 未映射灯珠；保持熄灯。`);return;}
      const note={id:`test-${pitch}`,pitch,hand:'R',finger:1,start:0,end:1,color:state.project?.palette?.R1 || palette.R1};
      state.testNotes=[note];state.testPixels=pixelsFor([note],{[pitch]:leds});state.testUntil=performance.now()+700;
      state.serialForceClear=false;state.activeSignature='';updateActive(true);
      if(!state.serialConnected)toast(`预览 ${pitchName(pitch)} → 灯珠 ${leds.join(', ')}；连接 ESP32 后可测试实物。`);
    }catch(error){toast(error.message,'error');}
  }
  function generateMapping() {
    pause();
    config.firstPitch=clamp(Math.round(finite($('first-pitch').value,21)),21,108);
    config.keyCount=clamp(Math.round(finite($('key-count').value,88)),1,Math.min(88,109-config.firstPitch));
    config.ledCount=clamp(Math.round(finite($('led-count').value,144)),1,512);
    config.mapping=makeMapping(config.firstPitch,config.keyCount,config.ledCount);config.confirmed=false;
    $('key-count').value=String(config.keyCount);$('led-count').value=String(config.ledCount);
    persistConfig();populateCalibrationKeys();renderKeyboard();
    toast('已生成初始映射。请测试实际琴键位置，再保存安装校准。');
  }
  function saveKey() {
    try{
      const values=readLedInput(),pitch=Number($('calibration-pitch').value);
      pause();config.mapping[pitch]=values;config.confirmed=false;
      persistConfig();updateMappingLabels();updateActive(true);
      toast(`已保存 ${pitchName(pitch)} → ${values.length?`灯珠 ${values.join(', ')}`:'不点灯'}。`,'success');
    }catch(error){toast(error.message,'error');}
  }
  function setJob(status,message) {
    const panel=$('job-panel');panel.hidden=false;panel.className=`job-panel ${status}`;
    $('job-title').textContent=status==='error'?'本次处理未完成':status==='done'?'练习已自动生成':'正在自动生成练习';
    $('job-message').textContent=message;
  }
  function setImporting(value) {
    state.importing=value;$('drop-zone').classList.toggle('busy',value);$('drop-zone').setAttribute('aria-disabled',String(value));
    $('file-input').disabled=value;$('demo-button').disabled=value;
    $('find-midi').disabled=value;$('song-query').disabled=value;
  }
  async function importFile(file) {
    if(!file || state.importing)return;
    if(!/\.(mp3|wav|flac|ogg|mid|midi|ncm)$/i.test(file.name)){toast('请选择 MP3、WAV、FLAC、OGG、MIDI 或网易云 NCM 文件。','error');return;}
    if(file.size>64*1024*1024){toast('单个文件最大 64 MB，请选择较小的音乐文件。','error');return;}
    pause();setImporting(true);setJob('running',/\.ncm$/i.test(file.name)?`正在导入 ${file.name}，将先自动转换为 MP3，再生成练习…`:`正在导入 ${file.name}…`);
    try{
      const tonic=Number($('import-tonic').value);
      const params=new URLSearchParams({filename:file.name,tonic:String(tonic),hand_size:$('hand-size').value});
      if($('import-bpm').value.trim())params.set('bpm',String(clamp(finite($('import-bpm').value,100),20,300)));
      const job=await request(`/api/import?${params}`,{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:file});
      if(!job.job_id)throw new Error('服务未返回处理任务编号。');
      let result;
      while(true){
        await new Promise(resolve=>setTimeout(resolve,650));
        result=await request(`/api/jobs/${encodeURIComponent(job.job_id)}`);
        if(result.status==='done'){if(!result.project)throw new Error('处理完成但未返回练习项目。');break;}
        if(result.status==='error')throw new Error(result.error || result.message || '自动处理失败。');
        setJob('running',result.message || '正在识别音符、生成双手指法与简谱灯光…');
      }
      loadProject(result.project,true);setJob('done',`${file.name} · 已自动生成音符、指法、简谱和灯光，可直接开始练习。`);
      refreshStatus();
    }catch(error){setJob('error',error.message);toast(error.message,'error');}
    finally{setImporting(false);$('file-input').value='';}
  }
  async function loadDemo() {
    if(state.importing)return;
    $('demo-button').disabled=true;
    try{loadProject(await request('/api/demo'));$('job-panel').hidden=true;toast('已载入示例曲，按空格开始跟灯练习。','success');}
    catch(_){loadProject(fallbackDemo());toast('已载入内置示例。连接本地服务后可导入音乐。');}
    finally{$('demo-button').disabled=false;}
  }
  async function searchMidi(event) {
    event.preventDefault();
    if(state.importing)return;
    const query=$('song-query').value.trim();
    if(!query)return;
    pause();setImporting(true);setJob('running',`正在为「${query}」搜索 MIDI…`);
    try {
      const job=await post('/api/search-midi',{query,hand_size:$('hand-size').value});
      if(!job.job_id)throw new Error('服务未返回搜索任务编号。');
      while(true){
        await new Promise(resolve=>setTimeout(resolve,650));
        const result=await request(`/api/jobs/${encodeURIComponent(job.job_id)}`);
        if(result.status==='done'){
          if(!result.project)throw new Error('未取得可用曲谱。');
          loadProject(result.project,true);
          setJob('done',`已自动匹配「${result.project.title}」，MIDI 已下载，双手指法、简谱与灯光已生成。`);
          break;
        }
        if(result.status==='error')throw new Error(result.error || result.message || '没有找到可下载的匹配曲谱。');
        setJob('running',result.message || '正在寻找匹配曲谱…');
      }
    } catch(error){setJob('error',error.message);toast(error.message,'error');}
    finally{setImporting(false);}
  }
  async function refreshStatus() {
    try{
      const data=await request('/api/status');
      const available=!!data.engine?.available;
      $('engine-status').innerHTML=`<span class="status-dot ${available?'':'neutral'}"></span><span>${escapeHTML(available?'音频转谱已就绪 · MIDI 可直接导入':data.engine?.message || '音频转谱尚未就绪，MIDI 可直接导入')}</span>`;
      $('engine-status').title=data.engine?.message || '';
      if(data.serial?.ports)fillPorts(data.serial.ports);
      if(data.serial?.available===false)$('serial-message').textContent=data.serial.message || '串口服务尚未就绪，可先使用软件预览。';
    }catch(error){
      $('engine-status').innerHTML='<span class="status-dot error"></span><span>本地服务未连接 · 当前可体验示例预览</span>';
      $('engine-status').title=error.message;
    }
  }
  async function rebuild() {
    if(!state.project)return;
    pause();$('rebuild-button').disabled=true;
    try{
      const original=state.project.key_adaptation?.original_project||state.project;
      const project=await post('/api/rebuild',{project:original,bpm:clamp(finite($('rebuild-bpm').value,90),20,300),tonic:Number($('rebuild-tonic').value),hand_size:$('hand-size').value});
      loadProject(project,true);
    }catch(error){toast(`自动重新生成失败：${error.message}`,'error');}
    finally{$('rebuild-button').disabled=false;}
  }
  function exportedProject() {
    return {...state.project,calibration:{...config},ui_settings:{playback_rate:state.rate,hand_filter:state.hand,mode:state.mode,mapped_only:state.mappedOnly,five_colors:state.fiveColors,lookahead_seconds:state.lookahead,loop:state.loop?{start:state.loopA,end:state.loopB}:null}};
  }
  function download(data,filename,mime='application/json;charset=utf-8') {
    const blob=data instanceof Blob?data:new Blob([typeof data==='string'?data:JSON.stringify(data,null,2)],{type:mime});
    const url=URL.createObjectURL(blob),anchor=document.createElement('a');anchor.href=url;anchor.download=filename;
    document.body.append(anchor);anchor.click();anchor.remove();setTimeout(()=>URL.revokeObjectURL(url),10000);$('export-menu').open=false;
  }
  function filename(suffix) { return `${String(state.project?.title || '钢琴练习').replace(/[<>:"/\\|?*\x00-\x1F]/g,'_').slice(0,90)}${suffix}`; }
  function exportEvents() {
    if(!state.project)return;
    const notes=state.project.notes.filter(selected),boundaries=new Map();
    const push=(time,type,note)=>{if(!boundaries.has(time))boundaries.set(time,[]);boundaries.get(time).push({type,note});};
    for(const note of notes){push(note.start-state.lookahead,'on',note);push(note.end,'off',note);}
    const active=new Map(),events=[];
    const points=[...boundaries.keys()].sort((a,b)=>a-b);
    let previous='';
    for(const time of points){
      const changes=boundaries.get(time);
      for(const change of changes)if(change.type==='off')active.delete(String(change.note.id));
      for(const change of changes)if(change.type==='on')active.set(String(change.note.id),change.note);
      const pixels=pixelsFor([...active.values()]),signature=JSON.stringify(pixels);
      if(signature===previous)continue;
      previous=signature;events.push({time:Number(((time+state.lookahead)/state.rate).toFixed(5)),source_time:Number(time.toFixed(5)),pixels});
    }
    const duration=(state.project.duration+state.lookahead)/state.rate;
    if(!events.length || events[events.length-1].pixels.length)events.push({time:Number(duration.toFixed(5)),source_time:state.project.duration,pixels:[]});
    const manual_groups=state.project.groups.map((group,index)=>({index:index+1,source_time:group.time,note_ids:group.note_ids,pixels:pixelsFor(notesInGroup(group).filter(selected)),wait_for_advance:true})).filter(group=>group.pixels.length || group.note_ids.some(id=>selected(state.noteById.get(String(id)))));
    download({format:'piano-light-events',version:1,title:state.project.title,mode:state.mode,playback_rate:state.rate,lookahead_seconds:state.lookahead,preroll_source_seconds:state.lookahead,lead_in_seconds:state.lookahead/state.rate,time_origin:'practice_start_including_preroll',hand_filter:state.hand,brightness:config.brightness,duration,calibration:config,events,manual_groups},filename('.lights.json'));
    toast('已导出灯光时间轴，包含当前速度、提前量、手别与琴键映射。','success');
  }
  async function exportMidi() {
    if(!state.project)return;
    $('export-midi').disabled=true;
    try{
      const response=await fetch('/api/export/midi',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(state.project)});
      if(!response.ok){let error;try{error=await response.json();}catch(_){}throw new Error(error?.error || error?.message || `导出失败 (${response.status})`);}
      download(await response.blob(),filename('.mid'),'audio/midi');toast('已导出 MIDI 乐曲。','success');
    }catch(error){toast(error.message,'error');}
    finally{$('export-midi').disabled=false;}
  }
  function readLoop() {
    const duration=state.project?.duration || 0;
    let start=clamp(finite($('loop-start').value),0,Math.max(0,duration-0.1));
    let end=clamp(finite($('loop-end').value,duration),start+0.1,duration);
    if(end<=start){start=0;end=duration;}
    state.loopA=start;state.loopB=end;$('loop-start').value=String(Number(start.toFixed(1)));$('loop-end').value=String(Number(end.toFixed(1)));
  }
  function fallbackDemo() {
    const bpm=90,beat=60/bpm,notes=[],groups=[];
    const melody=[60,62,64,65,67,67,69,67,65,64,62,60,64,62,60];
    const fingers=[1,2,3,4,5,5,5,4,3,2,1,1,3,2,1];
    let time=0,id=0;
    melody.forEach((pitch,index)=>{
      const length=index===melody.length-1?2:index===5||index===11?1.5:1;
      const note={id:id++,pitch,start:time,end:time+beat*length*0.88,velocity:85,hand:'R',finger:fingers[index],color:palette[`R${fingers[index]}`],jianpu:safeJianpu(pitch,0),beat_duration:length};
      notes.push(note);const group={time,note_ids:[note.id]};
      if(index%3===0){const bass={id:id++,pitch:index<6?48:index<12?43:48,start:time,end:time+beat*1.8,velocity:65,hand:'L',finger:5,color:palette.L5,jianpu:safeJianpu(index<6?48:index<12?43:48,0),beat_duration:2};notes.push(bass);group.note_ids.push(bass.id);}
      groups.push(group);time+=beat*length;
    });
    return {title:'练习示例 · C 大调入门',bpm,tonic:0,key_label:'1 = C',duration:time,notes,groups,warnings:[],palette,fingering:{engine:'内置示例指法'},transcription:{engine:'built-in demo'},notation:{meter_assumed:true}};
  }
  function bindEvents() {
    $('mapped-only').addEventListener('change',event=>setMappedOnly(event.target.checked));
    $('file-input').addEventListener('change',event=>importFile(event.target.files[0]));
    const zone=$('drop-zone');
    zone.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();if(!state.importing)$('file-input').click();}});
    ['dragenter','dragover'].forEach(name=>zone.addEventListener(name,event=>{event.preventDefault();if(!state.importing)zone.classList.add('dragging');}));
    ['dragleave','drop'].forEach(name=>zone.addEventListener(name,event=>{event.preventDefault();zone.classList.remove('dragging');}));
    zone.addEventListener('drop',event=>importFile(event.dataTransfer.files[0]));
    window.addEventListener('dragover',event=>event.preventDefault());window.addEventListener('drop',event=>event.preventDefault());
    $('demo-button').addEventListener('click',loadDemo);
    $('midi-search-form').addEventListener('submit',searchMidi);
    $('midi-ble-connect').addEventListener('click',()=>toggleBluetoothMidi(false));
    $('midi-ble-all').addEventListener('click',()=>toggleBluetoothMidi(true));
    $('midi-refresh').addEventListener('click',scanMidiDevices);
    $('midi-connect').addEventListener('click',toggleMidiConnection);
    $('midi-input').addEventListener('change',event=>{
      if(!state.midiInput)return;
      const input=state.midiAccess?.inputs.get(event.target.value);
      if(input)connectMidiInput(input);
    });
    $('play-button').addEventListener('click',play);$('prev-button').addEventListener('click',()=>step(-1));$('next-button').addEventListener('click',()=>step(1));
    $('timeline').addEventListener('input',event=>seek(Number(event.target.value)));
    $('speed-range').addEventListener('input',event=>{
      if(state.playing && state.mode==='timed'){state.time=currentTimedPosition();state.anchorTime=state.time;state.anchorNow=performance.now();}
      state.rate=Number(event.target.value)/100;$('speed-label').textContent=`${state.rate.toFixed(2)}×`;rangeFill(event.target);
    });
    $('speed-reset').addEventListener('click',()=>{$('speed-range').value='100';$('speed-range').dispatchEvent(new Event('input'));});
    $('mode-control').addEventListener('click',event=>{
      const button=event.target.closest('[data-mode]');if(!button)return;
      pause();state.mode=button.dataset.mode;state.groupIndex=indexAt(state.time);resetMidiJudgement();renderTransport();updateScoreCurrent();
    });
    $('hand-filter').addEventListener('click',event=>{
      const button=event.target.closest('[data-hand]');if(!button)return;
      state.hand=button.dataset.hand;resetMidiJudgement();renderScore();renderTransport();updateActive(true);
    });
    $('score-grid').addEventListener('click',event=>{const button=event.target.closest('[data-index]');if(button){const index=Number(button.dataset.index);seek(state.project.groups[index].time,index);}});
    $('score-page-prev').addEventListener('click',()=>{state.scorePage=Math.max(0,state.scorePage-1);renderScore();$('score-scroll').scrollLeft=0;});
    $('score-page-next').addEventListener('click',()=>{state.scorePage=Math.min(Math.floor((state.project.groups.length-1)/PAGE_SIZE),state.scorePage+1);renderScore();$('score-scroll').scrollLeft=0;});
    $('loop-button').addEventListener('click',()=>{state.loop=!state.loop;readLoop();renderTransport();});
    $('loop-start').addEventListener('change',readLoop);$('loop-end').addEventListener('change',readLoop);
    $('loop-set-start').addEventListener('click',()=>{$('loop-start').value=String(Math.max(0,state.time));readLoop();});
    $('loop-set-end').addEventListener('click',()=>{$('loop-end').value=String(Math.max(0,state.time));readLoop();});
    $('settings-shortcut').addEventListener('click',()=>{$('settings-panel').open=true;$('settings-panel').scrollIntoView({behavior:'smooth',block:'start'});refreshPorts(false);});
    $('settings-panel').addEventListener('toggle',()=>{if($('settings-panel').open)refreshPorts(false);});
    $('refresh-ports').addEventListener('click',()=>refreshPorts());$('connect-button').addEventListener('click',toggleConnection);
    $('brightness-range').addEventListener('input',event=>{config.brightness=Number(event.target.value)/100;rangeFill(event.target);updateMappingLabels();persistConfig();});
    $('lookahead-range').addEventListener('input',event=>{state.lookahead=Number(event.target.value)/100;config.lookahead=state.lookahead;$('lookahead-value').textContent=`${state.lookahead.toFixed(2)} 秒`;rangeFill(event.target);renderTransport();updateActive(true);persistConfig();});
    $('generate-map').addEventListener('click',generateMapping);$('calibration-pitch').addEventListener('change',showKeyMapping);
    $('save-key').addEventListener('click',saveKey);$('test-key').addEventListener('click',()=>testKey());
    $('save-calibration').addEventListener('click',()=>{config.confirmed=$('mapping-confirmed').checked;persistConfig();updateMappingLabels();toast(config.confirmed?'安装校准已保存，下次打开自动使用。':'当前映射已保存，仍标记为待安装校准。','success');});
    $('keyboard').addEventListener('click',event=>{const key=event.target.closest('[data-pitch]');if(!key)return;const pitch=Number(key.dataset.pitch);$('calibration-pitch').value=String(pitch);showKeyMapping();testKey(pitch,config.mapping[pitch] || []);});
    $('rebuild-tonic').innerHTML=$('import-tonic').innerHTML;$('rebuild-button').addEventListener('click',rebuild);
    $('export-project').addEventListener('click',()=>{if(state.project)download(exportedProject(),filename('.piano.json'));});
    $('export-events').addEventListener('click',exportEvents);$('export-midi').addEventListener('click',exportMidi);
    document.addEventListener('click',event=>{if(!event.target.closest('#export-menu'))$('export-menu').open=false;});
    document.addEventListener('keydown',event=>{
      if(event.target.closest('input,select,textarea,[contenteditable="true"]') || event.ctrlKey || event.metaKey || event.altKey)return;
      if(event.code==='Space'){if(event.target.closest('button,summary'))return;event.preventDefault();play();}else if(event.key==='ArrowRight'){event.preventDefault();step(1);}else if(event.key==='ArrowLeft'){event.preventDefault();step(-1);}else if(event.key==='Home'){event.preventDefault();seek(0,0);}
    });
    document.addEventListener('visibilitychange',()=>{if(document.hidden)pause();});
    window.addEventListener('pagehide',()=>{
      if(!state.serialConnected)return;
      const body=new Blob([JSON.stringify({pixels:[],brightness:config.brightness})],{type:'application/json'});
      navigator.sendBeacon('/api/serial/frame',body);
    });
    window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(renderKeyboard,150);});
  }
  async function initialize() {
    bindEvents();installFiveColors();populateCalibration();loadProject(fallbackDemo());renderKeyboard();
    document.querySelectorAll('input[type=range]').forEach(rangeFill);
    requestAnimationFrame(animate);setInterval(syncSerial,80);
    const revision=state.loadRevision;
    const results=await Promise.allSettled([refreshStatus(),request('/api/demo')]);
    if(results[1].status==='fulfilled' && state.loadRevision===revision && !state.importing) {
      try{loadProject(results[1].value);}catch(error){toast(`示例载入失败：${error.message}`,'error');}
    }
  }
  window.PianoLightMidiEvents=true;
  window.PianoCorrectAdvanceNative=true;
  window.PianoSimultaneousNative=true;
  window.PianoMappedOnlyNative=true;
  window.PianoProjectApi={current:()=>state.project,load:project=>loadProject(project)};
  window.PianoFingerColors={set:setFiveColors,colorFor,get enabled(){return state.fiveColors;},palette:fiveFingerColors.slice()};
  window.addEventListener('piano-calibration-saved',()=>{
    config=readConfig();populateCalibration();renderKeyboard();renderScore();updateActive(true);
  });
  initialize();
})();

/* 已转换曲谱的本机曲库；浏览器保存曲谱，后台补入历史转换结果。 */
(() => {
  'use strict';
  if(window.PianoLibrary)return;
  const $=id=>document.getElementById(id);
  const section=document.createElement('section');section.className='sidebar-section piano-library';
  section.setAttribute('aria-label','已转换曲谱曲库');
  section.innerHTML='<div class="library-heading"><h2>我的曲库</h2><button type="button" class="text-button" id="library-refresh">刷新</button></div><p class="setting-help" id="library-status" role="status">正在读取已转换的曲谱…</p><div id="library-list"></div>';
  document.querySelector('.sidebar-section').after(section);
  const style=document.createElement('style');
  style.textContent='.library-heading{display:flex;align-items:center;justify-content:space-between;gap:10px}.library-heading h2{font-size:18px;margin:0}.piano-library .setting-help{margin:8px 0 12px}.library-song{display:block;width:100%;text-align:left;background:var(--panel-deep);border:1px solid var(--border);border-radius:9px;padding:11px 12px;margin:8px 0;color:var(--text)}.library-song:hover{border-color:var(--accent)}.library-song[aria-current="true"]{border-color:var(--accent);background:var(--accent-soft)}.library-song strong{display:block;overflow-wrap:anywhere;font-size:14px}.library-song small{display:block;color:var(--muted);margin-top:5px;font-size:12px}';
  document.head.append(style);
  const database=new Promise((resolve,reject)=>{
    const opening=indexedDB.open('piano-light-library-v1',1);
    opening.onupgradeneeded=()=>opening.result.createObjectStore('scores',{keyPath:'id'});
    opening.onsuccess=()=>resolve(opening.result);
    opening.onerror=()=>reject(new Error('浏览器未能保存曲库，请检查本机存储空间。'));
  });
  async function storage(method,value){
    const db=await database;
    return new Promise((resolve,reject)=>{
      const tx=db.transaction('scores',method==='put'?'readwrite':'readonly');
      const query=tx.objectStore('scores')[method](value);
      tx.oncomplete=()=>resolve(query.result);
      tx.onerror=()=>reject(tx.error||new Error('曲库读写失败。'));
      tx.onabort=()=>reject(tx.error||new Error('曲库保存未完成。'));
    });
  }
  function projectKey(project){
    project=project.key_adaptation?.original_project||project;
    return JSON.stringify([project.source?.kind||'score',project.source?.filename||project.source?.query||project.title]);
  }
  async function save(project,onlyIfAbsent=false){
    project=project?.key_adaptation?.original_project||project;
    if(!project?.notes?.length||!project.groups?.length||project.source?.kind==='demo'||/demo|示例|built-in/i.test(project.transcription?.engine||''))return;
    const id=projectKey(project);
    if(onlyIfAbsent&&await storage('get',id))return;
    // 琴谱独立于本机灯珠校准和当前练习进度。
    const {calibration,ui_settings,...score}=project;
    await storage('put',{id,project:score,savedAt:Date.now()});
  }
  async function render(){
    const entries=(await storage('getAll')).sort((a,b)=>b.savedAt-a.savedAt);
    const current=await window.PianoProjectApi?.current();
    $('library-list').replaceChildren();
    for(const {id,project} of entries){
      const button=document.createElement('button');button.type='button';button.className='library-song';
      button.dataset.libraryId=id;button.setAttribute('aria-current',String(!!current&&projectKey(current)===id));
      const title=document.createElement('strong');title.textContent=project.title||'未命名练习';
      const detail=document.createElement('small'),seconds=Math.max(0,Math.round(project.duration||0));
      detail.textContent=`${project.notes.length} 音符 · ${Math.round(project.bpm||90)} 拍/分钟 · ${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;
      button.append(title,detail);button.onclick=()=>open(id).catch(showError);$('library-list').append(button);
    }
    $('library-status').textContent=entries.length?`${entries.length} 首已转换曲谱，点击即可练习。以后转换完成会自动加入。`:'还没有已转换曲谱。导入音乐并完成转谱后会自动加入。';
    return entries;
  }
  async function open(id){
    const entry=await storage('get',id);
    if(!entry)throw new Error('没有找到这首曲谱，请刷新曲库。');
    if(!window.PianoProjectApi?.load)throw new Error('曲谱载入入口尚未就绪。');
    await window.PianoProjectApi.load(entry.project);
    await render();
    $('library-status').textContent=`已载入「${entry.project.title}」，可以开始练习。`;
  }
  function showError(error){$('library-status').textContent=error.message||'读取曲库失败。';}
  async function refresh(){
    $('library-refresh').disabled=true;
    try{
      let jobs=[];
      const response=await fetch('/api/library');
      if(response.ok)jobs=(await response.json()).items||[];
      // 已连接的旧网页沿用既有任务接口，避免重连钢琴。
      else if(response.status===404)jobs=(window.PianoLibraryLegacyJobs||[]).map(id=>({id,legacy:true}));
      else throw new Error('读取历史曲谱失败，请稍后刷新。');
      for(const job of jobs){
        const result=await fetch(job.legacy?`/api/jobs/${job.id}`:`/api/library/${job.id}`);
        if(!result.ok)continue;
        const data=await result.json();
        await save(job.legacy?data.project:data,true);
      }
      await save(await window.PianoProjectApi?.current(),true);
      return await render();
    }finally{$('library-refresh').disabled=false;}
  }
  window.addEventListener('piano-project-loaded',event=>{
    save(event.detail).then(render).catch(showError);
  });
  $('library-refresh').onclick=()=>refresh().catch(showError);
  window.PianoLibrary={open,refresh,list:()=>storage('getAll')};
  window.PianoLibrary.ready=refresh().catch(error=>{showError(error);throw error;});
})();

/* 邻键替代：原谱独立保留，适配后的同一份音符用于显示、指法、灯光及按键判定。 */
(() => {
  'use strict';
  if(window.PianoKeyAdaptation)return;
  const $=id=>document.getElementById(id),storageKey='piano-light-key-adaptation-v1';
  function transform(raw,config){
    const original=raw.key_adaptation?.original_project||raw;
    const available=Object.keys(config.mapping||{}).map(Number).filter(p=>Number.isInteger(p)&&p>=21&&p<=108&&
      (config.mapping[p]||[]).some(i=>Number.isInteger(i)&&i>=0&&i<config.ledCount)).sort((a,b)=>a-b);
    if(!available.length)throw new Error('还没有已对应琴键，请先完成灯珠与琴键校准。');
    const allowed=new Set(available),minimum=available[0],maximum=available.at(-1);
    const stats={black:0,white:0,blackKeys:0,whiteKeys:0,merged:0,octaveShifted:0};
    const blackKeys=new Set(),whiteKeys=new Set(),notes=[],previous={L:null,R:null};
    const byId=new Map(original.notes.map(n=>[String(n.id),n])),seen=new Set();
    const groups=(original.groups||[]).map(g=>({time:g.time,notes:g.note_ids.map(id=>byId.get(String(id))).filter(Boolean)}));
    for(const group of groups)for(const n of group.notes)seen.add(String(n.id));
    for(const n of original.notes)if(!seen.has(String(n.id))){
      const group=groups.find(g=>Math.abs(g.time-n.start)<=0.025);
      if(group)group.notes.push(n);else groups.push({time:n.start,notes:[n]});
    }
    function fold(pitch){
      if(pitch>=minimum&&pitch<=maximum)return pitch;
      const candidates=[];
      for(let shift=-9;shift<=9;shift++)if(pitch+shift*12>=minimum&&pitch+shift*12<=maximum)candidates.push(pitch+shift*12);
      return candidates.sort((a,b)=>Math.abs(a-pitch)-Math.abs(b-pitch)||a-b)[0]??pitch;
    }
    for(const group of groups.sort((a,b)=>a.time-b.time)){
      const occupied=new Set(group.notes.filter(n=>allowed.has(n.pitch)).map(n=>n.pitch)),merged=new Map();
      const ordered=[...group.notes].sort((a,b)=>Number(allowed.has(b.pitch))-Number(allowed.has(a.pitch))||a.pitch-b.pitch);
      for(const n of ordered){
        const side=n.hand==='L'?'L':'R',folded=fold(n.pitch);
        let pitch=n.pitch;
        if(!allowed.has(pitch)){
          const distance=Math.min(...available.map(p=>Math.abs(p-folded)));
          const candidates=available.filter(p=>Math.abs(p-folded)===distance),last=previous[side];
          const cost=p=>{
            let value=occupied.has(p)?3:0;
            if(last){
              const direction=Math.sign(n.pitch-last.original),movement=Math.sign(p-last.pitch);
              if(direction&&movement!==direction)value+=4;
              value+=Math.abs((p-last.pitch)-(folded-last.folded))*0.05;
            }
            return value;
          };
          pitch=candidates.sort((a,b)=>cost(a)-cost(b)||a-b)[0];
          if([1,3,6,8,10].includes(n.pitch%12)){stats.black++;blackKeys.add(n.pitch);}
          else{stats.white++;whiteKeys.add(n.pitch);}
          if(folded!==n.pitch)stats.octaveShifted++;
        }
        occupied.add(pitch);
        const existing=merged.get(pitch);
        if(existing){
          const extended=Math.max(existing.end,n.end);
          if(existing.source_beat_duration)existing.source_beat_duration*=(extended-existing.start)/(existing.end-existing.start);
          existing.end=extended;existing.velocity=Math.max(existing.velocity||80,n.velocity||80);
          existing.adapted_from.push({id:n.id,pitch:n.pitch,hand:side});stats.merged++;
        }else{
          const {jianpu,finger,color,leds,onset_group,...clean}=n;
          merged.set(pitch,{...clean,pitch,source_hand:side,original_pitch:n.pitch,
            adapted_from:[{id:n.id,pitch:n.pitch,hand:side}]});
        }
      }
      notes.push(...merged.values());
      for(const side of ['L','R']){
        const lane=group.notes.filter(n=>(n.hand==='L'?'L':'R')===side).sort((a,b)=>a.pitch-b.pitch);
        const anchor=side==='R'?lane.at(-1):lane[0];
        if(anchor){
          const target=[...merged.values()].find(n=>n.adapted_from.some(from=>String(from.id)===String(anchor.id)));
          previous[side]={original:anchor.pitch,pitch:target.pitch,folded:fold(anchor.pitch)};
        }
      }
    }
    stats.blackKeys=blackKeys.size;stats.whiteKeys=whiteKeys.size;
    return {original,available,notes:notes.sort((a,b)=>a.start-b.start||a.pitch-b.pitch),stats};
  }
  let mode='original',original=null,revision=0,busy=false,lastStats=null,cached=null;
  function config(){return JSON.parse(localStorage.getItem('piano-light-studio-calibration-v1')||'{}');}
  function summary(){
    const output=$('key-adaptation-summary');if(!output)return;
    if(busy){output.textContent='正在替换未对应音符并重新计算双手指法…';return;}
    if(mode==='nearest'&&lastStats){
      const s=lastStats;
      output.textContent=`全曲替代黑键音符 ${s.black} 次、白键音符 ${s.white} 次（涉及黑键 ${s.blackKeys} 个、白键 ${s.whiteKeys} 个），合并 ${s.merged} 个同音${s.octaveShifted?`，调整 ${s.octaveShifted} 个超范围音`:''}${s.extraOmitted?`，另简化 ${s.extraOmitted} 个音符`:''}。原谱保留；适配会改变原曲音高。`;
    }else output.textContent=mode==='omit'?$('mapped-only-summary').textContent:'显示完整原谱，保留所有音符。';
  }
  function filter(enabled){
    const input=$('mapped-only');
    if(input.checked!==enabled){input.checked=enabled;input.dispatchEvent(new Event('change',{bubbles:true}));}
  }
  async function setMode(next,source=null,preserve=true){
    if(!['original','omit','nearest'].includes(next))throw new Error('请选择有效的琴键适配方式。');
    const ticket=++revision,oldMode=mode;
    const current=source||await window.PianoProjectApi.current();
    if(!current)return;
    const base=current.key_adaptation?.original_project||current;
    original=base;mode=next;lastStats=null;
    const index=Number(document.querySelector('#score-grid .score-group.current')?.dataset.index||0);
    const time=preserve?(current.groups[index]?.time||0):0;
    const running=$('play-button').classList.contains('is-playing');
    if(running)$('play-button').click();
    $('key-adaptation-mode').value=mode;$('key-adaptation-mode').disabled=true;busy=true;summary();
    try{
      if(next==='nearest'){
        const prepared=transform(base,config());
        const key=JSON.stringify([base,prepared.available,$('hand-size').value]);
        let result=cached?.key===key?cached.project:null;
        if(!result){
          const response=await fetch('/api/rebuild',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
            project:{...base,notes:prepared.notes,source_notes:prepared.notes},bpm:base.bpm,tonic:base.tonic,
            hand_size:$('hand-size').value||base.hand_size||'M'})});
          result=await response.json();
          if(!response.ok)throw new Error(result.error||'重新计算指法失败。');
          if(!result.notes?.length||result.notes.some(n=>!prepared.available.includes(n.pitch)))throw new Error('适配结果含有未对应琴键，请重新校准后再试。');
          prepared.stats.extraOmitted=result.fingering?.omitted_note_count||0;
          result={...result,title:`${base.title} · 邻键适配版`,duration:base.duration,
            key_adaptation:{mode:'nearest',original_project:base,stats:prepared.stats,available:prepared.available}};
          cached={key,project:result};
        }
        if(ticket!==revision)return;
        filter(false);await window.PianoProjectApi.load(result);lastStats=result.key_adaptation.stats;
      }else{
        filter(next==='omit');
        if(current.key_adaptation)await window.PianoProjectApi.load(base);
      }
      if(ticket!==revision)return;
      const timeline=$('timeline');timeline.value=String(time);timeline.dispatchEvent(new Event('input',{bubbles:true}));
      if(running&&!$('play-button').classList.contains('is-playing'))$('play-button').click();
      $('score-grid').dispatchEvent(new MouseEvent('click',{bubbles:true}));
      localStorage.setItem(storageKey,mode);
    }catch(error){
      if(ticket===revision){mode=oldMode;$('key-adaptation-mode').value=mode;filter(mode==='omit');}
      throw error;
    }finally{
      if(ticket===revision){busy=false;$('key-adaptation-mode').disabled=false;summary();}
    }
  }
  function showError(error){$('key-adaptation-summary').textContent=error.message;}
  function install(){
    const input=$('mapped-only'),container=input.closest('div');
    input.closest('label').hidden=true;$('mapped-only-summary').hidden=true;
    const wrap=document.createElement('div');
    wrap.innerHTML='<label>琴键适配<select id="key-adaptation-mode" aria-label="琴键适配方式"><option value="original">完整原谱</option><option value="omit">省略未对应音</option><option value="nearest">邻键替代</option></select></label><p class="setting-help" id="key-adaptation-summary" role="status" aria-live="polite" style="margin:8px 0 0"></p>';
    container.append(wrap);
    mode=localStorage.getItem(storageKey)||(input.checked?'omit':'original');
    if(!['original','omit','nearest'].includes(mode))mode='original';
    $('key-adaptation-mode').value=mode;
    $('key-adaptation-mode').onchange=event=>setMode(event.target.value).catch(showError);
    document.addEventListener('click',event=>{
      if(busy&&event.isTrusted&&event.target.closest('#play-button,#prev-button,#next-button,#score-grid .score-group')){event.preventDefault();event.stopImmediatePropagation();}
    },true);
    document.addEventListener('keydown',event=>{
      if(busy&&event.isTrusted&&['Space','ArrowRight','ArrowLeft','Home'].includes(event.code)){event.preventDefault();event.stopImmediatePropagation();}
    },true);
    new MutationObserver(summary).observe($('mapped-only-summary'),{childList:true,subtree:true});
    window.addEventListener('piano-project-loaded',event=>{
      if(event.detail.key_adaptation)return;
      original=event.detail;
      if(mode==='nearest')setMode(mode,event.detail,false).catch(showError);else summary();
    });
    window.addEventListener('piano-calibration-saved',()=>{cached=null;if(mode==='nearest')setMode(mode,original).catch(showError);});
    if(window.PianoMappedOnlyLive){
      // 旧网页的曲库保存原谱；后台重新编配也从原谱开始。
      window.addEventListener('piano-project-loaded',event=>{
        if(event.detail.key_adaptation){event.stopImmediatePropagation();$('score-grid').dispatchEvent(new MouseEvent('click',{bubbles:true}));}
      },true);
      const fetchOriginal=window.fetch;
      window.fetch=function(url,options){
        if(String(url)==='/api/rebuild'&&options?.body){
          const request=JSON.parse(options.body);
          if(request.project?.key_adaptation){request.project=request.project.key_adaptation.original_project;options={...options,body:JSON.stringify(request)};}
        }
        return fetchOriginal.call(this,url,options);
      };
    }
    if(mode!=='nearest')filter(mode==='omit');
    window.PianoKeyAdaptation.ready=mode==='nearest'?setMode(mode).catch(showError):Promise.resolve(summary());
  }
  window.PianoKeyAdaptation={transform,setMode,get mode(){return mode;},get busy(){return busy;}};
  install();
})();
