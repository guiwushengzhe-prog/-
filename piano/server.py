"""Loopback-only local workbench. No cloud service or account is required."""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .music import build_project, demo_project, read_midi, write_midi

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path(os.environ.get("PIANO_DATA_DIR", ROOT / ".runtime"))
MAX_UPLOAD = 64 * 1024 * 1024
JOBS = {}
JOB_LOCK = threading.Lock()
IMPORT_LOCK = threading.Lock()
WORKER = ROOT / "piano" / ("transcribe_worker.py" if os.environ.get("PIANO_TRANSCRIPTION_ENGINE") == "basic-pitch" else "piano_worker.py")
ENGINE_PYTHON = os.environ.get("PIANO_ENGINE_PYTHON", sys.executable)


def engine_status():
    # Availability is established by import checks, never by inventing a score.
    try:
        result = subprocess.run([ENGINE_PYTHON, str(WORKER), "--check"],
                                capture_output=True, text=True, timeout=25)
        lines = [line for line in result.stdout.splitlines() if line.startswith("{")]
        if lines:
            report = json.loads(lines[-1])
            available = result.returncode == 0 and report.get("available", False)
            return {"available": available,
                    "message": report.get("message", "本地转谱引擎已就绪" if available else "转谱引擎未就绪"),
                    "details": report}
        return {"available": False, "message": "本地转谱依赖未安装，请运行 setup.sh。"}
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return {"available": False, "message": "本地转谱引擎未就绪，请运行 setup.sh。"}


class SerialLights:
    def __init__(self):
        self.port = None
        self.lock = threading.Lock()

    def ports(self):
        try:
            from serial.tools.list_ports import comports
        except ImportError:
            return []
        return [{"device": p.device, "description": p.description} for p in comports()]

    def connect(self, device, baud):
        import serial
        # Prevent a local UI from writing arbitrary files under the name of a port.
        if device not in {p["device"] for p in self.ports()}:
            raise ValueError("请选择当前检测到的串口。")
        if int(baud) != 115200:
            raise ValueError("固件协议使用 115200 波特率。")
        with self.lock:
            self._disconnect()
            self.port = serial.Serial(device, 115200, timeout=.1, write_timeout=.25)
            self.port.write(b'{"type":"clear"}\n')
        return {"connected": True, "port": device}

    def _disconnect(self):
        if self.port:
            try:
                self.port.write(b'{"type":"clear"}\n')
            finally:
                self.port.close()
                self.port = None

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
        for p in pixels:
            if isinstance(p, dict):
                p = [p.get("index"), p.get("r"), p.get("g"), p.get("b")]
            if not isinstance(p, list) or len(p) != 4 or any(type(v) is not int for v in p):
                raise ValueError("灯珠应包含整数 index/r/g/b。")
            if not 0 <= p[0] < 512 or not all(0 <= v <= 255 for v in p[1:]):
                raise ValueError("灯珠编号或颜色超出范围。")
            packed.append(p)
        line = json.dumps({"type": "frame", "brightness": min(brightness, .35),
                           "pixels": packed}, separators=(",", ":")).encode() + b"\n"
        with self.lock:
            if not self.port or not self.port.is_open:
                raise ValueError("灯条串口尚未连接。")
            try:
                self.port.write(line)
            except Exception:
                self._disconnect()
                raise
        return {"sent": len(packed), "brightness": min(brightness, .35)}


LIGHTS = SerialLights()


def set_job(job_id, **fields):
    with JOB_LOCK:
        JOBS[job_id].update(fields)


def process_import(job_id, path, filename, options):
    try:
        set_job(job_id, status="running", message="读取音频与音符…")
        suffix = path.suffix.lower()
        if suffix in (".mid", ".midi"):
            notes, detected_bpm, extra = read_midi(path.read_bytes())
            transcription = {"engine": "Mido MIDI", **extra}
        else:
            output = path.with_suffix(".notes.json")
            process = subprocess.Popen([ENGINE_PYTHON, str(WORKER), str(path), str(output)],
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, bufsize=1)
            log = []
            deadline = time.monotonic() + 3600
            # A watchdog also covers workers stalled before producing any stdout.
            timer = threading.Timer(3600, process.kill)
            timer.start()
            try:
                for line in process.stdout:
                    log.append(line.strip())
                    log = log[-12:]
                    if time.monotonic() > deadline:
                        process.kill()
                    try:
                        event = json.loads(line)
                        if isinstance(event, dict) and event.get("message"):
                            set_job(job_id, message=str(event["message"])[:300])
                    except ValueError:
                        pass
                code = process.wait()
            finally:
                timer.cancel()
                if process.poll() is None:
                    process.kill()
                    process.wait()
            if code or not output.exists():
                detail = next((x for x in reversed(log) if '"error"' in x), "")
                try:
                    detail = json.loads(detail).get("error", "")
                except ValueError:
                    pass
                raise ValueError(detail or "自动转谱未完成，请检查音频格式和本地模型安装。")
            result = json.loads(output.read_text())
            notes = result["notes"]
            detected_bpm = result.get("bpm", result.get("metadata", {}).get("bpm", 100))
            transcription = {k: v for k, v in result.items() if k != "notes"}
        set_job(job_id, message="自动分配左右手、计算指法与灯色…")
        bpm = options.get("bpm") or detected_bpm
        tonic = options.get("tonic", -1)
        source = {"kind": "midi" if suffix in (".mid", ".midi") else "ncm" if suffix == ".ncm" else "audio",
                  "filename": filename}
        if suffix == ".ncm" and (path.parent / "converted.mp3").is_file():
            source["converted_audio_url"] = f"/api/jobs/{job_id}/audio.mp3"
        project = build_project(notes, title=Path(filename).stem, bpm=bpm, tonic=tonic,
                                hand_size=options.get("hand_size", "M"),
                                source=source, transcription=transcription)
        (path.parent / "project.json").write_text(json.dumps(project, ensure_ascii=False, indent=2))
        set_job(job_id, status="done", message="简谱、指法与灯光已自动生成", project=project)
    except Exception as exc:
        extra = {}
        if (path.parent / "converted.mp3").is_file():
            extra["converted_audio_url"] = f"/api/jobs/{job_id}/audio.mp3"
        set_job(job_id, status="error", message="生成未完成", error=str(exc)[:600], **extra)
    finally:
        IMPORT_LOCK.release()


def process_midi_search(job_id, query, directory, options):
    try:
        from .midi_sources import download_best
        set_job(job_id, status="running", message="正在搜索可下载的曲谱 MIDI…")
        found = download_best(query, directory, progress=lambda message: set_job(job_id, message=message))
        notes, bpm, extra = read_midi(Path(found["path"]).read_bytes())
        set_job(job_id, message="已下载 MIDI，正在自动分配双手指法和灯色…")
        source = {"kind": "midi-search", "query": query,
                  **{key: str(found.get(key, "")) for key in ("provider", "license", "page_url", "midi_url", "composer")}}
        project = build_project(notes, title=found["title"], bpm=bpm,
                                hand_size=options.get("hand_size", "M"),
                                source=source, transcription={"engine": "在线 MIDI / Mido", **extra})
        (directory / "project.json").write_text(json.dumps(project, ensure_ascii=False, indent=2))
        set_job(job_id, status="done", message="MIDI 已自动下载，指法、简谱和灯光已生成", project=project)
    except Exception as exc:
        set_job(job_id, status="error", message="未能自动取得可用曲谱", error=str(exc)[:600])
    finally:
        IMPORT_LOCK.release()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Do not log uploaded filenames or request bodies.
        return

    def send(self, status, body, content_type="application/json; charset=utf-8"):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def local_request(self):
        host = self.headers.get("Host", "")
        if not re.fullmatch(r"(127\.0\.0\.1|localhost)(:\d+)?", host):
            return False
        origin = self.headers.get("Origin")
        return not origin or origin in (f"http://{host}", f"https://{host}")

    def body(self, limit=MAX_UPLOAD):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("请求长度无效。") from exc
        if not 0 < length <= limit:
            raise ValueError(f"文件或请求应在 {limit // 1024 // 1024} MB 以内。")
        return self.rfile.read(length)

    def do_GET(self):
        if not self.local_request():
            return self.send(403, {"error": "仅允许本机访问。"})
        path = urlparse(self.path).path
        try:
            if path == "/api/status":
                return self.send(200, {"engine": self.server.engine,
                                       "serial": {"available": importlib.util.find_spec("serial") is not None,
                                                  "ports": LIGHTS.ports()}})
            if path == "/api/demo":
                return self.send(200, demo_project())
            audio_match = re.fullmatch(r"/api/jobs/([a-f0-9]{32})/audio\.mp3", path)
            if audio_match:
                audio_path = RUNTIME / audio_match[1] / "converted.mp3"
                if not audio_path.is_file():
                    return self.send(404, {"error": "转换后的 MP3 尚未生成。"})
                return self.send(200, audio_path.read_bytes(), "audio/mpeg")
            if path.startswith("/api/jobs/"):
                job_id = path.rsplit("/", 1)[-1]
                with JOB_LOCK:
                    job = dict(JOBS.get(job_id, {}))
                return self.send(200 if job else 404, job or {"error": "任务不存在。"})
            if path == "/api/ports":
                return self.send(200, {"ports": LIGHTS.ports()})
            static = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                      "/style.css": ("style.css", "text/css; charset=utf-8")}
            if path in static:
                filename, mime = static[path]
                return self.send(200, (ROOT / "static" / filename).read_bytes(), mime)
            return self.send(404, {"error": "页面不存在。"})
        except Exception as exc:
            return self.send(400, {"error": str(exc)[:600]})

    def do_POST(self):
        if not self.local_request():
            return self.send(403, {"error": "仅允许本机同源请求。"})
        parsed = urlparse(self.path)
        path, query = parsed.path, parse_qs(parsed.query)
        try:
            if path == "/api/import":
                filename = query.get("filename", ["upload"])[0]
                suffix = Path(filename).suffix.lower()
                if suffix not in (".ncm", ".mp3", ".wav", ".flac", ".ogg", ".mid", ".midi"):
                    raise ValueError("支持 NCM、MP3、WAV、FLAC、OGG、MIDI。")
                if suffix not in (".mid", ".midi") and not self.server.engine.get("available"):
                    raise ValueError(self.server.engine["message"])
                data = self.body()
                if not IMPORT_LOCK.acquire(blocking=False):
                    return self.send(409, {"error": "正在生成一首练习，请等待当前任务完成。"})
                try:
                    job_id = uuid.uuid4().hex
                    directory = RUNTIME / job_id
                    directory.mkdir(parents=True)
                    upload = directory / ("input" + suffix)
                    upload.write_bytes(data)
                    options = {k: v[0] for k, v in query.items() if k in ("bpm", "tonic", "hand_size")}
                    with JOB_LOCK:
                        # Bounded in-memory task history; saved local projects remain on disk.
                        if len(JOBS) >= 32:
                            del JOBS[next(iter(JOBS))]
                        JOBS[job_id] = {"status": "queued", "message": "等待本地引擎…"}
                    threading.Thread(target=process_import, args=(job_id, upload, filename, options),
                                     daemon=True).start()
                except Exception:
                    IMPORT_LOCK.release()
                    raise
                return self.send(202, {"job_id": job_id})
            request = json.loads(self.body())
            if not isinstance(request, dict):
                raise ValueError("请求应为 JSON 对象。")
            if path == "/api/search-midi":
                query_text = str(request.get("query", "")).strip()
                if not 1 <= len(query_text) <= 120 or any(ord(c) < 32 for c in query_text):
                    raise ValueError("请输入 1–120 字的曲名。")
                if not IMPORT_LOCK.acquire(blocking=False):
                    return self.send(409, {"error": "正在生成另一首练习，请等待完成。"})
                try:
                    job_id = uuid.uuid4().hex
                    directory = RUNTIME / job_id
                    directory.mkdir(parents=True)
                    with JOB_LOCK:
                        if len(JOBS) >= 32:
                            del JOBS[next(iter(JOBS))]
                        JOBS[job_id] = {"status": "queued", "message": "准备搜索 MIDI…"}
                    threading.Thread(target=process_midi_search,
                                     args=(job_id, query_text, directory, request), daemon=True).start()
                except Exception:
                    IMPORT_LOCK.release()
                    raise
                return self.send(202, {"job_id": job_id})
            if path == "/api/rebuild":
                project = request["project"]
                return self.send(200, build_project(project.get("source_notes", project["notes"]), title=project.get("title", "练习"),
                    bpm=request.get("bpm", project.get("bpm", 100)),
                    tonic=request.get("tonic", project.get("tonic", -1)),
                    hand_size=request.get("hand_size", project.get("hand_size", "M")), source=project.get("source"),
                    transcription=project.get("transcription")))
            if path == "/api/export/midi":
                return self.send(200, write_midi(request), "audio/midi")
            if path == "/api/serial/connect":
                return self.send(200, LIGHTS.connect(request["port"], request.get("baud", 115200)))
            if path == "/api/serial/disconnect":
                return self.send(200, LIGHTS.disconnect())
            if path == "/api/serial/frame":
                return self.send(200, LIGHTS.frame(request))
            return self.send(404, {"error": "接口不存在。"})
        except Exception as exc:
            return self.send(400, {"error": str(exc)[:600]})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18766)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.engine = engine_status()
    print(f"钢琴灯光练习台：http://127.0.0.1:{args.port}", flush=True)
    print(server.engine["message"], flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        LIGHTS.disconnect()
        server.server_close()


if __name__ == "__main__":
    main()
