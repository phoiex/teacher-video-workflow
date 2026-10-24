"""准备本地配置、检查环境或启动制作服务。"""
import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from teacher_flow.common import RUNTIME, RENDER_RUNTIME, NODE, load, save
from teacher_flow.model_roles import default_roles


def initialize():
    os.umask(0o077)
    if not (ROOT / '.env').exists():
        shutil.copyfile(ROOT / '.env.example', ROOT / '.env')
        (ROOT / '.env').chmod(0o600)
    if not (ROOT / 'models.json').exists():
        shutil.copyfile(ROOT / 'models.example.json', ROOT / 'models.json')
    path = RUNTIME / 'bridge.json'
    if not path.exists():
        save(path, {'token': secrets.token_urlsafe(32), 'public_url': 'http://127.0.0.1:8794'})
    path.chmod(0o600)
    # 生成的 DSL 仅供本地导入，带本次安装独有的工具口令。
    import yaml
    dsl = yaml.safe_load((ROOT / 'workflow/teacher-video.yml').read_text())
    for item in dsl['workflow']['environment_variables']:
        if item['name'] == 'LOCAL_TOOL_TOKEN': item['value'] = load(path)['token']
    target = RUNTIME.parent / 'teacher-video.local.yml'
    target.write_text(yaml.safe_dump(dsl, allow_unicode=True, sort_keys=False))
    target.chmod(0o600)
    return target


def doctor():
    checks = {'Python 3.12+': sys.version_info >= (3, 12),
              'Node': bool(shutil.which(NODE)), 'FFmpeg': bool(shutil.which('ffmpeg')),
              'FFprobe': bool(shutil.which('ffprobe')),
              '浏览器依赖': (RENDER_RUNTIME / 'node_modules/playwright-core/index.mjs').is_file(),
              'Chromium': bool(list((RENDER_RUNTIME / 'browsers').glob('chromium*'))),
              '本地配置': (RUNTIME / 'bridge.json').is_file()}
    from teacher_flow.model_connections import connection
    for role, profile in default_roles().items():
        try: connection(profile); checks[role + ' 凭据'] = True
        except ValueError: checks[role + ' 凭据'] = False
    checks['百炼凭据'] = bool(os.getenv('DASHSCOPE_API_KEY') and os.getenv('DASHSCOPE_WORKSPACE_ID'))
    for name, ok in checks.items(): print(('✓ ' if ok else '缺少：') + name)
    return all(checks.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['init', 'doctor', 'serve'])
    args = parser.parse_args()
    if args.action == 'init':
        print('本地配置已准备。Dify 导入文件：' + str(initialize()))
    elif args.action == 'doctor':
        raise SystemExit(0 if doctor() else 1)
    else:
        initialize()
        import uvicorn
        uvicorn.run('teacher_flow.service:app', host='127.0.0.1', port=8794, access_log=False)


if __name__ == '__main__': main()
