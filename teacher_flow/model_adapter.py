"""Convert configured Messages or Chat Completions models to Responses locally."""
import asyncio
import json
import os
import secrets
import time
import uuid

os.environ['LITELLM_LOCAL_MODEL_COST_MAP'] = 'True'
os.environ['DO_NOT_TRACK'] = '1'

import litellm
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from .common import RUNTIME, digest, load, save
from . import model_connections
from .model_roles import DEFAULT_MODEL_ROLES
from .response_stream import ResponseStream

litellm.telemetry = False
litellm.suppress_debug_info = True
litellm.set_verbose = False
ROOT = RUNTIME.parent/'model-adapter'
app = FastAPI(docs_url=None, redoc_url=None)


def configured_models(config):
    return config.get('models') or {
        DEFAULT_MODEL_ROLES['producer']['model']: model_connections.route(DEFAULT_MODEL_ROLES['producer'])}


@app.get('/health')
def health(model:str|None=None):
    routes = configured_models(load(ROOT/'config.json'))
    status = {'ok':True,'service':'course-model-responses','adapter':'litellm-1.106.0',
              'stream_contract':'reasoning-and-tool-continuation-v1',
              'output_policy':'provider_default','models':list(routes)}
    if model:
        if model not in routes:raise HTTPException(404,'模型尚未登记。')
        info = model_connections.catalog_info(routes[model],litellm.model_cost)
        status.update(model=model, max_input_tokens=info.get('max_input_tokens'),
                      model_max_output_tokens=info.get('max_output_tokens') or info.get('max_tokens'))
    return status


@app.post('/v1/responses')
async def responses(request:Request, authorization:str|None=Header(default=None)):
    config = load(ROOT/'config.json')
    if not secrets.compare_digest(authorization or '', 'Bearer '+config['token']):
        raise HTTPException(401, '本机协议适配鉴权失败。')
    payload = await request.json()
    model = payload.get('model','')
    profile = configured_models(config).get(model)
    if not profile:
        raise HTTPException(400, '模型尚未登记，请先配置对应的服务商和协议。')
    if not payload.get('stream'):
        raise HTTPException(400, '制作会话需使用流式响应。')
    provider = model_connections.adapter_provider(profile)
    info = model_connections.catalog_info(profile,litellm.model_cost)
    try:
        policy = model_connections.output_policy(profile,litellm.model_cost,payload.get('max_output_tokens'))
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc
    if info:
        info.update(litellm_provider=provider, mode='responses' if profile['protocol']=='responses' else 'chat')
        litellm.register_model({provider+'/'+model:info, model:info})
    try:
        access = await asyncio.to_thread(model_connections.connection,profile)
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc
    key = access['api_key']
    job = uuid.uuid4().hex
    path = ROOT/'requests'/f'{job}.json'
    record = {'id':job,'model':model,'status':'submitting','started_at':time.time(),
              'request_hash':digest(payload),'input_items':len(payload.get('input',[])),
              'tools':len(payload.get('tools',[])), 'reasoning':payload.get('reasoning'),
              'provider':profile['provider'], 'protocol':profile['protocol'],
              'catalog_model':profile.get('catalog_model'),
              'output_limit_source':policy['source'],
              'effective_max_output_tokens':policy['max_output_tokens']}
    save(path,record)
    # Codex的缓存分组提示不是Messages字段；对话、工具及思考设置保持。
    kwargs = {k:v for k,v in payload.items() if k not in ('model','stream','prompt_cache_key')}
    try:
        stream = await litellm.aresponses(model=provider+'/'+model, stream=True,
            api_base=access['base_url'], api_key=key,
            timeout=900, num_retries=0, **kwargs)
    except Exception as exc:
        detail = str(exc).replace(key,'[redacted]').replace(config['token'],'[redacted]')[:1500]
        record.update(status='failed',finished_at=time.time(),error_type=type(exc).__name__,detail=detail)
        save(path,record)
        raise HTTPException(getattr(exc,'status_code',502) or 502, detail) from exc

    async def events():
        record['status']='running';save(path,record)
        bridge = ResponseStream(stream)
        last_saved = time.monotonic()
        try:
            async for event in stream:
                data = bridge.normalize(event)
                kind = data.get('type','')
                reply = data.get('response') or {}
                record['stream'] = bridge.snapshot()
                if kind in ('response.completed','response.failed','response.incomplete'):
                    record.update(status=reply.get('status',kind.removeprefix('response.')),
                                  response_id=reply.get('id'),usage=reply.get('usage'),finished_at=time.time())
                    save(path,record)
                elif time.monotonic() - last_saved >= 2:
                    save(path,record)
                    last_saved = time.monotonic()
                yield 'event: '+kind+'\ndata: '+json.dumps(data,ensure_ascii=False)+'\n\n'
            if record['status']=='running':
                raise RuntimeError('模型连接结束前未收到完整响应。')
        except asyncio.CancelledError:
            record.update(status='interrupted',finished_at=time.time());save(path,record)
            raise
        except Exception as exc:
            detail=str(exc).replace(key,'[redacted]').replace(config['token'],'[redacted]')[:1500]
            record.update(status='failed',finished_at=time.time(),error_type=type(exc).__name__,detail=detail)
            save(path,record)
            raise
        finally:
            close=getattr(stream,'aclose',None)
            if close:await close()
    return StreamingResponse(events(),media_type='text/event-stream',
        headers={'Cache-Control':'no-store','X-Accel-Buffering':'no'})
