#!/usr/bin/env python3
"""Fetch the pinned official Transkun checkpoint without loading or running it."""
from __future__ import annotations

import hashlib
from http.client import HTTPException
from pathlib import Path
import sys
import tempfile
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

MODEL_URL = (
    "https://raw.githubusercontent.com/Yujia-Yan/Transkun/"
    "c5cb8370e17b4a1650b5971ba87ee4b0d208e5b6/transkun/pretrained/2.0.pt"
)
MODEL_SHA256 = "50a80010effc2a59ffcd068a95cd2b29bd7f23a27a3515bc3ccd209c89a3d44c"
MODEL_BYTES = 56_408_978
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
CHUNK_BYTES = 64 * 1024
DOWNLOAD_TIMEOUT = 30
MODEL_PATH = Path(__file__).resolve().parent / "vendor" / "transkun" / "pretrained" / "2.0.pt"


class ModelDownloadError(ValueError):
    """A failed download or integrity check; the previous model remains intact."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        # Only the fixed, versioned HTTPS endpoint is permitted.
        return None


def _open_download():
    request = Request(MODEL_URL, headers={"Accept-Encoding": "identity",
                                          "User-Agent": "PianoLightStudio-model-installer/1"})
    return build_opener(_NoRedirect).open(request, timeout=DOWNLOAD_TIMEOUT)


def _correct_cached_model(path):
    if not path.is_file() or path.stat().st_size != MODEL_BYTES:
        return False
    digest = hashlib.sha256()
    count = 0
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_BYTES):
            count += len(chunk)
            if count > MAX_DOWNLOAD_BYTES:
                return False
            digest.update(chunk)
    return count == MODEL_BYTES and digest.hexdigest() == MODEL_SHA256


def ensure_model(path=None):
    """Return a verified model path, replacing a stale file only after success."""
    target = MODEL_PATH if path is None else Path(path)
    if _correct_cached_model(target):
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with _open_download() as source:
            declared = source.headers.get("Content-Length")
            if declared is not None:
                try:
                    declared = int(declared)
                except (TypeError, ValueError) as exc:
                    raise ModelDownloadError("模型下载响应的长度无效。") from exc
                if declared < 0 or declared > MAX_DOWNLOAD_BYTES:
                    raise ModelDownloadError("模型下载超过 64 MiB 上限。")
                if declared != MODEL_BYTES:
                    raise ModelDownloadError("模型下载长度与固定版本不符。")
            digest = hashlib.sha256()
            count = 0
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".transkun-model-",
                                             suffix=".part", delete=False) as output:
                temporary = Path(output.name)
                while chunk := source.read(CHUNK_BYTES):
                    count += len(chunk)
                    if count > MAX_DOWNLOAD_BYTES:
                        raise ModelDownloadError("模型下载超过 64 MiB 上限。")
                    if count > MODEL_BYTES:
                        raise ModelDownloadError("模型下载长度与固定版本不符。")
                    digest.update(chunk)
                    output.write(chunk)
            if count != MODEL_BYTES or digest.hexdigest() != MODEL_SHA256:
                raise ModelDownloadError("模型下载未通过长度或 SHA256 校验，原模型已保留。")
        temporary.replace(target)
        return target
    except (OSError, URLError, TimeoutError, HTTPException) as exc:
        raise ModelDownloadError(f"模型下载失败，原模型已保留：{exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    try:
        path = ensure_model()
    except (ModelDownloadError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Transkun 模型已通过 SHA256 校验：{path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
