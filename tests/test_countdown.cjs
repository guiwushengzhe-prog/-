const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(require('node:path').join(__dirname,'../static/app.js'),'utf8');
let now=0,nextTimer=0;const timers=new Map(),messages=[];
const window={addEventListener(){},dispatchEvent(){},PianoLibrary:{},PianoKeyAdaptation:{},PianoPhrasePractice:{}};
vm.runInNewContext(source.replace('  initialize();',`
  renderTransport=()=>{};updateScoreCurrent=()=>{};updateActive=()=>{};updateClock=()=>{};syncSerial=()=>{};renderMidiJudgement=()=>{};renderScore=()=>{};
  toast=message=>messages.push(message);
  window.test={state,play,pause,seek,handleMidiMessage,startImmediately,animate,step};`),{
  window,document:{hidden:false},localStorage:{getItem(){return null;}},performance:{now:()=>now},messages,
  setTimeout(callback,delay){const id=++nextTimer;timers.set(id,{callback,at:now+delay});return id;},
  clearTimeout:id=>timers.delete(id),requestAnimationFrame(){},CustomEvent:class{constructor(type,options){this.detail=options.detail;}}
});
const {state,play,pause,seek,handleMidiMessage,startImmediately}=window.test;
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
pause();state.mode='timed';state.time=0;state.lookahead=.4;
startImmediately();assert.equal(state.playing,true,'立即开始不等待');assert.equal(state.countdown,0);assert.equal(timers.size,0);
assert.equal(state.time,0,'立即开始不能额外等待预亮时间');
pause();play();advance(1000);startImmediately();assert.equal(state.playing,true,'倒计时期间可以改为立即开始');assert.equal(timers.size,0);
pause();advance(4000);assert.equal(state.playing,false,'切换立即开始后不能残留旧倒计时');
window.PianoKeyAdaptation.busy=true;
play();startImmediately();assert.equal(state.playing,false,'琴键适配中不能开始播放旧谱');assert.equal(state.countdown,0);
window.PianoKeyAdaptation.busy=false;startImmediately();assert.equal(state.playing,true,'适配结束后立即开始恢复可用');pause();
console.log('开始方式：3/2/1、立即开始、倒计时中改立即开始、取消、跳转、未连接提示、适配期间禁止旧谱播放与准备期间不推进检查通过。');
state.project={duration:5,notes:[{id:'a',pitch:60,hand:'R',start:0,end:1},{id:'b',pitch:62,hand:'R',start:4,end:5}],groups:[{time:0,note_ids:['a']},{time:4,note_ids:['b']}]};
state.noteById=new Map(state.project.notes.map(n=>[n.id,n]));state.mode='timed';state.loop=false;state.time=4.9;state.groupIndex=1;state.scorePage=3;
startImmediately();advance(200);window.test.animate(now);
assert.equal(state.playing,false);assert.equal(state.time,0,'定速整曲结束后进度归零');assert.equal(state.groupIndex,0);assert.equal(state.scorePage,0);
advance(1000);window.test.animate(now);assert.equal(state.playing,false,'回到开头后保持暂停');assert.equal(state.time,0);
startImmediately();assert.equal(state.playing,true);assert.equal(state.time,0,'再次开始从头练习');pause();
state.mode='manual';state.time=4;state.groupIndex=1;state.playing=true;window.test.step(1);
assert.equal(state.playing,false);assert.equal(state.time,0,'手动推进越过末组回到开头');assert.equal(state.groupIndex,0);
state.mode='timed';state.loop=true;state.loopA=0;state.loopB=4.5;state.time=4.4;
startImmediately();advance(200);window.test.animate(now);
assert.equal(state.playing,true,'开启循环仍连续练习');assert.ok(state.time<1,'循环仍回到所选起点');pause();
console.log('整曲结束：定速与手动回到开头、保持暂停、再次开始及保留循环检查通过。');
