// 验证五色模式确实改变实际灯光帧，并能无损恢复原十指配色。
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(require('node:path').join(__dirname,'../static/app.js'),'utf8');
const values=new Map();
function create(){
  const window={addEventListener(){},dispatchEvent(){},PianoLibrary:{},PianoKeyAdaptation:{}};
  const checkbox={checked:false};
  vm.runInNewContext(source.replace('  initialize();',`
    renderLegend=()=>{};renderScore=()=>{};updateActive=()=>{};syncSerial=()=>{};toast=()=>{};
    window.test={state,config,pixelsFor,exportedProject};`),{
    window,localStorage:{getItem:key=>values.get(key)||null,setItem:(key,value)=>values.set(key,value)},
    document:{getElementById:()=>checkbox}});
  return {window,checkbox,...window.test};
}
const api=create(),colors=['#FF0000','#FFFF00','#00FF00','#0080FF','#FF00FF'];
const notes=['L','R'].flatMap((hand,h)=>[1,2,3,4,5].map(finger=>({id:`${hand}${finger}`,hand,finger,
  pitch:60+h*5+finger-1,start:0,end:1,color:hand==='L'?'#123456':'#ABCDEF'})));
api.state.project={title:'配色检查',notes};api.state.groupIndex=7;api.state.playing=true;
api.config.ledCount=60;api.config.mapping=Object.fromEntries(notes.map((n,i)=>[n.pitch,[i,40+i]]));
const original=JSON.stringify(api.state.project);
api.window.PianoFingerColors.set(true);
assert.equal(api.checkbox.checked,true);assert.equal(values.get('piano-light-five-colors-v1'),'true');
assert.equal(new Set(notes.map(api.window.PianoFingerColors.colorFor)).size,5,'双手总共只有五种颜色');
for(let finger=1;finger<=5;finger++){
  for(const hand of ['L','R'])assert.equal(api.window.PianoFingerColors.colorFor(notes.find(n=>n.hand===hand&&n.finger===finger)),colors[finger-1]);
}
const pixels=api.pixelsFor(notes);
assert.equal(pixels.length,10,'每个琴键仍只使用一颗有效灯珠');
for(let i=0;i<10;i++){
  const hex=colors[i%5].slice(1);
  assert.equal(pixels[i].index,i);
  assert.deepEqual([pixels[i].r,pixels[i].g,pixels[i].b],[0,2,4].map(offset=>parseInt(hex.slice(offset,offset+2),16)),'实际灯光帧必须采用五色值');
}
assert.equal(api.exportedProject().ui_settings.five_colors,true);
assert.equal(api.state.groupIndex,7,'切换颜色不得改变练习位置');assert.equal(api.state.playing,true);
assert.equal(create().window.PianoFingerColors.enabled,true,'重新打开页面保留五色开关');
api.window.PianoFingerColors.set(false);
assert.equal(api.checkbox.checked,false);assert.equal(values.get('piano-light-five-colors-v1'),'false');
for(const note of notes)assert.equal(api.window.PianoFingerColors.colorFor(note),note.color,'关闭后恢复曲谱原有颜色');
assert.equal(JSON.stringify(api.state.project),original,'配色开关不能改写曲谱或适配原谱');
console.log('五色指法：双手同指同色、五色区分、实际灯光帧、单键单灯、关闭恢复、设置保存及练习位置保留检查通过。');
