#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
teacher_python="${TEACHER_PYTHON:-python3}"
"$teacher_python" -c 'import sys; assert sys.version_info >= (3, 12), "需要 Python 3.12 或以上"'
command -v node >/dev/null || { echo '请先安装 Node.js 22 或以上。'; exit 1; }
command -v npm >/dev/null || { echo '请先安装 npm。'; exit 1; }
command -v ffmpeg >/dev/null || { echo '请先安装 FFmpeg。'; exit 1; }
node -e 'if (Number(process.versions.node.split(".")[0]) < 22) process.exit(1)'
if [ ! -d .venv ]; then "$teacher_python" -m venv .venv; fi
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/local.py init
.venv/bin/python scripts/install_renderer.py
