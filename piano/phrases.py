"""Cached, isolated adapter to the pinned loop-miner project."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading

REVISION = "3b167aafee09872c80f6ced9b01cdfdba59b476f"
SSMS_REVISION = "bdabe679a9a5a5900dba56666b535af734e646b7"
ADAPTER_VERSION = 2
ANALYSIS_LOCK = threading.Lock()


def original_project(project):
    return project.get("key_adaptation", {}).get("original_project") or project


def analyse(project, runtime):
    from .music import read_midi, validate_notes
    project = original_project(project)
    notes = validate_notes(project.get("source_notes") or project["notes"])
    transcription = dict(project.get("transcription") or {})
    # Recover meter for older library files that predate time-signature metadata.
    if not transcription.get("time_signature_map"):
        for saved in runtime.glob("*/project.json"):
            try:
                data = saved.read_bytes()
                try:
                    stored = json.loads(data.decode("utf-8-sig"))
                except UnicodeDecodeError:
                    stored = json.loads(data.decode("gb18030"))
                if stored.get("source") != project.get("source"):
                    continue
                for midi_path in sorted(saved.parent.glob("*.mid*")):
                    _, _, metadata = read_midi(midi_path.read_bytes())
                    transcription["time_signature_map"] = metadata["time_signature_map"]
                    break
                if transcription.get("time_signature_map"):
                    break
            except (OSError, ValueError, KeyError):
                continue
    payload = {"notes": notes, "bpm": project.get("bpm", 90),
               "duration": project["duration"], "groups": project["groups"],
               "tempo_map": transcription.get("tempo_map", []),
               "time_signature_map": transcription.get("time_signature_map", []),
               "adapter_version": ADAPTER_VERSION, "revision": REVISION}
    if payload["time_signature_map"] and payload["time_signature_map"][0]["beat"] > 0:
        payload["time_signature_map"].insert(0, {"time": 0, "beat": 0, "numerator": 4, "denominator": 4})
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    key = hashlib.sha256(encoded).hexdigest()
    cache = runtime / "phrase-cache"
    cache.mkdir(parents=True, exist_ok=True)
    result_path = cache / f"{key}.json"
    with ANALYSIS_LOCK:
        if result_path.exists():
            result = json.loads(result_path.read_text(encoding="utf-8"))
            return {**result, "cached": True}
        source_path = cache / f"{key}.input.json"
        source_path.write_bytes(encoded)
        process = subprocess.run(
            [sys.executable, "-m", "piano.phrase_worker", str(source_path), str(result_path), str(runtime)],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=180)
        if process.returncode or not result_path.exists():
            lines = process.stdout.decode("utf-8", errors="replace").splitlines()
            errors = [line for line in lines if line.startswith('{"error":')]
            if errors:
                raise ValueError(json.loads(errors[-1])["error"])
            raise ValueError("自动分段引擎运行失败，请检查本地引擎安装。")
        return {**json.loads(result_path.read_text(encoding="utf-8")), "cached": False}
