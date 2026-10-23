"""Serial protocol 2: identify the receiver and confirm each changed frame.

Protocol 1 remains usable until the new firmware is uploaded; its writes are
explicitly reported as unverified rather than pretending to acknowledge them.
"""
from __future__ import annotations

import json
import math
import threading
import time


class SerialLights:
    def __init__(self):
        self.port = None
        self.lock = threading.Lock()
        self.device = ""
        self.info = {}
        self.sequence = 0
        self.last_frame = None
        self.last_ack = None
        self.reply_buffer = bytearray()

    def ports(self):
        try:
            from serial.tools.list_ports import comports
        except ImportError:
            return []
        return [{"device": port.device, "description": port.description} for port in comports()]

    def _status(self):
        connected = bool(self.port and self.port.is_open)
        return {"connected": connected, "port": self.device,
                "verified": connected and self.info.get("protocol") == 2,
                "protocol": self.info.get("protocol", 1), **self.info,
                "last_ack": self.last_ack}

    def status(self):
        with self.lock:
            return self._status()

    def _write(self, message):
        data = json.dumps(message, separators=(",", ":")).encode() + b"\n"
        written = self.port.write(data)
        if written is not None and written != len(data):
            raise OSError("灯带命令未完整发出。")

    def _reply(self, sequence, deadline, expected):
        while time.monotonic() < deadline:
            chunk = self.port.read_until(b"\n", 2048)
            if not chunk:
                continue
            self.reply_buffer.extend(chunk)
            if len(self.reply_buffer) > 4096:
                self.reply_buffer.clear()
                continue
            while b"\n" in self.reply_buffer:
                line, _, rest = self.reply_buffer.partition(b"\n")
                self.reply_buffer = bytearray(rest)
                try:
                    reply = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    continue
                if not isinstance(reply, dict) or reply.get("seq") != sequence:
                    if isinstance(reply, dict) and reply.get("type") == "ready" and expected == "ack":
                        raise OSError("灯带控制器已重启，正在等待重新连接。")
                    continue
                if reply.get("type") == "error":
                    reasons = {"pixels": "灯珠编号或颜色超出固件范围，请检查灯珠数量与映射。",
                               "brightness": "固件拒绝了无效亮度。", "sequence": "灯光命令顺序失效，请重新连接。",
                               "command": "固件不支持该命令。", "json": "固件未能读取命令。"}
                    raise ValueError(reasons.get(reply.get("code"), "固件未能执行灯光命令。"))
                if reply.get("type") == expected:
                    return reply
        return None

    def _command(self, kind, **fields):
        self.sequence = self.sequence % 0xFFFFFFFE + 1
        sequence = self.sequence
        started = time.perf_counter()
        self._write({"type": kind, "seq": sequence, **fields})
        reply = self._reply(sequence, time.monotonic() + .35, "ack")
        if reply is None or reply.get("command") != kind:
            raise OSError("灯带没有确认执行，连接已暂停。")
        self.last_ack = {"sequence": sequence, "command": kind, "received_at": time.time(),
                         "round_trip_ms": round((time.perf_counter() - started) * 1000, 2)}
        return reply

    def connect(self, device, baud):
        import serial
        if device not in {port["device"] for port in self.ports()}:
            raise ValueError("请选择当前检测到的串口。")
        if int(baud) != 115200:
            raise ValueError("固件协议使用 115200 波特率。")
        with self.lock:
            self._disconnect()
            self.port = serial.Serial(device, 115200, timeout=.035, write_timeout=.25)
            self.device, self.info = device, {}
            self.sequence, self.last_frame, self.last_ack = 0, None, None
            self.reply_buffer.clear()
            try:
                # Opening USB serial can reset a board. Repeating the greeting
                # waits for its actual reply instead of relying on a blind delay.
                deadline = time.monotonic() + 2.1
                while time.monotonic() < deadline:
                    self.sequence += 1
                    self._write({"type": "hello", "seq": self.sequence})
                    reply = self._reply(self.sequence, min(deadline, time.monotonic() + .3), "hello")
                    if reply is not None:
                        if reply.get("protocol") != 2 or type(reply.get("led_count")) is not int or not 1 <= reply["led_count"] <= 512:
                            raise ValueError("灯带返回的协议或灯珠数量无效，请核对固件版本。")
                        self.info = {key: reply[key] for key in ("protocol", "firmware", "led_count", "data_pin", "color_order") if key in reply}
                        break
                if self.info:
                    self._command("clear")
                else:
                    self.info = {"protocol": 1, "firmware": "旧版固件（无执行回报）"}
                    self._write({"type": "clear"})
            except Exception:
                self._close()
                raise
            return self._status()

    def _close(self):
        port, self.port = self.port, None
        self.last_frame = None
        if port:
            port.close()

    def _disconnect(self):
        if not self.port:
            return
        try:
            if self.port.is_open:
                if self.info.get("protocol") == 2:
                    self._command("clear")
                else:
                    self._write({"type": "clear"})
        except (OSError, ValueError):
            pass
        finally:
            self._close()

    def disconnect(self):
        with self.lock:
            self._disconnect()
        return {"connected": False}

    def frame(self, request):
        pixels = request.get("pixels", [])
        brightness = float(request.get("brightness", .15))
        if not math.isfinite(brightness) or not 0 <= brightness <= 1:
            raise ValueError("亮度应在 0–1 之间。")
        if not isinstance(pixels, list) or len(pixels) > 512:
            raise ValueError("单帧最多 512 个灯珠。")
        packed = []
        for pixel in pixels:
            if isinstance(pixel, dict):
                pixel = [pixel.get(key) for key in ("index", "r", "g", "b")]
            if not isinstance(pixel, list) or len(pixel) != 4 or any(type(value) is not int for value in pixel):
                raise ValueError("灯珠应包含整数 index/r/g/b。")
            if not 0 <= pixel[0] < 512 or not all(0 <= value <= 255 for value in pixel[1:]):
                raise ValueError("灯珠编号或颜色超出范围。")
            packed.append(pixel)
        # Canonical ordering lets unchanged pictures use a tiny heartbeat.
        packed.sort(key=lambda pixel: pixel[0])
        signature = (brightness, tuple(tuple(pixel) for pixel in packed))
        with self.lock:
            if not self.port or not self.port.is_open:
                raise OSError("灯条串口尚未连接。")
            if any(pixel[0] >= self.info.get("led_count", 512) for pixel in packed):
                raise ValueError(f"灯珠编号超出固件的 {self.info['led_count']} 颗范围，请检查映射。")
            verified = self.info.get("protocol") == 2
            try:
                if verified:
                    kind = "ping" if signature == self.last_frame else "frame" if packed else "clear"
                    reply = self._command(kind, **({"brightness": brightness, "pixels": packed} if kind == "frame" else {}))
                    if kind == "ping" and reply.get("lit") is False and any(any(pixel[1:]) for pixel in packed):
                        # The receiver may have cleared itself after a stalled
                        # browser. A live connection must restore the picture.
                        kind = "frame"
                        self._command(kind, brightness=brightness, pixels=packed)
                else:
                    kind = "frame"
                    self._write({"type": kind, "brightness": brightness, "pixels": packed})
            except OSError:
                self._close()
                raise
            self.last_frame = signature
            return {"sent": len(packed), "brightness": brightness, "verified": verified,
                    "command": kind, "last_ack": self.last_ack}
