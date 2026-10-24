"""安装固定版本的浏览器渲染依赖，不调用模型。"""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from teacher_flow.common import RENDER_RUNTIME, NODE


def main():
    RENDER_RUNTIME.mkdir(parents=True, exist_ok=True)
    (RENDER_RUNTIME / 'package.json').write_text(json.dumps({
        'name': 'teacher-video-renderer', 'private': True,
        'dependencies': {'playwright-core': '1.61.1'}}) + '\n')
    subprocess.run(['npm', 'install', '--ignore-scripts', '--no-audit', '--no-fund'], cwd=RENDER_RUNTIME, check=True)
    subprocess.run([NODE, str(RENDER_RUNTIME / 'node_modules/playwright-core/cli.js'),
                    'install', 'chromium'], check=True,
                   env={**os.environ, 'PLAYWRIGHT_BROWSERS_PATH': str(RENDER_RUNTIME / 'browsers')})
    print('浏览器渲染依赖已准备。')


if __name__ == '__main__': main()
