const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(require('node:path').join(__dirname,'../static/app.js'),'utf8');
let now=0,nextTimer=0;const timers=new Map(),messages=[];
const window={addEventListener(){},dispatchEvent(){},PianoLibrary:{},PianoKeyAdaptation:{},PianoPhrasePractice:{}};
vm.runInNewContext(source.replace('  initialize();',`
  renderTransport=()=>{};updateScoreCurrent=()=>{};updateActive=()=>{};updateClock=()=>{};syncSerial=()=>{};renderMidiJudgement=()=>{};
  toast=message=>messages.push(message);
  window.test={state,play,pause,seek,handleMidiMessage};`),{
  window,document:{hidden:false},localStorage:{getItem(){return null;}},performance:{now:()=>now},messages,
  setTimeout(callback,delay){const id=++nextTimer;timers.set(id,{callback,at:now+delay});return id;},
  clearTimeout:id=>timers.delete(id),CustomEvent:class{constructor(type,options){this.detail=options.detail;}}
});
const {state,play,pause,seek,handleMidiMessage}=window.test;
state.project={duration:5,notes:[{id:'a',pitch:60,hand:'R',start:0,end:1}],groups:[{time:0,note_ids:['a']}]};
state.noteById=new Map(state.project.notes.map(n=>[n.id,n]));
function advance(milliseconds){
  const until=now+milliseconds;
  for(;;){const item=[...timers].sort((a,b)=>a[1].at-b[1].at)[0];if(!item||item[1].at>until)break;
    now=item[1].at;timers.delete(item[0]);item[1].callback();}
  now=until;
}
play();assert.equal(state.countdown,3);assert.equal(state.playing,false);assert.equal(state.time,0);
advance(1000);assert.equal(state.countdown,2);assert.equal(state.playing,false);assert.equal(state.time,0);
advance(1000);assert.equal(state.countdown,1);advance(999);assert.equal(state.playing,false);
advance(1);assert.equal(state.countdown,0);assert.equal(state.playing,true);assert.equal(state.anchorNow,3000);
pause();state.time=0;play();play();advance(4000);assert.equal(state.playing,false,'再点一次必须取消，不能延迟偷偷开始');
play();seek(1);advance(4000);assert.equal(state.playing,false,'切换位置取消待开始的练习');assert.equal(state.time,1);
state.mode='correct';state.midiBleConnection=null;play();assert.equal(state.countdown,0,'未连接钢琴时不启动倒计时');
state.midiBleConnection={};state.groupIndex=0;state.time=0;play();
handleMidiMessage({data:[0x90,60,90]});assert.equal(state.groupIndex,0);assert.equal(state.playing,false,'倒计时按键不推进');
pause();advance(4000);assert.equal(state.playing,false);
state.mode='manual';play();advance(3000);assert.equal(state.playing,true,'手动模式也有准备时间');
console.log('开始倒计时：3/2/1、时间轴等待、重复点击取消、跳转取消、未连接提示和准备期间不推进检查通过。');
