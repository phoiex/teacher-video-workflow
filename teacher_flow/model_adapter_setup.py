"""启动本机协议适配进程，不发送模型请求。"""
import json
import os
import secrets
import socket
import sys
import subprocess
import time
import urllib.request
import urllib.parse
from .common import RUNTIME, TOOL, load, save
from . import model_connections


def ensure(profile=None):
    from .model_roles import DEFAULT_MODEL_ROLES, validate
    profile = profile or DEFAULT_MODEL_ROLES['producer']
    validate({**DEFAULT_MODEL_ROLES, 'producer': profile})
    folder=RUNTIME.parent/'model-adapter'
    path=folder/'config.json'
    if not path.exists():
        save(path,{'port':8795,'base_url':'http://127.0.0.1:8795/v1','token':secrets.token_urlsafe(32)})
    os.chmod(path,0o600)
    config=load(path)
    selected = model_connections.route(profile)
    selected = {k:selected[k] for k in ('provider','model','protocol','catalog_model') if k in selected}
    routes = config.setdefault('models', {})
    previous = routes.get(profile['model'])
    if previous and previous.get('provider') != profile['provider']:
        raise ValueError('本机已登记同名模型的其他服务商，请使用不同模型别名。')
    if previous != selected:
        routes[profile['model']] = selected
        save(path, config)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def ready():
        try:
            with opener.open(f'http://127.0.0.1:{config["port"]}/health?model='+urllib.parse.quote(profile['model'],safe=''),timeout=1) as r:
                status=json.load(r)
                return status if status.get('service') == 'course-model-responses' else None
        except Exception:return None
    status=ready()
    if status:return {**config,'model_context_window':status.get('max_input_tokens')}
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        try:sock.bind(('127.0.0.1',config['port']))
        except OSError as exc:raise RuntimeError('协议适配端口已被其他程序占用。') from exc
    with (folder/'service.log').open('ab') as log:
        process=subprocess.Popen([sys.executable,'-m','uvicorn',
            'teacher_flow.model_adapter:app','--host','127.0.0.1','--port',str(config['port']),
            '--no-access-log'],cwd=TOOL,stdin=subprocess.DEVNULL,stdout=log,stderr=log,
            start_new_session=True,env={**os.environ,'PYTHONPATH':str(TOOL),
                                      'LITELLM_LOCAL_MODEL_COST_MAP':'True','DO_NOT_TRACK':'1'})
    save(folder/'service.json',{'pid':process.pid,'port':config['port']})
    for _ in range(60):
        status=ready()
        if status:return {**config,'model_context_window':status.get('max_input_tokens')}
        if process.poll() is not None:break
        time.sleep(.25)
    raise RuntimeError('协议适配未启动，请查看运行日志。')


if __name__=='__main__':
    config=ensure()
    print(json.dumps({'ok':True,'base_url':config['base_url']}))
