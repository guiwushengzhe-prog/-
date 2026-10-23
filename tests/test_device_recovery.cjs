const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(require('node:path').join(__dirname,'../static/app.js'),'utf8');
const elements=new Map(),timers=new Map(),storage=new Map();let now=100,nextTimer=0;
function element(id){if(!elements.has(id))elements.set(id,{textContent:'',dataset:{},disabled:false});return elements.get(id);}
const window={addEventListener(){},dispatchEvent(){},PianoLibrary:{},PianoKeyAdaptation:{},PianoPhrasePractice:{}};
const context={window,document:{getElementById:element},performance:{now:()=>now},
  localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)},
  setTimeout(fn,delay){const id=++nextTimer;timers.set(id,{fn,at:now+delay});return id;},clearTimeout:id=>timers.delete(id)};
vm.runInNewContext(source.replace('  initialize();',`
  renderTransport=()=>{};updateScoreCurrent=()=>{};updateActive=()=>{};updateClock=()=>{};renderMidiJudgement=()=>{};setDeviceState=()=>{};toast=()=>{};
  post=(path,data)=>window.transport(path,data);
  window.test={state,config,syncSerial,recovery,scheduleRecovery,cancelRecovery,pauseForDeviceLoss,toggleBluetoothMidi,reconnectDevices,
    setReconnect:fn=>reconnectSerial=fn,setMidiReconnect:fn=>toggleBluetoothMidi=fn};`),context);
const api=window.test,{state,recovery}=api;
async function flush(){for(let i=0;i<6;i++)await Promise.resolve();}
async function next(){const [id,timer]=[...timers].sort((a,b)=>a[1].at-b[1].at)[0];now=timer.at;timers.delete(id);await timer.fn();await flush();}
(async()=>{
  const sent=[];let release;
  window.transport=(path,data)=>{sent.push({path,data});return new Promise(resolve=>{release=resolve;});};
  state.serialConnected=true;state.testUntil=10000;state.testPixels=[{index:1,r:255,g:0,b:0}];
  const first=api.syncSerial();assert.equal(sent.length,1);
  state.testPixels=[{index:2,r:0,g:255,b:0}];await api.syncSerial();
  state.testPixels=[{index:3,r:0,g:0,b:255}];await api.syncSerial();
  assert.equal(sent.length,1,'发送中不排队积压旧画面');
  now+=12;release({verified:true});await first;await flush();
  assert.equal(sent.length,2,'执行确认后立即补发，不等待下一次轮询');
  assert.equal(sent[1].data.pixels[0].index,3,'只发送最新画面');
  state.serialForceClear=true;await api.syncSerial();
  release({verified:true});await flush();
  assert.equal(sent.length,3);assert.equal(sent[2].data.pixels.length,0,'清灯必须紧接在当前请求后');
  release({verified:true});await flush();
  state.testPixels=[{index:4,r:255,g:0,b:0}];now+=1;
  const immediate=api.syncSerial();assert.equal(sent.length,4,'空闲时的新画面不再额外等20毫秒');
  await api.syncSerial();release({verified:true});await immediate;await flush();
  assert.equal(sent.length,4,'确认期间的重复调用不得重复刷新相同画面');
  now+=499;await api.syncSerial();assert.equal(sent.length,4,'相同画面继续保持500毫秒心跳间隔');
  now+=1;const heartbeat=api.syncSerial();assert.equal(sent.length,5);
  release({verified:true});await heartbeat;await flush();
  let attempts=0;
  api.setReconnect(async()=>{attempts++;api.scheduleRecovery('serial');});
  recovery.serial.wanted=true;api.scheduleRecovery('serial');api.scheduleRecovery('serial');
  assert.equal(timers.size,1,'同一设备只保留一个重连任务');
  while(timers.size)await next();
  assert.equal(attempts,5,'重连失败最多五次，不能无限重试');
  assert.match(element('serial-message').textContent,/点击连接/);
  api.cancelRecovery('serial');recovery.serial.wanted=true;api.scheduleRecovery('serial');
  api.cancelRecovery('serial',true);assert.equal(timers.size,0,'手动断开立即取消重连');
  let midiAttempts=0;
  api.setMidiReconnect(async()=>{midiAttempts++;api.scheduleRecovery('midi');});
  recovery.midi.wanted=true;api.scheduleRecovery('midi');while(timers.size)await next();
  assert.equal(midiAttempts,5,'蓝牙重连同样有界且不会弹出新设备选择器');
  let manualConnects=0;
  window.BleMidi={async connect(){manualConnects++;return {connected:true,name:'检查琴',disconnect(){}};}};
  await api.toggleBluetoothMidi(false,false);await api.toggleBluetoothMidi(false,false);
  await api.reconnectDevices();
  assert.equal(manualConnects,1,'用户已手动断开后，迟到的启动流程不得再次连接');
  assert.equal(recovery.midi.wanted,false);
  console.log('设备恢复：变化立即发送、确认后补发最新画面、相同画面去重与心跳、立即清灯、重连去重、五次上限和手动取消检查通过。');
})().catch(error=>{console.error(error);process.exitCode=1;});
