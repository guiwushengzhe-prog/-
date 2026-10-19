// 验证十色、五色与全红模式共用实际灯光帧，并保留已有设置。
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(require('node:path').join(__dirname,'../static/app.js'),'utf8');
const values=new Map();
function create(){
  const window={addEventListener(){},dispatchEvent(){},PianoLibrary:{},PianoKeyAdaptation:{},PianoPhrasePractice:{}};
  const selector={value:''};
  vm.runInNewContext(source.replace('  initialize();',`
    renderLegend=()=>{};renderScore=()=>{};updateActive=()=>{};syncSerial=()=>{};toast=()=>{};
    window.test={state,config,pixelsFor,exportedProject,fingerStyle};`),{
    window,localStorage:{getItem:key=>values.get(key)||null,setItem:(key,value)=>values.set(key,value)},
    document:{getElementById:()=>selector}});
  return {window,selector,...window.test};
}
const api=create(),colors=['#FF2020','#FFFF00','#00FF00','#0040FF','#FFFFFF'];
const tenColors=['#FF2020','#FF8000','#FFFF00','#80FF00','#00FF00','#00FFFF','#0040FF','#8000FF','#FF00FF','#FFFFFF'];
const notes=['L','R'].flatMap((hand,h)=>[1,2,3,4,5].map(finger=>({id:`${hand}${finger}`,hand,finger,
  pitch:60+h*5+finger-1,start:0,end:1,color:hand==='L'?'#123456':'#ABCDEF'})));
api.state.project={title:'配色检查',notes};api.state.groupIndex=7;api.state.playing=true;
api.config.ledCount=60;api.config.mapping=Object.fromEntries(notes.map((n,i)=>[n.pitch,[i,40+i]]));
const original=JSON.stringify(api.state.project);
api.window.PianoFingerColors.set(true);
assert.equal(api.selector.value,'five');assert.equal(values.get('piano-light-five-colors-v1'),'true');
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
assert.equal(api.selector.value,'ten');assert.equal(values.get('piano-light-five-colors-v1'),'false');
for(let i=0;i<notes.length;i++){
  assert.equal(api.window.PianoFingerColors.colorFor(notes[i]),tenColors[i],'关闭五色后，旧曲谱也必须使用新版十色');
  const hex=tenColors[i].slice(1),pixel=api.pixelsFor(notes)[i];
  assert.deepEqual([pixel.r,pixel.g,pixel.b],[0,2,4].map(offset=>parseInt(hex.slice(offset,offset+2),16)),'实体灯光与十色图例一致');
}
assert.match(api.fingerStyle(notes[6]),/--finger-ink:#FFFFFF/,'蓝底数字使用白字');
assert.match(api.fingerStyle(notes[7]),/--finger-ink:#FFFFFF/,'紫底数字使用白字');
assert.match(api.fingerStyle(notes[9]),/--finger-ink:#111925/,'白底数字使用深色字');
const backend=fs.readFileSync(require('node:path').join(__dirname,'../piano/music.py'),'utf8');
for(let i=0;i<notes.length;i++)assert.ok(backend.includes(`"${notes[i].id}": "${tenColors[i]}"`),'新转换的曲谱与网页十色一致');
api.window.PianoFingerColors.setMode('red');
assert.equal(api.selector.value,'red');assert.equal(values.get('piano-light-color-mode-v1'),'red');
for(const note of notes)assert.equal(api.window.PianoFingerColors.colorFor(note),'#FF0000','全红模式不区分左右手或手指');
assert.equal(api.window.PianoFingerColors.colorFor({}),'#FF0000','没有指法也只使用红色');
for(const pixel of api.pixelsFor(notes))assert.deepEqual([pixel.r,pixel.g,pixel.b],[255,0,0],'灯光实际输出纯红色');
assert.equal(api.exportedProject().ui_settings.color_mode,'red');
assert.equal(api.exportedProject().ui_settings.five_colors,false);
assert.equal(create().window.PianoFingerColors.mode,'red','重新打开仍保持全红');
api.window.PianoFingerColors.setMode('five');
for(let i=0;i<notes.length;i++)assert.equal(api.window.PianoFingerColors.colorFor(notes[i]),colors[i%5],'全红可切回五色');
api.window.PianoFingerColors.setMode('ten');
for(let i=0;i<notes.length;i++)assert.equal(api.window.PianoFingerColors.colorFor(notes[i]),tenColors[i],'全红可切回十色');
values.delete('piano-light-color-mode-v1');values.set('piano-light-five-colors-v1','true');
assert.equal(create().window.PianoFingerColors.mode,'five','升级后保留原五色选择');
assert.equal(api.state.groupIndex,7);assert.equal(api.state.playing,true);
assert.equal(JSON.stringify(api.state.project),original,'配色开关不能改写曲谱或适配原谱');
console.log('指法配色：全红纯红输出、三种配色切换、选择保存、旧五色迁移、图例与灯光一致及原谱与练习位置保留检查通过。');
