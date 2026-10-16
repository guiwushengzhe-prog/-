#!/usr/bin/env bash
# Local-only setup. System Python and system packages are never changed.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ! -x .venv/bin/python ]]; then
  if command -v python3.11 >/dev/null 2>&1; then
    PIANO_SETUP_PYTHON="$(command -v python3.11)"
  elif [[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]]; then
    mkdir -p .runtime/tools
    PIANO_ARCHIVE=.runtime/tools/python311.tar.gz
    if [[ ! -x .runtime/tools/python/bin/python3.11 ]]; then
      curl -fL --retry 2 'https://github.com/astral-sh/python-build-standalone/releases/download/20251014/cpython-3.11.14%2B20251014-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz' -o "$PIANO_ARCHIVE"
      printf '%s  %s\n' '91ab434738647ab45d630aaa02e3808bb516239beeb52f7799c12a12d1557a38' "$PIANO_ARCHIVE" | sha256sum --check --status
      tar -xzf "$PIANO_ARCHIVE" -C .runtime/tools
    fi
    PIANO_SETUP_PYTHON="$PWD/.runtime/tools/python/bin/python3.11"
  else
    echo '请先安装 Python 3.11，再运行 setup.sh。Windows 请使用 README 中的 Python 命令。' >&2
    exit 1
  fi
  "$PIANO_SETUP_PYTHON" -m venv .venv
fi
.venv/bin/python -m pip install -r requirements-runtime.lock
.venv/bin/python -m pip install --no-deps --require-hashes -r requirements-basic-pitch.lock
.venv/bin/python -m pip install --index-url https://download.pytorch.org/whl/cpu -r requirements-piano.txt
.venv/bin/python piano/download_model.py
.venv/bin/python piano/piano_worker.py --check
echo '安装完成。运行 ./run.sh，然后打开 http://127.0.0.1:18766 。'
