const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(require('node:path').join(__dirname,'../static/ble_midi.js'),'utf8');
const storage=new Map(),timers=new Map();let nextTimer=0,prompts=0,messages=[];
const deviceListeners=new Map(),valueListeners=new Map();
let connectTarget;
function device(id){
  return {id,name:'钢琴 '+id,addEventListener:(type,fn)=>deviceListeners.set(id+type,fn),removeEventListener:(type)=>deviceListeners.delete(id+type),
    gatt:{connected:false,async connect(){connectTarget=id;this.connected=true;return {async getPrimaryService(){return {async getCharacteristic(){return {
      addEventListener:(type,fn)=>valueListeners.set(id+type,fn),removeEventListener:type=>valueListeners.delete(id+type),async startNotifications(){}
    };}};}};},disconnect(){this.connected=false;}}
  };
}
const first=device('first'),last=device('last');let permitted=[first,last];
const bluetooth={async getDevices(){return permitted;},async requestDevice(){prompts++;return last;}};
const window={};vm.runInNewContext(source,{window,navigator:{bluetooth},Uint8Array,
  localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)},
  setTimeout(fn){const id=++nextTimer;timers.set(id,fn);return id;},clearTimeout:id=>timers.delete(id)
});
(async()=>{
  storage.set('piano-light-last-bluetooth-v1',JSON.stringify({id:'last'}));
  const connection=await window.BleMidi.connect({automatic:true,onMessage:data=>messages.push(Array.from(data))});
  assert.equal(connectTarget,'last','只能重连上次设备');assert.equal(prompts,0,'自动连接不能弹出授权选择器');assert.equal(connection.connected,true);
  const data=new Uint8Array([0x80,0x80,0x90,60,90]);
  valueListeners.get('lastcharacteristicvaluechanged')({target:{value:new DataView(data.buffer)}});
  assert.deepEqual(messages,[[0x90,60,90]],'自动重连必须接回真正的通知解析回调');
  connection.disconnect();assert.equal(valueListeners.size,0);assert.equal(deviceListeners.size,0);
  permitted=[first];await assert.rejects(window.BleMidi.connect({automatic:true,onMessage(){}}),/未找到上次/);
  assert.equal(connectTarget,'last','上次设备不在时不能连其他设备');assert.equal(prompts,0);
  const manual=await window.BleMidi.connect({onMessage(){}});assert.equal(prompts,1);
  assert.equal(JSON.parse(storage.get('piano-light-last-bluetooth-v1')).id,'last','手动成功连接后记住设备');
  manual.disconnect();permitted=[last];
  let finish;last.gatt.connect=()=>new Promise(resolve=>{finish=resolve;});
  const pending=window.BleMidi.connect({automatic:true,onMessage(){}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(timers.size,1,'连接等待必须设置超时');
  for(const callback of [...timers.values()])callback();
  await assert.rejects(pending,/连接超时/);assert.equal(deviceListeners.size,0,'超时释放监听器');
  last.gatt.connected=true;finish({});await Promise.resolve();await Promise.resolve();
  assert.equal(last.gatt.connected,false,'超时后迟到的连接也必须释放');
  delete bluetooth.getDevices;
  await assert.rejects(window.BleMidi.connect({automatic:true,onMessage(){}}),/暂不支持自动找回/);
  assert.equal(prompts,1,'浏览器不支持免选择器重连时不能反复弹窗');
  console.log('蓝牙重连：指定上次设备、免选择器、接回按键通知、设备缺失不串连、手动记忆和超时释放检查通过。');
})().catch(error=>{console.error(error);process.exitCode=1;});
