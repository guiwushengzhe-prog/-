#!/usr/bin/env python3
"""Bounded local audio transcription using Spotify Basic Pitch's ONNX model.

Usage: python transcribe_worker.py INPUT OUTPUT_JSON [--max-duration 600]
Stdout is a JSON-lines progress stream. Library diagnostics go to stderr.
No network requests or paid services are used during transcription.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time

# The HTTP service invokes this file directly with an isolated Python interpreter.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Keep this worker usable on a small CPU-only VM. Set before importing libraries.
for _key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS"):
    os.environ[_key] = "2"

_PROGRESS_STREAM = sys.stdout
SUPPORTED_SUFFIXES = {".mp3", ".wav", ".flac", ".ogg", ".ncm"}
MAX_DECODED_MONO_BYTES = 128 * 1024 * 1024


class TranscriptionError(ValueError):
    """An input or runtime error that can be shown to a user."""


def progress(message: str, **fields: object) -> None:
    print(json.dumps({"message": message, **fields}, ensure_ascii=False, allow_nan=False),
          file=_PROGRESS_STREAM, flush=True)


def transcribe(input_path: Path, output_path: Path, max_duration: float = 600.0) -> dict:
    started = time.perf_counter()
    if not math.isfinite(max_duration) or not 0 < max_duration <= 3600:
        raise TranscriptionError("最长时长必须是大于 0、且不超过 3600 的有限秒数。")
    if not input_path.is_file():
        raise TranscriptionError("找不到输入音频文件。")
    if input_path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise TranscriptionError("支持 MP3、WAV、FLAC、OGG、NCM 音频文件。")
    if input_path.resolve() == output_path.resolve():
        raise TranscriptionError("输出 JSON 不能覆盖输入音频。")

    original_input = input_path
    conversion = None
    if input_path.suffix.lower() == ".ncm":
        from piano.ncm_convert import convert_ncm

        converted_path = input_path.parent / "converted.mp3"
        if converted_path.resolve() == output_path.resolve():
            raise TranscriptionError("输出 JSON 不能覆盖转换后的 MP3。")
        conversion = convert_ncm(input_path, converted_path,
                                 progress=lambda message: progress(message, stage="convert"))
        input_path = converted_path

    progress("正在检查音频格式和时长", stage="inspect")
    import numpy as np
    import soundfile as sf
    import soxr

    try:
        info = sf.info(str(input_path))
    except (RuntimeError, OSError) as exc:
        raise TranscriptionError("音频无法解码；请确认文件内容有效，而不只是修改了扩展名。") from exc
    if info.samplerate <= 0 or info.channels <= 0 or info.frames <= 0:
        raise TranscriptionError("音频为空或时长信息无效。")
    if info.channels > 8 or not 8000 <= info.samplerate <= 192000:
        raise TranscriptionError("请使用最多 8 声道、采样率 8–192 kHz 的音频。")
    declared_duration = info.frames / info.samplerate
    if declared_duration > max_duration + 1e-6:
        raise TranscriptionError(
            f"音频时长 {declared_duration:.2f} 秒，超过本次处理上限 {max_duration:g} 秒。")

    # Independently bound the decoded frame count; never silently truncate a song.
    max_frames = math.floor(max_duration * info.samplerate)
    try:
        with sf.SoundFile(str(input_path)) as audio_file:
            # Mix and continuously resample each block, bounding high-rate/multichannel memory.
            blocks = []
            decoded_frames = 0
            normalized_frames = 0
            resampler = (soxr.ResampleStream(info.samplerate, 22050, 1, dtype="float32", quality="HQ")
                         if info.samplerate != 22050 else None)
            while True:
                block = audio_file.read(min(65536, max_frames + 1 - decoded_frames),
                                        dtype="float32", always_2d=True)
                if len(block) == 0:
                    break
                decoded_frames += len(block)
                if decoded_frames > max_frames:
                    raise TranscriptionError(f"解码后音频超过上限 {max_duration:g} 秒；已停止处理。")
                mono = block.mean(axis=1, dtype=np.float32)
                if not np.isfinite(mono).all():
                    raise TranscriptionError("音频含无效采样值，无法转谱。")
                normalized = resampler.resample_chunk(mono) if resampler else mono
                normalized_frames += len(normalized)
                if normalized_frames * 4 > MAX_DECODED_MONO_BYTES:
                    raise TranscriptionError("音频解码超过 128 MiB 内存预算，已停止处理。")
                if len(normalized):
                    blocks.append(normalized)
            if resampler:
                tail = resampler.resample_chunk(np.empty(0, dtype=np.float32), last=True)
                normalized_frames += len(tail)
                if normalized_frames * 4 > MAX_DECODED_MONO_BYTES:
                    raise TranscriptionError("音频解码超过 128 MiB 内存预算，已停止处理。")
                if len(tail):
                    blocks.append(tail)
    except (RuntimeError, OSError) as exc:
        raise TranscriptionError("音频解码失败，文件可能已损坏。") from exc
    if not blocks:
        raise TranscriptionError("音频没有可读取的采样。")
    audio = np.concatenate(blocks)
    del blocks
    if not np.isfinite(audio).all():
        raise TranscriptionError("音频含无效采样值，无法转谱。")
    duration = decoded_frames / info.samplerate

    progress("正在加载本地音符识别模型", stage="model", duration=round(duration, 4))
    import librosa
    import onnxruntime as ort
    from basic_pitch import FilenameSuffix, build_icassp_2022_model_path
    from basic_pitch.inference import Model, predict

    model_path = build_icassp_2022_model_path(FilenameSuffix.onnx)
    if not model_path.is_file():
        raise TranscriptionError("缺少 Basic Pitch 官方 ONNX 模型，请重新安装 basic-pitch==0.4.0。")
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    options.log_severity_level = 3
    # Reuse the upstream Model.predict adapter while explicitly pinning CPU and thread limits.
    model = Model.__new__(Model)
    model.model_type = Model.MODEL_TYPES.ONNX
    model.model = ort.InferenceSession(str(model_path), sess_options=options,
                                       providers=["CPUExecutionProvider"])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    bpm = 100.0
    bpm_source = "fallback-default"
    with tempfile.TemporaryDirectory(prefix="piano-transcribe-") as temporary:
        normalized_path = Path(temporary) / "input.wav"
        sf.write(str(normalized_path), audio, 22050, subtype="FLOAT")
        progress("正在估计节拍速度", stage="tempo")
        try:
            if duration >= 5:
                tempo, beats = librosa.beat.beat_track(y=audio, sr=22050, hop_length=512)
                candidate = float(np.asarray(tempo).reshape(-1)[0])
                if len(beats) >= 4 and math.isfinite(candidate) and 40 <= candidate <= 240:
                    bpm, bpm_source = candidate, "librosa-beat-track"
        except (ValueError, RuntimeError):
            pass
        del audio
        progress("正在自动识别音符和起止时间", stage="transcribe")
        inference_started = time.perf_counter()
        _, _, events = predict(
            normalized_path, model, minimum_frequency=27.5,
            maximum_frequency=4186.009044809578, multiple_pitch_bends=False)
        inference_seconds = time.perf_counter() - inference_started

    notes = []
    for start, end, pitch, amplitude, _ in events:
        start = max(0.0, float(start))
        end = min(duration, float(end))
        if not 21 <= int(pitch) <= 108 or end <= start:
            continue
        notes.append({"pitch": int(pitch), "start": round(start, 5), "end": round(end, 5),
                      "velocity": max(1, min(127, int(round(float(amplitude) * 127))))})
    notes.sort(key=lambda note: (note["start"], note["pitch"], note["end"]))
    result = {
        "notes": notes,
        "engine": "spotify-basic-pitch-0.4.0-onnx-cpu",
        "bpm": round(bpm, 3),
        "metadata": {
            "source_name": original_input.name,
            "duration": round(duration, 5),
            "source_sample_rate": info.samplerate,
            "source_channels": info.channels,
            "source_format": info.format,
            "decoded_sample_rate": 22050,
            "decoded_mono_memory_limit_mib": MAX_DECODED_MONO_BYTES // (1024 * 1024),
            "max_duration": max_duration,
            "note_count": len(notes),
            "inference_seconds": round(inference_seconds, 3),
            "total_seconds": round(time.perf_counter() - started, 3),
            "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
            "model_license": "Apache-2.0; bundled in spotify/basic-pitch distribution",
            "onnxruntime_version": importlib.metadata.version("onnxruntime"),
            "bpm": round(bpm, 3),
            "bpm_estimated": True,
            "bpm_source": bpm_source,
            "warnings": ["自动转谱可能有漏音和误音；独奏钢琴比混合人声、鼓和多种乐器更适合此模型。"],
        },
    }
    if conversion is not None:
        result["metadata"]["conversion"] = conversion
    if not notes:
        result["metadata"]["warnings"].append("未识别到有效钢琴音符；可换用更清晰、音量合适的独奏片段。")
    # Atomic publication prevents the HTTP service from seeing an incomplete result.
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output_path.parent,
                                         prefix=".transcription-", suffix=".json", delete=False) as handle:
            temporary_name = handle.name
            json.dump(result, handle, ensure_ascii=True, allow_nan=False)
        os.replace(temporary_name, output_path)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)
    progress(f"识别完成，共 {len(notes)} 个音符", stage="complete", note_count=len(notes))
    return result


def check_engine() -> dict:
    """Check dependencies and bundled model without running any inference."""
    try:
        for module in ("numpy", "soundfile", "soxr", "librosa", "onnxruntime", "pretty_midi", "mir_eval",
                       "imageio_ffmpeg"):
            __import__(module)
        import imageio_ffmpeg
        if not Path(imageio_ffmpeg.get_ffmpeg_exe()).is_file():
            raise RuntimeError("缺少本地 FFmpeg，无法转换 NCM 内层音频")
        package = importlib.util.find_spec("basic_pitch")
        if package is None or package.origin is None:
            raise ImportError("缺少 basic-pitch==0.4.0")
        model = Path(package.origin).parent / "saved_models" / "icassp_2022" / "nmp.onnx"
        if not model.is_file() or model.stat().st_size < 100000:
            raise RuntimeError("缺少官方 ONNX 音符模型")
        return {"available": True, "message": "本地自动转谱引擎已就绪（Basic Pitch / ONNX CPU）",
                "engine": "spotify-basic-pitch-0.4.0-onnx-cpu"}
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        return {"available": False, "message": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, nargs="?")
    parser.add_argument("output_json", type=Path, nargs="?")
    parser.add_argument("--check", action="store_true", help="check dependencies/model; do not infer")
    parser.add_argument("--max-duration", type=float, default=600.0)
    args = parser.parse_args()
    if args.check:
        with contextlib.redirect_stdout(sys.stderr):
            result = check_engine()
        print(json.dumps(result, ensure_ascii=False), file=_PROGRESS_STREAM, flush=True)
        return 0 if result["available"] else 2
    if args.input is None or args.output_json is None:
        parser.error("INPUT and OUTPUT_JSON are required unless --check is used")
    try:
        # Upstream prints descriptive status to stdout; keep this CLI machine-readable.
        with contextlib.redirect_stdout(sys.stderr):
            transcribe(args.input, args.output_json, args.max_duration)
    except (TranscriptionError, ImportError, OSError, RuntimeError, ValueError) as exc:
        progress(str(exc), stage="error", error=str(exc))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
