"""准备固定版本的 Dify、构建镜像和管理本项目实例。"""
import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'vendor/dify'
BASE = json.loads((ROOT / 'dify-base.json').read_text())


def run(*args, cwd=None):
    subprocess.run(args, cwd=cwd or ROOT, check=True)


def prepare(source=SOURCE):
    source = Path(source)
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        run('git', 'clone', '--filter=blob:none', '--no-checkout', BASE['repository'], str(source))
        run('git', 'checkout', '--detach', BASE['commit'], cwd=source)
    current = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
    if current != BASE['commit']:
        raise RuntimeError('Dify 版本不符，请使用 dify-base.json 中固定的提交。')
    # 只覆盖清单内文件，升级时可以逐项对照上游。
    for relative in BASE['overlay_files']:
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / 'dify-overlay' / relative, target)
    deploy = source / 'docker'
    env = deploy / '.env'
    if not env.exists():
        sandbox = secrets.token_urlsafe(32)
        settings = {
            'SECRET_KEY': secrets.token_urlsafe(42), 'DB_PASSWORD': secrets.token_urlsafe(24),
            'REDIS_PASSWORD': secrets.token_urlsafe(24), 'CODE_EXECUTION_API_KEY': sandbox,
            'SANDBOX_API_KEY': sandbox, 'PLUGIN_DAEMON_KEY': secrets.token_urlsafe(32),
            'PLUGIN_DIFY_INNER_API_KEY': secrets.token_urlsafe(32),
            'DIFY_AGENT_API_TOKEN': secrets.token_urlsafe(32),
            'DIFY_AGENT_SERVER_SECRET_KEY': secrets.token_urlsafe(32),
            'DIFY_AGENT_LOCAL_SANDBOX_AUTH_TOKEN': secrets.token_urlsafe(32),
            'EXPOSE_NGINX_PORT': '127.0.0.1:8788', 'EXPOSE_NGINX_SSL_PORT': '127.0.0.1:8743',
            'NEXT_PUBLIC_SOCKET_URL': 'ws://127.0.0.1:8788',
            'CONSOLE_API_URL': 'http://127.0.0.1:8788', 'CONSOLE_WEB_URL': 'http://127.0.0.1:8788',
            'APP_WEB_URL': 'http://127.0.0.1:8788', 'SERVICE_API_URL': 'http://127.0.0.1:8788',
            'FILES_URL': 'http://127.0.0.1:8788', 'APP_API_URL': 'http://127.0.0.1:8788',
            'CODE_MAX_STRING_LENGTH': '400000', 'CODE_MAX_STRING_ARRAY_LENGTH': '500',
        }
        lines = []
        for line in (deploy / '.env.example').read_text().splitlines():
            key = line.split('=', 1)[0]
            if key in settings: line = key + '=' + settings.pop(key)
            lines.append(line)
        lines.extend(key + '=' + value for key, value in settings.items())
        env.write_text('\n'.join(lines) + '\n')
        env.chmod(0o600)
    proxy = deploy / 'ssrf_proxy/squid.conf.template'
    text = proxy.read_text()
    marker = 'acl teacher_video_host '
    if marker not in text:
        anchor = 'http_access deny to_private_networks'
        if text.count(anchor) != 1: raise RuntimeError('Dify 内部代理模板已变化。')
        rule = ('acl teacher_video_host dstdomain host.docker.internal\n'
                'acl teacher_video_port port 8794\n'
                'http_access allow client_localnet teacher_video_host teacher_video_port\n')
        proxy.write_text(text.replace(anchor, rule + '\n' + anchor))
    common = deploy / 'ssrf_proxy/squid-common.conf.template'
    common.write_text(common.read_text().replace('client_lifetime 5 minutes', 'client_lifetime 20 minutes'))
    (deploy / 'teacher.override.yml').write_text('''services:
  api:
    image: teacher-video-api:0.1.0
  api_websocket:
    image: teacher-video-api:0.1.0
  worker:
    image: teacher-video-api:0.1.0
  worker_beat:
    image: teacher-video-api:0.1.0
  web:
    image: teacher-video-web:0.1.0
  plugin_daemon:
    ports: !reset []
''')
    print('Dify 源码、界面改动和本地配置已准备。')


def compose(action):
    if not (SOURCE / 'docker/teacher.override.yml').exists():
        raise RuntimeError('请先运行 prepare 和 build。')
    args = {'up': ['up', '-d'], 'down': ['down'], 'status': ['ps'], 'config': ['config', '--quiet']}[action]
    run('docker', 'compose', '-p', 'teacher-video', '-f', 'docker-compose.yaml',
        '-f', 'teacher.override.yml', *args, cwd=SOURCE / 'docker')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'build', 'up', 'down', 'status', 'config'])
    action = parser.parse_args().action
    if action == 'prepare': prepare()
    elif action == 'build':
        if not (SOURCE / 'docker/teacher.override.yml').exists():
            raise RuntimeError('请先运行 prepare。')
        run('docker', 'build', '-t', 'teacher-video-api:0.1.0', '-f', 'Dockerfile.api', '.')
        run('docker', 'build', '-t', 'teacher-video-web:0.1.0', '-f', 'web/Dockerfile',
            '--build-arg', 'COMMIT_SHA=' + BASE['commit'], '.', cwd=SOURCE)
    else: compose(action)


if __name__ == '__main__': main()
