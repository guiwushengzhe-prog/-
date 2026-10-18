/*
 * 浏览器蓝牙 MIDI 连接与数据包解析。
 * 连接流程与数据包状态处理参考 BLE-MIDI/WebMIDI 开源项目
 * （https://github.com/BLE-MIDI/WebMIDI，Apache-2.0 许可证，版本
 * 0597f4092514607654ed3166527bea645d42188e）。许可证副本位于
 * licenses/BLE-MIDI-WebMIDI-LICENSE。
 */
(() => {
  'use strict';

  const serviceUuid = '03b80e5a-ede8-4b33-a751-6ce34ec4c700';
  const characteristicUuid = '7772e5db-3868-4112-a1a9-f2669d106bf3';
  const dataLengths = status => {
    if (status < 0xf0) {
      const family = status & 0xf0;
      return family === 0xc0 || family === 0xd0 ? 1 : 2;
    }
    return ({0xf1:1,0xf2:2,0xf3:1,0xf6:0,0xf8:0,0xf9:0,0xfa:0,0xfb:0,
      0xfc:0,0xfd:0,0xfe:0,0xff:0})[status] ?? -1;
  };

  function createDecoder(onMessage) {
    let runningStatus = 0;
    return packet => {
      if (packet.length < 2 || !(packet[0] & 0x80) || !(packet[1] & 0x80)) return;
      const messages = [];
      let index = 2;
      let needTimestamp = false;
      let pendingStatus = 0;
      let pending = [];
      let inSysEx = false;

      const finish = () => {
        messages.push(Uint8Array.of(pendingStatus, ...pending));
        pendingStatus = 0;
        pending = [];
        needTimestamp = true;
      };

      while (index < packet.length) {
        const value = packet[index++];
        if (needTimestamp && (value & 0x80)) {
          needTimestamp = false;
          continue;
        }
        if (inSysEx) {
          if (value === 0xf7) { inSysEx = false; needTimestamp = true; }
          continue;
        }
        if (value & 0x80) {
          if (value >= 0xf8) {
            messages.push(Uint8Array.of(value));
            needTimestamp = true;
            continue;
          }
          pending = [];
          if (value === 0xf0) {
            runningStatus = 0;
            pendingStatus = 0;
            inSysEx = true;
            continue;
          }
          if (value === 0xf7) {
            runningStatus = 0;
            pendingStatus = 0;
            needTimestamp = true;
            continue;
          }
          const length = dataLengths(value);
          if (length < 0) {
            runningStatus = 0;
            pendingStatus = 0;
            needTimestamp = true;
            continue;
          }
          if (value < 0xf0) runningStatus = value;
          else runningStatus = 0;
          pendingStatus = value;
          if (length === 0) finish();
          continue;
        }

        if (!pendingStatus) {
          if (runningStatus < 0x80 || runningStatus >= 0xf0) continue;
          pendingStatus = runningStatus;
          pending = [];
        }
        pending.push(value);
        if (pending.length >= dataLengths(pendingStatus)) finish();
      }
      for (const message of messages) onMessage(message);
    };
  }

  async function connect({includeAllDevices = false, onMessage, onDisconnected}) {
    if (!navigator.bluetooth?.requestDevice) {
      throw new Error('当前浏览器不支持网页蓝牙，请使用新版 Chrome 或 Edge。');
    }
    const device = await navigator.bluetooth.requestDevice(includeAllDevices
      ? {acceptAllDevices:true, optionalServices:[serviceUuid]}
      : {filters:[{services:[serviceUuid]}], optionalServices:[serviceUuid]});
    const decoder = createDecoder(onMessage);
    let disconnected = false;
    const onLost = () => {
      if (disconnected) return;
      disconnected = true;
      onDisconnected?.(device);
    };
    device.addEventListener('gattserverdisconnected', onLost);
    try {
      const server = await device.gatt.connect();
      const service = await server.getPrimaryService(serviceUuid);
      const characteristic = await service.getCharacteristic(characteristicUuid);
      characteristic.addEventListener('characteristicvaluechanged', event => {
        const value = event.target.value;
        decoder(new Uint8Array(value.buffer, value.byteOffset, value.byteLength));
      });
      await characteristic.startNotifications();
      return {
        name: device.name || '蓝牙 MIDI 钢琴',
        disconnect() {
          device.removeEventListener('gattserverdisconnected', onLost);
          if (device.gatt.connected) device.gatt.disconnect();
          disconnected = true;
        }
      };
    } catch (error) {
      if (device.gatt.connected) device.gatt.disconnect();
      throw error;
    }
  }

  window.BleMidi = {connect, createDecoder};
})();
