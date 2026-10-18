#!/usr/bin/env python3
"""Bounded local high-quality solo-piano transcription with MIT Transkun V2."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS"):
    os.environ[name] = "2"

STREAM = sys.stdout
MODEL_DIR = Path(__file__).resolve().parent / "vendor" / "transkun" / "pretrained"
MODEL_SHA = "50a80010effc2a59ffcd068a95cd2b29bd7f23a27a3515bc3ccd209c89a3d44c"
CONFIG_SHA = "d3d989214eb148230ee5df476d994dcde6af595904d3f968f1221d2e3bea5ac6"


def progress(message, **fields):
    print(json.dumps({"message": message, **fields}, ensure_ascii=False, allow_nan=False), file=STREAM, flush=True)


def digest(path):
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def check_engine():
    try:
        import numpy, soundfile, soxr, torch, torchaudio, pretty_midi, mir_eval, imageio_ffmpeg
        if digest(MODEL_DIR / "2.0.pt") != MODEL_SHA or digest(MODEL_DIR / "2.0.conf") != CONFIG_SHA:
            raise ValueError("钢琴专用模型或配置校验失败。")
        return {"available": True, "engine": "transkun-v2-no-pedal-extension-cpu",
                "message": "钢琴专用转谱已就绪（Transkun V2，本地 CPU）"}
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        return {"available": False, "message": f"钢琴专用引擎未就绪：{exc}。请运行 setup.sh。"}


def decode_audio(path, max_duration):
    import numpy as np
    import soundfile as sf
    import soxr
    try:
        info = sf.info(str(path))
        if not 1 <= info.channels <= 8 or not 8000 <= info.samplerate <= 192000 or info.frames <= 0:
            raise ValueError("音频声道、采样率或时长无效。")
        duration = info.frames / info.samplerate
        if duration > max_duration + 1e-6:
            raise ValueError(f"音频超过 {max_duration:g} 秒上限。")
        max_frames = math.floor(max_duration * info.samplerate)
        frames = 0
        channels = min(2, info.channels)
        resampler = soxr.ResampleStream(info.samplerate, 44100, channels, dtype="float32", quality="HQ") if info.samplerate != 44100 else None
        blocks = []
        normalized = 0
        with sf.SoundFile(str(path)) as source:
            while True:
                block = source.read(min(65536, max_frames + 1 - frames), dtype="float32", always_2d=True)
                if not len(block):
                    break
                frames += len(block)
                if frames > max_frames or not np.isfinite(block).all():
                    raise ValueError("解码后音频超过上限或含无效采样。")
                if info.channels > 2:
                    block = block.mean(axis=1, dtype=np.float32)[:, None]
                    if channels == 2:
                        block = np.repeat(block, 2, axis=1)
                if resampler:
                    block = resampler.resample_chunk(block, last=False)
                blocks.append(block)
                normalized += block.nbytes
                if normalized > 256 * 1024 * 1024:
                    raise ValueError("音频解码超过 256 MiB 内存上限。")
            if resampler:
                blocks.append(resampler.resample_chunk(np.empty((0, channels), dtype=np.float32), last=True))
        if not blocks:
            raise ValueError("没有可读取的音频采样。")
        return np.concatenate(blocks, axis=0), info
    except (RuntimeError, OSError) as exc:
        raise ValueError("音频无法解码，文件可能已损坏。") from exc


def transcribe(path, output, max_duration=600):
    start = time.monotonic()
    if not 0 < max_duration <= 600:
        raise ValueError("当前最多处理 600 秒。")
    if path.suffix.lower() not in (".ncm", ".mp3", ".wav", ".flac", ".ogg"):
        raise ValueError("支持 NCM、MP3、WAV、FLAC、OGG。")
    if path.resolve() == output.resolve():
        raise ValueError("输出不能覆盖输入。")
    original = path
    conversion = None
    if path.suffix.lower() == ".ncm":
        from piano.ncm_convert import convert_ncm
        converted = path.parent / "converted.mp3"
        conversion = convert_ncm(path, converted, progress=lambda message: progress(message, stage="convert"))
        path = converted
    progress("读取音频，准备钢琴专用转谱…", stage="decode")
    audio, info = decode_audio(path, max_duration)
    import numpy as np
    import torch
    from piano.vendor.transkun.ModelTransformer import Config, TransKun
    torch.set_num_threads(2)
    torch.set_num_interop_threads(2)
    torch.set_grad_enabled(False)
    if digest(MODEL_DIR / "2.0.pt") != MODEL_SHA or digest(MODEL_DIR / "2.0.conf") != CONFIG_SHA:
        raise ValueError("模型或配置文件校验失败。")
    settings = json.loads((MODEL_DIR / "2.0.conf").read_text())["Model"]["config"]
    configuration = Config()
    for key, value in settings.items():
        setattr(configuration, key, value)
    progress("加载 Transkun 钢琴专用模型…", stage="model")
    model = TransKun(conf=configuration).to("cpu")
    checkpoint = torch.load(MODEL_DIR / "2.0.pt", map_location="cpu", weights_only=True)
    weights = checkpoint.get("best_state_dict", checkpoint.get("state_dict"))
    model.load_state_dict(weights, strict=True)
    model.eval()
    del weights, checkpoint
    count = 0
    expected = max(1, math.ceil((len(audio) / 44100 + 16) / 8))
    original_frames = model.transcribeFrames
    def tracked(*args, **kwargs):
        nonlocal count
        count += 1
        progress(f"钢琴专用模型正在处理第 {count}/{expected} 段…", stage="transcribe", segment=count, segments=expected)
        return original_frames(*args, **kwargs)
    model.transcribeFrames = tracked
    inference_start = time.monotonic()
    with torch.no_grad():
        events = model.transcribe(torch.from_numpy(audio), stepInSecond=None, segmentSizeInSecond=None, discardSecondHalf=False)
    inference_seconds = time.monotonic() - inference_start
    notes = []
    for note in events:
        if 21 <= note.pitch <= 108 and math.isfinite(note.start) and math.isfinite(note.end) and note.end > note.start:
            notes.append({"pitch": int(note.pitch), "start": float(note.start), "end": float(note.end), "velocity": max(1, min(127, int(note.velocity)))})
    notes.sort(key=lambda n: (n["start"], n["pitch"], n["end"]))
    if not notes:
        raise ValueError("未识别到钢琴音符。")
    bpm, bpm_source = 100., "fallback-default"
    try:
        import librosa
        mono = audio.mean(axis=1, dtype=np.float32)
        mono = librosa.resample(mono, orig_sr=44100, target_sr=22050)
        tempo, beats = librosa.beat.beat_track(y=mono, sr=22050)
        estimated = float(np.asarray(tempo).reshape(-1)[0])
        if len(beats) >= 4 and math.isfinite(estimated) and 40 <= estimated <= 240:
            bpm, bpm_source = estimated, "librosa-beat-track"
    except (ImportError, ValueError, RuntimeError):
        pass
    result = {"notes": notes, "bpm": round(bpm, 3), "engine": "transkun-v2-no-pedal-extension-cpu",
              "metadata": {"source_name": original.name, "note_count": len(notes), "duration": len(audio)/44100,
                           "source_sample_rate": info.samplerate, "source_channels": info.channels,
                           "model_sha256": MODEL_SHA, "model_license": "MIT",
                           "source": "https://github.com/Yujia-Yan/Transkun", "revision": "c5cb8370e17b4a1650b5971ba87ee4b0d208e5b6",
                           "inference_seconds": round(inference_seconds, 3), "total_seconds": round(time.monotonic()-start, 3),
                           "bpm_estimated": True, "bpm_source": bpm_source,
                           "warnings": ["钢琴专用转谱的实测结果不代表所有录音；混合人声和多种乐器仍可能产生错误。"]}}
    if conversion:
        result["metadata"]["conversion"] = conversion
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent, suffix=".json", delete=False) as temp:
        json.dump(result, temp, ensure_ascii=True, allow_nan=False)
        temporary_name = temp.name
    os.replace(temporary_name, output)
    progress(f"钢琴转谱完成，共 {len(notes)} 个音符", stage="complete")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, nargs="?")
    parser.add_argument("output", type=Path, nargs="?")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--max-duration", type=float, default=600)
    args = parser.parse_args()
    try:
        with contextlib.redirect_stdout(sys.stderr):
            if args.check:
                result = check_engine()
                print(json.dumps(result, ensure_ascii=False), file=STREAM, flush=True)
                return 0 if result["available"] else 2
            if args.input is None or args.output is None:
                raise ValueError("需要输入文件和输出 JSON 路径。")
            transcribe(args.input, args.output, args.max_duration)
    except Exception as exc:
        progress(str(exc), stage="error", error=str(exc))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
