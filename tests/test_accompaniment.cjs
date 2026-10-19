const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(require('node:path').join(__dirname,'../static/app.js'),'utf8');
let now=0,nextTimer=0;const timers=new Map(),scheduled=[];
class Context {
  constructor(){this.currentTime=0;this.destination={};this.state='running';}
  resume(){return Promise.resolve();}
  createGain(){return {gain:{value:1,setValueAtTime(){},linearRampToValueAtTime(){},exponentialRampToValueAtTime(){}},connect(){},disconnect(){}};}
  createOscillator(){const voice={frequency:{value:0},connect(){},disconnect(){},start(time){scheduled.push({time,voice});},stop(){voice.stopped=true;}};return voice;}
}
const window={AudioContext:Context,addEventListener(){},dispatchEvent(){},PianoLibrary:{},PianoKeyAdaptation:{},PianoPhrasePractice:{}};
vm.runInNewContext(source.replace('  initialize();',`
  renderTransport=()=>{};updateScoreCurrent=()=>{};updateActive=()=>{};updateClock=()=>{};syncSerial=()=>{};renderMidiJudgement=()=>{};toast=()=>{};
  window.test={PracticeAccompaniment,state,play,pause,seek,handleMidiMessage,startAccompaniment,setAudio:value=>accompaniment=value};`),{
  window,document:{hidden:false},localStorage:{getItem(){return null;},setItem(){}},URL,
  location:{href:'http://127.0.0.1:18766/',origin:'http://127.0.0.1:18766'},performance:{now:()=>now},
  setTimeout(callback,delay){const id=++nextTimer;timers.set(id,{callback,at:now+delay});return id;},clearTimeout:id=>timers.delete(id),
  CustomEvent:class{constructor(type,options){this.detail=options.detail;}}
});
function media(){return {currentTime:0,paused:true,ended:false,playbackRate:1,addEventListener(){},removeAttribute(){},load(){},
  pause(){this.paused=true;},play(){this.paused=false;return Promise.resolve();}};}
const api=window.test,{state}=api;
const notes=[{id:'0',pitch:60,start:0,end:.8,velocity:80,hand:'R'},{id:'1',pitch:64,start:1,end:1.8,velocity:80,hand:'R'},
  {id:'2',pitch:67,start:2,end:2.8,velocity:80,hand:'R'}];
const score={notes,source_notes:notes,groups:notes.map(n=>({time:n.start,note_ids:[n.id]})),duration:3,source:{kind:'midi'}};
state.project=score;state.noteById=new Map(notes.map(n=>[n.id,n]));state.lookahead=0;state.mode='correct';state.midiBleConnection={};
const synth=new api.PracticeAccompaniment(media(),()=>{});synth.load(score);synth.enabled=true;api.setAudio(synth);
function advance(ms){const until=now+ms;for(;;){const t=[...timers].sort((a,b)=>a[1].at-b[1].at)[0];if(!t||t[1].at>until)break;now=t[1].at;timers.delete(t[0]);t[1].callback();}now=until;}
api.play();assert.equal(scheduled.length,0,'倒计时不能提前发声');advance(3000);
assert.equal(scheduled.length,1);assert.equal(synth.end,1,'弹对推进只播放当前组片段');
synth.context.currentTime=1.1;synth.tick();assert.equal(synth.live,false,'等待按键时伴奏段尾必须停');
api.handleMidiMessage({data:[0x90,61,90]});assert.equal(state.groupIndex,0);assert.equal(synth.live,false,'错音不能启动下一段');
api.handleMidiMessage({data:[0x90,60,90]});assert.equal(state.groupIndex,1);assert.equal(synth.startTime,1);assert.equal(synth.end,2);assert.equal(synth.live,true);
api.pause();assert.equal(synth.live,false);assert.ok(scheduled.every(x=>x.voice.stopped),'暂停清除已排定音符');
api.seek(2);assert.equal(synth.live,false);assert.equal(state.time,2);
const audio=media(),original=new api.PracticeAccompaniment(audio,()=>{});
original.load({...score,source:{converted_audio_url:'/api/jobs/'+ 'a'.repeat(32)+'/audio.mp3'}});original.enabled=true;
original.start(1,2,1,false);assert.equal(audio.paused,false);audio.currentTime=2.001;original.tick();assert.equal(audio.paused,true,'原录音也必须在组末暂停');
original.start(1,3,.5,true);assert.equal(audio.playbackRate,.5);audio.currentTime=1.4;assert.equal(original.position(),1.4,'定速使用原音频时钟同步');
original.start(-.4,3,1,true);original.stop();advance(500);assert.equal(audio.paused,true,'取消后不能由迟到的播放启动音乐');
const adapted={...score,notes:notes.map(n=>({...n,pitch:n.pitch+1})),key_adaptation:{original_project:score}};
synth.load(adapted);assert.equal(synth.notes[0].pitch,60,'邻键适配后伴奏仍使用完整原谱');
console.log('伴奏：倒计时静音、弹对后续播、错音与等待不续播、原录音组末暂停、变速同步、取消清音、跳转与适配原谱检查通过。');
