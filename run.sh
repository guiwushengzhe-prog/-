#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
PIANO_PYTHON="${PIANO_PYTHON:-.venv/bin/python}"
if [[ ! -x "$PIANO_PYTHON" ]]; then
  echo '请先运行 ./setup.sh 安装本地环境，或设置 PIANO_PYTHON 指向已安装依赖的 Python。' >&2
  exit 1
fi
exec "$PIANO_PYTHON" -m piano.server "$@"
