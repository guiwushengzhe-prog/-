"""下载固定版本的开源 NCM 转换库；不安装到系统目录。"""
from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile

VERSION = "1.5.1"
COMMIT = "76a55d862f767ee20ae417ecd128fde442eea77f"
URL = f"https://github.com/taurusxin/ncmdump/releases/download/{VERSION}/libncmdump-{VERSION}-windows-amd64.zip"
ZIP_SHA256 = "fecd4ef9e9baa6c48a6ada7a733b0df7633dccbbe0d6da457ba61304fae0477c"
DLL_SHA256 = "77ee6fb899cb118567a9908c6e018b1d696ba353de6ffd9e3f960fd367822865"
TARGET = Path(__file__).resolve().parents[1] / ".runtime" / "tools" / "ncmdump" / "libncmdump.dll"


def ensure_ncmdump():
    if os.name != "nt":
        raise ValueError("此转换组件用于64位 Windows。")
    if TARGET.is_file() and hashlib.sha256(TARGET.read_bytes()).hexdigest() == DLL_SHA256:
        return TARGET
    with urlopen(URL, timeout=45) as response:
        archive = response.read()
    if hashlib.sha256(archive).hexdigest() != ZIP_SHA256:
        raise ValueError("NCM 转换组件下载校验失败。")
    with ZipFile(io.BytesIO(archive)) as zipped:
        binary = zipped.read("libncmdump.dll")
    if hashlib.sha256(binary).hexdigest() != DLL_SHA256:
        raise ValueError("NCM 转换库校验失败。")
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    temporary = TARGET.with_suffix(".dll.partial")
    temporary.write_bytes(binary)
    temporary.replace(TARGET)
    return TARGET


if __name__ == "__main__":
    print(ensure_ncmdump())
