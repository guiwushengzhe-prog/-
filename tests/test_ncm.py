# NCM fixture builder adapted from Calvin-Vollerei/ncmdump-local tests/ncm_builder.py
# Upstream commit: 06c495d61e1347963fbef8d970033d5bc2f6bc0d
# Copyright (c) 2026 ncm2mp3 contributors; MIT License.
# Full license retained at piano/vendor/ncmdump_local/LICENSE.
# -*- coding: utf-8 -*-
"""Build synthetic (but byte-accurate) .ncm containers for the tests.

Why synthetic: the project must never ship real .ncm files, and they carry copyrighted
audio anyway. Building the container ourselves also pins the layout — if the parser and
this builder ever disagree, the round-trip tests fail, which is exactly the signal we want.

Layout, matching what the reference implementation reads (see ncm_core._parse_header):

    "CTENFDAM" | 2 pad | u32 key_len | key blob
    u32 meta_len | metadata blob
    "00 00 00 00" | 0x01 | u32 cover_frame_len | u32 image_len | cover bytes | audio
"""
from __future__ import annotations

from pathlib import Path
import sys
APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

import base64
import json
import struct

from piano.vendor.ncmdump_local.aes_lite import AES
from piano.vendor.ncmdump_local.ncm_core import CORE_KEY, META_KEY

# a fixed key-material blob; length only matters, not the value
KEYDATA = (b"104091397427940E7fT49x7dof9OKCgg9cdvhEuezy3iZCL1nFvBFd1T4uSktAJKmwZXsijPbijliion"
           b"VUXXg9plTbXEclAE9Lb")


def _aes_ecb_encrypt(key: bytes, data: bytes) -> bytes:
    """AES-128-ECB encryption with PKCS#7 padding.

    Only AES-128: that is all the container format needs (both the key blob and the
    metadata blob use a 16-byte key), and it keeps this helper small. Correctness is
    pinned by ``test_aes.py::test_builder_encryptor_matches_openssl`` against a vector
    produced by OpenSSL.
    """
    if len(key) != 16:
        raise ValueError("the fixture builder only implements AES-128")
    from piano.vendor.ncmdump_local.aes_lite import SBOX

    aes = AES(key)
    pad = 16 - (len(data) % 16)
    data = data + bytes([pad]) * pad
    out = bytearray()
    for offset in range(0, len(data), 16):
        out += _encrypt_block(aes, list(data[offset:offset + 16]), SBOX)
    return bytes(out)


def _encrypt_block(aes: AES, block: list, sbox: list) -> bytes:
    """Minimal AES-128 encrypt: the inverse of aes_lite's decryption."""
    rk = aes._round_keys
    state = [block[i] ^ rk[0][i] for i in range(16)]

    def shift_rows(s):
        return [s[0], s[5], s[10], s[15], s[4], s[9], s[14], s[3],
                s[8], s[13], s[2], s[7], s[12], s[1], s[6], s[11]]

    def mix_columns(s):
        def xt(a):
            return ((a << 1) ^ 0x1B) & 0xFF if a & 0x80 else (a << 1) & 0xFF

        out = [0] * 16
        for c in range(4):
            a0, a1, a2, a3 = s[4 * c:4 * c + 4]
            out[4 * c + 0] = xt(a0) ^ (xt(a1) ^ a1) ^ a2 ^ a3
            out[4 * c + 1] = a0 ^ xt(a1) ^ (xt(a2) ^ a2) ^ a3
            out[4 * c + 2] = a0 ^ a1 ^ xt(a2) ^ (xt(a3) ^ a3)
            out[4 * c + 3] = (xt(a0) ^ a0) ^ a1 ^ a2 ^ xt(a3)
        return out

    for rnd in range(1, aes.nr):
        state = [sbox[b] for b in state]
        state = shift_rows(state)
        state = mix_columns(state)
        state = [state[i] ^ rk[rnd][i] for i in range(16)]
    state = [sbox[b] for b in state]
    state = shift_rows(state)
    return bytes(state[i] ^ rk[aes.nr][i] for i in range(16))


def keystream(keydata: bytes, length: int) -> bytes:
    """Reproduce the player's keystream (RC4 KSA + the extra shuffle step)."""
    n = len(keydata)
    box = list(range(256))
    j = 0
    for i in range(256):
        j = (box[i] + j + keydata[i % n]) & 0xFF
        box[i], box[j] = box[j], box[i]
    shuffled = [0] * 256
    for t in range(256):
        t1 = (t + 1) & 0xFF
        i1 = box[t1]
        n1 = box[(t1 + i1) & 0xFF]
        shuffled[t] = box[(i1 + n1) & 0xFF]
    return bytes(shuffled[i % 256] for i in range(length))


def fake_flac(payload: bytes = b"audio-bytes-here") -> bytes:
    """A byte string that sniffs as FLAC AND is shaped like a real stream.

    Two details matter because the payload-length helper walks the metadata blocks:

    * the metadata region must be a properly terminated STREAMINFO block;
    * the audio must start with a real frame-sync word. A FLAC block header is
      ``<last-flag><type:7> <size:24>``, so a body beginning with 0xFF would look like a
      "last" block plus a huge length — the parser would then consume the audio as
      metadata. ``0xFF 0xF9`` is a valid 16-bit frame sync (fixed blocksize) and keeps the
      byte after it from being read as a block header.
    """
    streaminfo = bytes(34)                       # 34 bytes is the real STREAMINFO size
    block = bytes([0x80 | 0]) + len(streaminfo).to_bytes(3, "big") + streaminfo
    return b"fLaC" + block + b"\xff\xf9" + payload


def build(audio: bytes, title: str = "Test Song", artists=("Artist A",),
          album: str = "Album", cover: bytes = b"", keydata: bytes = KEYDATA,
          fmt: str = "flac", prefix: str = "music") -> bytes:
    """Assemble a complete container around `audio`."""
    key_plain = b"neteasecloudmusic" + keydata
    key_blob = _aes_ecb_encrypt(CORE_KEY, key_plain)
    key_enc = bytes(b ^ 0x64 for b in key_blob)

    meta = {
        "musicId": "1", "musicName": title,
        "artist": [[a, "1"] for a in artists],
        "albumId": "1", "album": album,
        "albumPic": "", "bitrate": 999000, "duration": 1000, "format": fmt,
    }
    payload = (prefix + ":").encode("ascii") + json.dumps(meta, ensure_ascii=False).encode("utf-8")
    meta_blob = b"163 key(Don't modify):" + base64.b64encode(_aes_ecb_encrypt(META_KEY, payload))
    meta_enc = bytes(b ^ 0x63 for b in meta_blob)

    ks = keystream(keydata, len(audio))
    audio_enc = bytes(a ^ b for a, b in zip(audio, ks))

    # 真实容器分别存储封面框长度和图片长度；没有封面时两个字段均为零。
    block = cover

    out = bytearray()
    out += b"CTENFDAM\x01\x70"
    out += struct.pack("<I", len(key_enc)) + key_enc
    out += struct.pack("<I", len(meta_enc)) + meta_enc
    out += b"\x00\x00\x00\x00" + b"\x01"
    out += struct.pack("<II", len(block), len(cover)) + block
    out += audio_enc
    return bytes(out)


def write(path, audio: bytes, **kwargs):
    data = build(audio, **kwargs)
    with open(path, "wb") as fh:
        fh.write(data)
    return str(path)


# These are synthesized NCM containers around our own test audio. They do not
# represent a successful test on an actual file downloaded from NetEase.
import io
import os
import subprocess
import tempfile
import unittest
from unittest import mock

import numpy as np
import soundfile as sf

from piano.ncm_convert import NcmConversionError, convert_ncm


class NcmConversionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.example = APP / "examples" / "automatic-transcription-test.mp3"
        cls.mp3 = cls.example.read_bytes()
        samples, sr = sf.read(io.BytesIO(cls.mp3), dtype="float32")
        stream = io.BytesIO()
        sf.write(stream, samples, sr, format="FLAC")
        cls.flac = stream.getvalue()
        assert sf.info(io.BytesIO(cls.flac)).format == "FLAC"

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="piano-ncm-test-")
        self.folder = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def fixture(self, payload=None, fmt="mp3", name="input.ncm"):
        source = self.folder / name
        source.write_bytes(build(self.mp3 if payload is None else payload, fmt=fmt,
                                 title="NCM test", artists=("Test Artist",), album="Local Fixture"))
        return source

    def test_mp3_is_restored_bit_exact_and_source_is_retained(self):
        source = self.fixture()
        before = source.read_bytes()
        target = self.folder / "converted.mp3"
        messages = []
        metadata = convert_ncm(source, target, messages.append)
        self.assertEqual(target.read_bytes(), self.mp3)
        self.assertEqual(source.read_bytes(), before)
        self.assertFalse(metadata["transcoded"])
        self.assertEqual(metadata["inner_format"], "mp3")
        self.assertEqual(metadata["title"], "NCM test")
        self.assertEqual(metadata["artists"], ["Test Artist"])
        self.assertEqual(metadata["album"], "Local Fixture")
        self.assertTrue(metadata["source_preserved"])
        self.assertEqual(sf.info(target).format, "MP3")
        self.assertGreater(len(messages), 1)
        self.assertEqual(list(self.folder.glob(".ncm-convert-*")), [])

    def test_real_decodable_flac_is_encoded_to_real_mp3(self):
        source = self.fixture(self.flac, fmt="flac")
        before = source.read_bytes()
        target = self.folder / "converted.mp3"
        metadata = convert_ncm(source, target)
        self.assertTrue(metadata["transcoded"])
        self.assertEqual(metadata["inner_format"], "flac")
        self.assertNotEqual(target.read_bytes(), self.flac)
        self.assertNotEqual(target.read_bytes()[:4], b"fLaC")
        self.assertEqual(sf.info(target).format, "MP3")
        self.assertAlmostEqual(sf.info(target).duration, 8.0, delta=.1)
        self.assertEqual(source.read_bytes(), before)

    def test_cover_length_fields_do_not_shift_audio(self):
        source = self.folder / "with-cover.ncm"
        source.write_bytes(build(self.mp3, fmt="mp3", cover=b"synthetic-cover"))
        before = source.read_bytes()
        target = self.folder / "with-cover.mp3"
        convert_ncm(source, target)
        self.assertEqual(target.read_bytes(), self.mp3)
        self.assertEqual(source.read_bytes(), before)

    def test_damaged_headers_lengths_and_empty_audio_do_not_publish(self):
        valid = build(self.mp3, fmt="mp3")
        key_length = struct.unpack("<I", valid[10:14])[0]
        meta_length_offset = 14 + key_length
        meta_length = struct.unpack("<I", valid[meta_length_offset:meta_length_offset + 4])[0]
        cover_length_offset = meta_length_offset + 4 + meta_length + 5
        invalid_key = bytearray(valid)
        invalid_key[10:14] = struct.pack("<I", 0xFFFFFFFF)
        invalid_meta = bytearray(valid)
        invalid_meta[meta_length_offset:meta_length_offset + 4] = struct.pack("<I", len(valid) + 1)
        invalid_cover = bytearray(valid)
        invalid_cover[cover_length_offset:cover_length_offset + 4] = struct.pack("<I", 0xFFFFFFFF)
        cases = {"bad_magic": b"not-ncm", "short_header": b"CTENFDAM\x01\x70",
                 "bad_key_length": invalid_key, "bad_meta_length": invalid_meta,
                 "bad_cover_length": invalid_cover, "empty_audio": build(b"", fmt="mp3"),
                 "undecodable_audio": build(b"ID3" + bytes(100), fmt="mp3")}
        for label, contents in cases.items():
            with self.subTest(label=label):
                source = self.folder / f"{label}.ncm"
                source.write_bytes(contents)
                target = self.folder / f"{label}.mp3"
                with self.assertRaises(NcmConversionError):
                    convert_ncm(source, target)
                self.assertFalse(target.exists())
                self.assertEqual(source.read_bytes(), bytes(contents))
        self.assertEqual(list(self.folder.glob(".ncm-convert-*")), [])

    def test_transcode_timeout_does_not_publish_or_delete_source(self):
        source = self.fixture(self.flac, fmt="flac")
        target = self.folder / "timeout.mp3"
        original_run = subprocess.run
        def timeout_encoder(command, *args, **kwargs):
            if "-codec:a" in command:
                raise subprocess.TimeoutExpired("ffmpeg", 120)
            return original_run(command, *args, **kwargs)
        with mock.patch("piano.ncm_convert.subprocess.run", side_effect=timeout_encoder):
            with self.assertRaisesRegex(NcmConversionError, "120"):
                convert_ncm(source, target)
        self.assertFalse(target.exists())
        self.assertTrue(source.exists())
        self.assertEqual(list(self.folder.glob(".ncm-convert-*")), [])

    def test_inner_audio_over_600_seconds_is_rejected(self):
        stream = io.BytesIO()
        sf.write(stream, np.zeros(601 * 8000, dtype=np.float32), 8000, format="FLAC")
        source = self.fixture(stream.getvalue(), fmt="flac")
        target = self.folder / "too-long.mp3"
        with self.assertRaisesRegex(NcmConversionError, "600"):
            convert_ncm(source, target)
        self.assertFalse(target.exists())
        self.assertTrue(source.exists())

    def test_ncm_worker_transcribes_our_eight_notes_automatically(self):
        source = self.fixture()
        before = source.read_bytes()
        output = self.folder / "notes.json"
        worker = APP / "piano" / "transcribe_worker.py"
        completed = subprocess.run([sys.executable, str(worker), str(source), str(output)],
                                   cwd=self.folder, capture_output=True, text=True, encoding="utf-8", timeout=90,
                                   env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        progress_rows = [json.loads(line) for line in completed.stdout.splitlines()]
        self.assertTrue(any(row.get("stage") == "convert" for row in progress_rows))
        result = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(len(result["notes"]), 8)
        self.assertCountEqual([n["pitch"] for n in result["notes"]], [60, 62, 64, 67, 72, 60, 64, 67])
        for pitch, onset in [(60, .35), (62, 1.35), (64, 2.35), (67, 3.35), (72, 4.35),
                             (60, 5.5), (64, 5.5), (67, 5.5)]:
            self.assertTrue(any(n["pitch"] == pitch and abs(n["start"] - onset) < .15
                                for n in result["notes"]))
        self.assertEqual(result["metadata"]["source_name"], "input.ncm")
        self.assertEqual(result["metadata"]["conversion"]["inner_format"], "mp3")
        self.assertTrue(result["metadata"]["conversion"]["source_preserved"])
        self.assertEqual((self.folder / "converted.mp3").read_bytes(), self.mp3)
        self.assertEqual(source.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
