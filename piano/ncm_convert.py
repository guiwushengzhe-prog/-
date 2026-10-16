"""Local, source-preserving NCM conversion using the vendored MIT core."""
from __future__ import annotations

import os
from pathlib import Path
import struct
import subprocess
import tempfile
from typing import Callable

from .vendor.ncmdump_local import NcmError, decrypt_to_file

MAX_DURATION = 600.0
UPSTREAM_COMMIT = "06c495d61e1347963fbef8d970033d5bc2f6bc0d"


class NcmConversionError(ValueError):
    """A damaged, unsupported, or unconvertible local NCM file."""


def _validate_container_lengths(source: Path) -> None:
    """Reject damaged length fields before the upstream AES parser reads blocks."""
    size = source.stat().st_size
    with source.open("rb") as handle:
        if handle.read(8) != b"CTENFDAM" or len(handle.read(2)) != 2:
            raise NcmConversionError("NCM 文件头无效或不完整。")
        for label, limit, encrypted in (("密钥", 64 * 1024, True),
                                         ("元数据", 4 * 1024 * 1024, False)):
            raw_length = handle.read(4)
            if len(raw_length) != 4:
                raise NcmConversionError(f"NCM {label}长度字段缺失。")
            length = struct.unpack("<I", raw_length)[0]
            if (length > limit or length > size - handle.tell()
                    or (encrypted and (length == 0 or length % 16 != 0))):
                raise NcmConversionError(f"NCM {label}长度异常或数据不完整。")
            handle.seek(length, os.SEEK_CUR)
        trailer = handle.read(9)
        if len(trailer) != 9:
            raise NcmConversionError("NCM 封面长度字段缺失，容器已损坏。")
        cover_length = struct.unpack("<I", trailer[5:9])[0]
        audio_offset = handle.tell() + max(cover_length, 4)
        if audio_offset > size:
            raise NcmConversionError("NCM 封面长度异常，音频区不完整。")
        if audio_offset == size:
            raise NcmConversionError("NCM 音频区为空。")


def _audio_info(path: Path, label: str):
    import soundfile as sf

    try:
        info = sf.info(str(path))
        if info.frames <= 0 or info.samplerate <= 0 or info.channels <= 0:
            raise NcmConversionError(f"{label}没有有效的音频采样。")
        if info.frames / info.samplerate > MAX_DURATION + 1e-6:
            raise NcmConversionError(f"{label}超过 {MAX_DURATION:g} 秒处理上限。")
        # Opening a plausible header is insufficient: require actual decoder output.
        with sf.SoundFile(str(path)) as audio:
            if len(audio.buffer_read(4096, dtype="int16")) == 0:
                raise NcmConversionError(f"{label}音频为空或无法解码。")
        return info
    except (RuntimeError, OSError) as exc:
        raise NcmConversionError(f"{label}无法解码，文件可能已损坏或内层格式不受支持。") from exc


def convert_ncm(source, output_mp3, progress: Callable[[str], None] | None = None) -> dict:
    """Stream a local NCM to a validated MP3, retaining the original file always.

    An MP3 payload is restored bit for bit. Other decodable audio is really encoded
    with libmp3lame; its extension is never merely renamed to .mp3. Only a successful,
    checked output is atomically published. No account, download, or network is used.
    """
    source, output_mp3 = Path(source), Path(output_mp3)
    emit = progress or (lambda _message: None)
    if not source.is_file():
        raise NcmConversionError("找不到本地 NCM 文件。")
    if source.resolve() == output_mp3.resolve():
        raise NcmConversionError("转换输出不能覆盖原始 NCM 文件。")
    if output_mp3.suffix.lower() != ".mp3":
        raise NcmConversionError("NCM 转换输出必须使用 .mp3 扩展名。")
    _validate_container_lengths(source)
    output_mp3.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=".ncm-convert-", dir=output_mp3.parent) as temporary:
        temporary = Path(temporary)
        raw_audio = temporary / "raw_audio.bin"
        emit("正在本地解密 NCM 容器")
        try:
            result = decrypt_to_file(str(source), str(raw_audio), chunk_size=1 << 20)
        except (NcmError, ValueError, OSError, struct.error) as exc:
            raise NcmConversionError(f"NCM 容器解密失败：{exc}") from exc
        if result.truncated:
            raise NcmConversionError("NCM 容器头或元数据已损坏，未生成转换结果。")
        info = _audio_info(raw_audio, "NCM 内层音频")
        actual_format = info.format.upper()
        inner_format = {"MP3": "mp3", "MPEG": "mp3", "WAVEX": "wav", "RF64": "wav"}.get(
            actual_format, actual_format.lower())
        renamed_raw = temporary / f"raw_audio.{inner_format}"
        raw_audio.rename(renamed_raw)
        candidate = temporary / "converted.mp3"
        transcoded = inner_format != "mp3"
        if not transcoded:
            emit("已恢复原始 MP3 音频，保留全部音频字节")
            renamed_raw.rename(candidate)
        else:
            import imageio_ffmpeg

            emit(f"正在把 {inner_format.upper()} 音频实际编码为 MP3")
            command = [imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-hide_banner", "-loglevel", "error",
                       "-xerror", "-protocol_whitelist", "file,pipe", "-i", str(renamed_raw),
                       "-map", "0:a:0", "-vn", "-map_metadata", "-1", "-codec:a", "libmp3lame",
                       "-q:a", "2", "-ac", str(min(2, info.channels)), "-threads", "2", "-y", str(candidate)]
            try:
                encoded = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
            except subprocess.TimeoutExpired as exc:
                raise NcmConversionError("NCM 音频转为 MP3 超时（120 秒），已停止处理。") from exc
            except OSError as exc:
                raise NcmConversionError("无法运行本地 FFmpeg，请检查 imageio-ffmpeg 安装。") from exc
            if encoded.returncode != 0:
                detail = (encoded.stderr or "编码器未返回详细信息").strip()[-1000:]
                raise NcmConversionError(f"NCM 内层音频编码 MP3 失败：{detail}")
        converted_info = _audio_info(candidate, "转换后的 MP3")
        if converted_info.format.upper() not in {"MP3", "MPEG"}:
            raise NcmConversionError("转换器没有生成真正的 MP3，已拒绝输出。")
        metadata = {
            "engine": "ncmdump-local+ffmpeg" if transcoded else "ncmdump-local",
            "upstream_commit": UPSTREAM_COMMIT,
            "license": "MIT",
            "inner_format": inner_format,
            "inner_sample_rate": info.samplerate,
            "inner_channels": info.channels,
            "output_format": "mp3",
            "output_sample_rate": converted_info.samplerate,
            "output_channels": converted_info.channels,
            "transcoded": transcoded,
            "source_preserved": True,
            "inner_audio_bytes": result.audio_len,
            "output_bytes": candidate.stat().st_size,
            "duration": round(converted_info.frames / converted_info.samplerate, 5),
            "title": result.meta.title,
            "artists": result.meta.artists,
            "album": result.meta.album,
        }
        os.replace(candidate, output_mp3)
    emit("NCM 转换完成，原始文件已保留")
    return metadata
