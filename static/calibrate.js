/* 逐颗灯珠校准；沿用实体钢琴输入，每次按下只记录当前一颗。 */
(() => {
  'use strict';
  if(window.PianoLightCalibration)return;
  const key='piano-light-studio-calibration-v1';
  const $=id=>document.getElementById(id);
  const api=async(path,body)=>{
    if(path==='/api/calibration'&&window.PianoLightCalibrationStorageOnly){
      if(body===undefined)return JSON.parse(localStorage.getItem('piano-light-led-records-v1') || '{"records":{}}');
      const saved={...body,updated_at:Date.now()/1000};localStorage.setItem('piano-light-led-records-v1',JSON.stringify(saved));return saved;
    }
    const response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const data=await response.json();if(!response.ok)throw new Error(data.error || `请求失败 ${response.status}`);return data;
  };
  const panel=document.createElement('section');
  panel.className='midi-checker';panel.id='led-calibration';
  panel.innerHTML='<h4>逐颗灯珠自动校准</h4><p class="setting-help">亮一颗灯，按一次对应琴键。收到后自动保存并亮下一颗；同一琴键可以对应多颗灯。这里的灯号从1开始。</p><div class="midi-controls"><label>起始灯号 <input id="led-cal-first" type="number" min="1" max="512" value="14" style="width:75px"></label><label>结束灯号 <input id="led-cal-last" type="number" min="1" max="512" value="144" style="width:75px"></label><button class="button primary" id="led-cal-start">开始逐颗校准</button><button class="button secondary" id="led-cal-stop" disabled>暂停并保存</button></div><p class="midi-feedback" id="led-cal-message" aria-live="assertive">正在接入当前钢琴按键…</p>';
  $('auto-calibration-slot').append(panel);
  const undo=document.createElement('button');undo.className='button secondary';undo.textContent='撤销上一颗';undo.disabled=true;
  $('led-cal-stop').after(undo);
  let config,records={},current=13,last=143,active=false,busy=false,ready=false,starting=false;
  let lastRecorded=null;
  let frameBusy=false,heartbeat=null,relay=Promise.resolve(),saveQueue=Promise.resolve();
  const held=new Set(),disabled=new Map();
  const readConfig=()=>JSON.parse(localStorage.getItem(key) || '{}');
  const message=text=>{$('led-cal-message').textContent=text;};
  function say(text){
    if(!window.speechSynthesis)return;
    speechSynthesis.cancel();const utterance=new SpeechSynthesisUtterance(text);utterance.lang='zh-CN';utterance.rate=1.2;speechSynthesis.speak(utterance);
  }
  function controls(running){
    $('led-cal-start').disabled=running;$('led-cal-stop').disabled=!running;
    for(const id of ['play-button','prev-button','next-button','connect-button','refresh-ports','generate-map','save-key','test-key','led-cal-first','led-cal-last']){
      const element=$(id);if(!element)continue;
      if(running){disabled.set(id,element.disabled);element.disabled=true;}
      else if(disabled.has(id)){element.disabled=disabled.get(id);disabled.delete(id);}
    }
  }
  function snapshot(state){return {state,current_led:current+1,first_led:Number($('led-cal-first').value),last_led:last+1,records:{...records},config:JSON.parse(JSON.stringify(config || {})),message:$('led-cal-message').textContent};}
  function save(state){
    const data=snapshot(state);
    saveQueue=saveQueue.catch(()=>{}).then(()=>api('/api/calibration',data));return saveQueue;
  }
  async function frame(pixels){
    while(frameBusy)await new Promise(resolve=>setTimeout(resolve,10));
    frameBusy=true;
    try{return await api('/api/serial/frame',{brightness:Number(config.brightness)||.15,pixels});}
    finally{frameBusy=false;}
  }
  async function light(){
    await frame([[current,255,0,0]]);
    message(`第${current+1}颗灯已亮，等待按键。已保存 ${Object.keys(records).length} 颗。`);
    ready=held.size===0;
  }
  async function stop(reason='已暂停并保存。'){
    active=false;ready=false;clearInterval(heartbeat);heartbeat=null;
    try{await frame([]);await api('/api/serial/disconnect',{});}catch(_){}
    message(reason);controls(false);await save('paused').catch(e=>message(`保存失败：${e.message}`));
  }
  async function fail(error){await stop(`校准暂停：${error.message}。已记录的对应关系保留。`);}
  async function finish(){
    active=false;ready=false;clearInterval(heartbeat);heartbeat=null;
    const mapping={};
    for(let pitch=config.firstPitch;pitch<config.firstPitch+config.keyCount;pitch++)mapping[pitch]=[];
    for(const [led,pitch] of Object.entries(records))(mapping[pitch] ||= []).push(Number(led));
    config.mapping=mapping;config.confirmed=true;localStorage.setItem(key,JSON.stringify(config));
    window.dispatchEvent(new Event('piano-calibration-saved'));
    await frame([]);await api('/api/serial/disconnect',{});
    message(`校准完成，已保存 ${Object.keys(records).length} 颗灯的实际对应关系。`);
    say('校准完成');controls(false);await save('complete');
  }
  async function receive(data){
    const [status,pitch,velocity]=data;
    const family=status&0xf0,token=`${status&15}:${pitch}`;
    if(family===0x80 || (family===0x90 && velocity===0)){
      held.delete(token);if(active&&!busy&&held.size===0)ready=true;return;
    }
    if(family!==0x90 || !(velocity>0) || !Number.isInteger(pitch) || held.has(token))return;
    held.add(token);
    relay=relay.catch(()=>{}).then(()=>api('/api/midi/event',{status,pitch,velocity}));
    relay.catch(error=>{if(active)fail(error);else message(`按键回传失败：${error.message}`);});
    if(!active||!ready||busy)return;
    ready=false;busy=true;undo.disabled=true;const index=current;
    message(`收到：第${index+1}颗灯 → 音符编号 ${pitch}。正在保存。`);say('收到');
    try{
      records[index]=pitch;config.mapping ||= {};
      for(const [note,indices] of Object.entries(config.mapping))config.mapping[note]=indices.filter(n=>n!==index);
      config.mapping[pitch]=[...new Set([...(config.mapping[pitch]||[]),index])];config.confirmed=false;
      localStorage.setItem(key,JSON.stringify(config));
      window.dispatchEvent(new Event('piano-calibration-saved'));
      await save('received');await relay;lastRecorded=index;
      if(!active)return;
      if(index>=last){
        await finish();return;
      }
      current++;await light();await save('waiting');
    }catch(error){await fail(error);}finally{busy=false;undo.disabled=lastRecorded===null;if(active&&held.size===0)ready=true;}
  }
  async function start(options={}){
    if(active||starting)return;starting=true;
    try{
      config=readConfig();const first=Number(options.first ?? $('led-cal-first').value);
      const end=Number(options.last ?? $('led-cal-last').value);
      if(!Number.isInteger(first)||!Number.isInteger(end)||first<1||end<first||end>Number(config.ledCount || 144))throw new Error('请检查起始和结束灯号');
      if(!$('midi-connection-status').textContent.includes('已连接'))throw new Error('当前网页的钢琴尚未连接');
      if($('play-button')?.classList.contains('is-playing'))$('play-button').click();
      if($('connect-button')?.textContent.includes('断开灯带')){
        $('connect-button').click();
        for(let i=0;i<100&&$('connect-button').disabled;i++)await new Promise(resolve=>setTimeout(resolve,50));
        if($('connect-button').disabled)throw new Error('灯带未能交接控制');
      }
      const ports=(await api('/api/ports')).ports;
      const port=options.port || $('serial-port')?.value || (ports.length===1?ports[0].device:null);
      if(!port)throw new Error('请选择灯带串口');
      const saved=await api('/api/calibration');records={...(saved.records || {})};
      current=first-1;last=end-1;lastRecorded=null;undo.disabled=true;$('led-cal-first').value=first;$('led-cal-last').value=end;
      await api('/api/serial/connect',{port,baud:115200});
      active=true;controls(true);await light();await save('waiting');
      heartbeat=setInterval(()=>{if(active&&!busy&&!frameBusy)frame([[current,255,0,0]]).catch(fail);},350);
      say(`第${current+1}颗，等待按键`);
    }catch(error){if(active)await fail(error);else message(`尚未开始：${error.message}`);throw error;}
    finally{starting=false;}
  }
  window.PianoLightCalibration={get active(){return active;},start,stop,status:()=>snapshot(active?'waiting':'paused')};
  undo.onclick=async()=>{
    if(lastRecorded===null||busy)return;
    const index=lastRecorded,port=$('serial-port')?.value;
    try{
      await stop('已撤销上一颗，准备重新对应。');
      delete records[index];
      for(const [pitch,leds] of Object.entries(config.mapping))config.mapping[pitch]=leds.filter(n=>n!==index);
      config.confirmed=false;current=index;lastRecorded=null;undo.disabled=true;
      localStorage.setItem(key,JSON.stringify(config));window.dispatchEvent(new Event('piano-calibration-saved'));
      await save('paused');await start({first:index+1,last:last+1,port});
    }catch(error){await fail(error);}
  };
  window.addEventListener('piano-midi-message',event=>{receive(event.detail).catch(fail);});
  $('led-cal-start').onclick=()=>start().catch(()=>{});$('led-cal-stop').onclick=()=>stop().catch(()=>{});
  window.addEventListener('pagehide',()=>{
    if(active)navigator.sendBeacon('/api/serial/frame',new Blob([JSON.stringify({pixels:[],brightness:.15})],{type:'application/json'}));
  });
  async function initialize(){
    const stored=readConfig();$('led-cal-last').value=stored.ledCount || 144;
    if(!window.PianoLightMidiEvents){
      if(!window.BleMidi?.createDecoder){
        await new Promise((resolve,reject)=>{
          const script=document.createElement('script');script.src='/ble_midi.js?calibration=1';script.onload=resolve;script.onerror=()=>reject(new Error('读取按键解析器失败'));document.head.append(script);
        });
      }
      // 旧页面的蓝牙回调已持有连接。只旁读它正在读取的数据，不重连设备。
      const proto=window.BluetoothRemoteGATTCharacteristic?.prototype;
      const descriptor=proto&&Object.getOwnPropertyDescriptor(proto,'value');
      if(!descriptor?.get||!descriptor.configurable)throw new Error('当前页面无法旁读，请刷新一次后连接钢琴');
      const decode=window.BleMidi.createDecoder(data=>{receive(Array.from(data)).catch(fail);});
      Object.defineProperty(proto,'value',{...descriptor,get(){
        const value=descriptor.get.call(this);
        if(this.uuid==='7772e5db-3868-4112-a1a9-f2669d106bf3'&&value){
          try{decode(new Uint8Array(value.buffer,value.byteOffset,value.byteLength));}catch(error){message(`读取按键失败：${error.message}`);}
        }
        return value;
      }});
    }
    message('按键读取已接通。点击开始后，按当前亮灯对应的实体琴键。每颗的对应关系立即保存在当前浏览器。');
  }
  window.PianoLightCalibration.ready=initialize().catch(error=>{message(`接入失败：${error.message}`);throw error;});
})();
