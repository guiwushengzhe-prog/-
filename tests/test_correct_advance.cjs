// 验证真实判定和推进函数；只替换页面绘制，不连接实体设备。
const fs=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const source=fs.readFileSync(require('node:path').join(__dirname,'../static/app.js'),'utf8');
const window={addEventListener(){},dispatchEvent(){}};
const context={window,localStorage:{getItem(){return null;}},performance:{now:()=>0},
  document:{getElementById(){return {textContent:'',dataset:{}};}},
  CustomEvent:class{constructor(type,options){this.detail=options.detail;}},console};
const instrumented=source.replace('  initialize();',`
  renderMidiJudgement=()=>{};updateActive=()=>{};updateClock=()=>{};renderTransport=()=>{};
  updateScoreCurrent=()=>{if(state.midiJudgedGroup!==state.groupIndex)resetMidiJudgement();};
  syncSerial=()=>{};toast=()=>{};
  window.test={state,handleMidiMessage,judgeMidiPitch,resetMidiJudgement,step};`);
vm.runInNewContext(instrumented,context);
const {state,handleMidiMessage:receive,resetMidiJudgement,step}=window.test;
function setup(groups,hand='both'){
  const notes=groups.flatMap((pitches,index)=>pitches.map((pitch,n)=>({id:`${index}:${n}`,pitch,hand:n?'L':'R'})));
  state.project={duration:10,groups:groups.map((p,index)=>({time:index,note_ids:notes.filter(n=>n.id.startsWith(index+':')).map(n=>n.id)}))};
  state.noteById=new Map(notes.map(n=>[n.id,n]));state.mode='correct';state.playing=true;
  state.groupIndex=0;state.hand=hand;state.loop=false;state.midiHeld.clear();resetMidiJudgement();
}
const on=pitch=>receive({data:[0x90,pitch,90]});
const off=pitch=>receive({data:[0x80,pitch,0]});
setup([[60,64],[67]]);
on(61);assert.equal(state.groupIndex,0,'错音不得推进');
on(60);assert.equal(state.groupIndex,0,'和弦未弹齐不得推进');
on(64);assert.equal(state.groupIndex,1,'音组弹齐只推进一组');
on(67);assert.equal(state.playing,false,'末组弹对后停止');
setup([[60],[60],[62]]);
on(60);assert.equal(state.groupIndex,1);
on(60);assert.equal(state.groupIndex,1,'按住或重复按下消息不得跳过同音组');
off(60);on(60);assert.equal(state.groupIndex,2,'同音组必须重新按下');
setup([[60],[62]]);state.playing=false;on(60);
assert.equal(state.groupIndex,0,'暂停时不得推进');assert.equal(state.midiMatched.size,0,'暂停时不累计判对');
setup([[60,64],[67,69]],'L');on(60);assert.equal(state.groupIndex,0);on(64);assert.equal(state.groupIndex,1,'遵守手别筛选');
setup([[60]]);state.loop=true;state.loopA=0;state.loopB=1;on(60);
assert.equal(state.playing,true);assert.equal(state.midiMatched.size,0,'单音组循环须清空上一轮判定');
off(60);on(60);assert.equal(state.playing,true);
console.log('弹对推进：错音、和弦、重按、暂停、手别、循环检查通过。');
