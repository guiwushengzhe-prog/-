// 直接验证正式替代函数：缺失白键、和弦合并、旋律方向、范围调整及原谱保留。
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(require('node:path').join(__dirname,'../static/app.js'),'utf8');
const moduleSource=source.slice(source.indexOf('/* 邻键替代：')).replace('  install();','');
const window={PianoPhrasePractice:{}};vm.runInNewContext(moduleSource,{window});
const transform=window.PianoKeyAdaptation.transform;
const config=pitches=>({ledCount:60,mapping:Object.fromEntries(pitches.map((pitch,i)=>[pitch,[i]]))});
function score(groups){
  const notes=groups.flatMap((pitches,g)=>pitches.map((pitch,i)=>({id:`${g}:${i}`,pitch,start:g,end:g+0.8,hand:'R',finger:5,color:'#ffffff',jianpu:{degree:'old'}})));
  return {title:'替代检查',notes,groups:groups.map((pitches,g)=>({time:g,note_ids:pitches.map((p,i)=>`${g}:${i}`)}))};
}
let original=score([[60,61,64]]),before=JSON.stringify(original);
let result=transform(original,config([60,62,64]));
assert.deepEqual(Array.from(result.notes,n=>n.pitch),[60,62,64],'等距离时优先使用和弦中尚未占用的邻键');
assert.equal(result.stats.black,1);assert.equal(result.stats.white,0);assert.equal(result.stats.merged,0);
assert.equal(JSON.stringify(original),before,'转换不得改写原谱');
assert.equal(result.notes.some(n=>'jianpu' in n||'finger' in n||'color' in n),false,'必须丢弃旧简谱和指法交由原有引擎重算');
original=score([[60,61,62]]);original.notes[2].end=2;
result=transform(original,config([60]));
assert.equal(result.notes.length,1,'同一组不同音落在同一琴键时合并');
assert.equal(result.notes[0].end,2,'合并保留较晚的结束时间');
assert.equal(result.notes[0].adapted_from.length,3);
assert.equal(result.stats.black,1);assert.equal(result.stats.white,1);assert.equal(result.stats.merged,2);
result=transform(score([[60],[61],[64]]),config([60,62,64]));
assert.deepEqual(Array.from(result.notes,n=>n.pitch),[60,62,64],'等距离替代尽量保留旋律上行方向');
result=transform(score([[24],[108]]),config([36,60,84,96]));
assert.deepEqual(Array.from(result.notes,n=>n.pitch),[36,96],'超范围音优先移动整组同名键后再替代');
assert.equal(result.stats.octaveShifted,2);
assert.equal(result.stats.white,2);
const sparse={ledCount:60,mapping:{60:[60],62:[-1],64:[0],65:[1.5]}};
result=transform(score([[60,61,62,63,64,65]]),sparse);
assert.deepEqual(Array.from(result.available),[64],'只认可有效灯珠对应的琴键');
assert.equal(result.notes.every(n=>n.pitch===64),true);
assert.throws(()=>transform(score([[60]]),config([])),/还没有已对应琴键/,'无映射不能猜测琴键');
original=score([[61],[64]]);
const adapted={key_adaptation:{original_project:original},notes:[],groups:[]};
result=transform(adapted,config([60,64]));
assert.equal(result.original,original,'再次适配仍从原谱开始');
assert.deepEqual(Array.from(result.notes,n=>n.pitch),[60,64]);
// 把适配结果交给正式判定和灯光函数，确认原音不能冒充替代音，松开也不会累计。
const coreWindow={addEventListener(){},dispatchEvent(){},PianoLibrary:{},PianoKeyAdaptation:{},PianoPhrasePractice:{}};
const core=source.replace('  initialize();',`
  renderMidiJudgement=()=>{};updateActive=()=>{};updateClock=()=>{};renderTransport=()=>{};
  updateScoreCurrent=()=>{if(state.midiJudgedGroup!==state.groupIndex)resetMidiJudgement();};
  syncSerial=()=>{};toast=()=>{};
  window.test={state,config,handleMidiMessage,midiExpectedPitches,pixelsFor};`);
vm.runInNewContext(core,{window:coreWindow,localStorage:{getItem(){return null;}},performance:{now:()=>0},
  document:{getElementById(){return {textContent:'',dataset:{}};}},
  CustomEvent:class{constructor(type,options){this.detail=options.detail;}}});
const api=coreWindow.test,fixture=score([[61,64],[67]]),mapping=config([60,64,67]);
result=transform(fixture,mapping);
const adaptedNotes=result.notes.map(n=>({...n,finger:1,color:'#68D2E7'}));
api.state.project={...fixture,notes:adaptedNotes,duration:3};api.state.noteById=new Map(adaptedNotes.map(n=>[String(n.id),n]));
api.state.mode='correct';api.state.playing=true;api.state.groupIndex=0;
Object.assign(api.config,mapping);
assert.deepEqual(Array.from(api.midiExpectedPitches()),[60,64],'判定要求替代后的实际按键');
assert.deepEqual(Array.from(api.pixelsFor(adaptedNotes.slice(0,2)),p=>p.index),[0,1],'灯光使用替代后的同一组音高');
const message=(pitch,velocity=90)=>api.handleMidiMessage({data:[0x90,pitch,velocity]});
message(61);assert.equal(api.state.groupIndex,0,'原来的未对应音不能通过替代音判定');
message(60);message(60,0);message(64);assert.equal(api.state.groupIndex,0,'替代和弦仍必须同时按住');
message(60);assert.equal(api.state.groupIndex,1,'同时按住替代后的和弦才推进');
console.log('邻键替代：黑白键、缺键、和弦合并、旋律、超范围、无效映射、指法重算入口和原谱保留检查通过。');
