"""按课程角色调用模型，保存可恢复的请求与结果。"""
import base64
import fcntl
import json
import mimetypes
import time
from pathlib import Path

from .common import RUNTIME, digest, load, save
from . import model_roles, network_retry, model_connections

def messages(message, images, protocol):
    text = json.dumps(message, ensure_ascii=False) + '\n\n按本步骤要求返回 JSON 对象。'
    content = [{'type':'text' if protocol == 'chat.completions' else 'input_text', 'text':text}]
    for item in images:
        path = Path(item['path'])
        mime = mimetypes.guess_type(path.name)[0] or 'image/png'
        url = 'data:'+mime+';base64,'+base64.b64encode(path.read_bytes()).decode()
        content.append({'type':'image_url', 'image_url':{'url':url}} if protocol == 'chat.completions'
                       else {'type':'input_image', 'image_url':url})
    return [{'role':'user', 'content':content}]


def generate(stage, instructions, message, images=None, profile=None):
    from openai import OpenAI
    profile = profile or model_roles.for_stage(stage)
    if not profile or profile['protocol'] not in model_connections.PROTOCOLS:
        raise ValueError('内容节点模型协议配置不正确。')
    images = images or []
    packet = {'format_version':1, 'stage':stage, 'profile':profile, 'instructions':instructions, 'message':message,
              'images':[{**p,'sha256':digest(Path(p['path']).read_bytes())} for p in images]}
    folder = RUNTIME/(profile['provider']+'-requests')/digest(packet)
    folder.mkdir(parents=True, exist_ok=True)
    with (folder/'request.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        receipt = folder/'receipt.json'
        if receipt.exists():
            old = load(receipt)
            if old.get('status') == 'completed':
                return load(folder/'result.json')
            if not network_retry.receipt_retryable(old):
                raise ValueError('上次模型请求尚未取得可接续结果，请查看记录。')
        save(folder/'request.json', packet)
        if profile['protocol'] == 'messages':
            from .model_adapter_setup import ensure
            bridge = ensure(profile)
            access = {'api_key': bridge['token'], 'base_url': bridge['base_url']}
            protocol = 'responses'
        else:
            access = model_connections.connection(profile, RUNTIME)
            protocol = profile['protocol']
        key = access['api_key']

        def once(attempt):
            if receipt.exists():
                save(folder/'attempts'/f'{time.time_ns()}.json',load(receipt))
            record = {'status':'submitting','model':profile['model'],'provider':profile['provider'],
                      'protocol':profile['protocol'],'attempt':attempt,'started_at':time.time()}
            save(receipt, record)
            content = messages(message, images, protocol)
            text, usage, terminal = '', None, False
            try:
                with OpenAI(api_key=key,base_url=access['base_url'],timeout=900,max_retries=0) as client:
                    if protocol == 'responses':
                        options = {'model':profile['model'],'instructions':instructions,
                            'input':content,'text':{'format':{'type':'json_object'}},
                            'store':False,'stream':True}
                        if profile.get('reasoning_effort'):
                            options['reasoning']={'effort':profile['reasoning_effort']}
                        with client.responses.create(**options) as stream:
                            for event in stream:
                                if event.type in ('response.completed','response.failed','response.incomplete'):
                                    reply = event.response
                                    terminal = True
                                    record.update(response_id=reply.id,returned_model=reply.model)
                                    usage = reply.usage.model_dump() if reply.usage else None
                                    if reply.status != 'completed':
                                        raise ValueError('模型未返回完整结果。')
                                    text = reply.output_text
                    else:
                        options = {'model':profile['model'], 'messages':[{'role':'system','content':instructions}]+content,
                            'response_format':{'type':'json_object'}, 'stream':True, 'stream_options':{'include_usage':True}}
                        if profile.get('reasoning_effort'):
                            options['reasoning_effort']=profile['reasoning_effort']
                        with client.chat.completions.create(**options) as stream:
                            for event in stream:
                                record.update(response_id=event.id,returned_model=event.model)
                                if event.usage: usage = event.usage.model_dump()
                                for choice in event.choices:
                                    text += choice.delta.content or ''
                                    if choice.finish_reason:
                                        terminal = True
                                        if choice.finish_reason != 'stop':
                                            raise ValueError('模型未返回完整结果。')
                if not terminal:
                    raise network_retry.NetworkFailure('连接结束前未收到完整响应。')
                save(folder/'response.json',{'text':text,'usage':usage})
                data = json.loads(text)
                if not isinstance(data,dict):
                    raise ValueError('模型返回的JSON不是对象。')
                save(folder/'result.json',data)
                record.update(status='completed',finished_at=time.time(),usage=usage)
                save(receipt,record)
                return data
            except Exception as exc:
                record.update(status='failed' if terminal or getattr(exc,'status_code',None) else 'unknown',
                    retryable=network_retry.is_network_error(exc),error_type=type(exc).__name__,
                    http_status=getattr(exc,'status_code',None),finished_at=time.time(),
                    detail=str(exc).replace(key,'[redacted]')[:1200])
                save(receipt,record)
                raise
        return network_retry.call(once)
