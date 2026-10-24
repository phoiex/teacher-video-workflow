"""微课配音：复用旧音频，分开保存合成回执和下载进度。"""
import hashlib
import json
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path
from .common import load, save
from . import network_retry


def provider():
    from . import tts_config
    return tts_config


def archive(folder,name,record):
    target=folder/'attempts'/str(time.time_ns())
    save(target/(name+'.json'),record)


def synthesize(text,name,folder,instruction,*,checkpoint=None,on_retry=None):
    folder=Path(folder);folder.mkdir(exist_ok=True,parents=True)
    record_path=folder/(name+'.json');audio=folder/(name+'.wav')
    recovery=folder/'download-recovery'/(name+'.json')
    module=provider()
    expected={'text_sha256':hashlib.sha256(text.encode()).hexdigest(),
              'model':module.MODEL,'voice':'longanlingxin','instruction':instruction}
    previous=load(record_path) if record_path.exists() else None
    if previous:
        if any(previous.get(k)!=v for k,v in expected.items()):raise ValueError('已保存的配音与当前文本或声音设置不一致。')
        if previous.get('status')=='complete':
            if not audio.exists() or hashlib.sha256(audio.read_bytes()).hexdigest()!=previous.get('sha256'):
                raise ValueError('已完成配音的文件不完整，请查看保存记录。')
            return audio
        if not recovery.exists() and not network_retry.receipt_retryable(previous):
            raise ValueError('配音接入或文本需要处理，请查看错误记录。')
    state={**expected,'status':'submitted','model':module.MODEL,'provider':'阿里云百炼',
           'region':'cn-beijing','characters':len(text),'retry_count':0}
    def remember_error(exc,phase):
        state.update(status='needs_review',error_type=type(exc).__name__,
                     retryable=network_retry.is_network_error(exc),phase=phase,
                     http_status=getattr(exc,'code',None))
        save(record_path,state)
    if not recovery.exists():
        key=module.read_credential('API Key');workspace=module.read_credential('Workspace ID')
        endpoint=f'https://{workspace}.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer'
        payload={'model':module.MODEL,'input':{'text':text,'voice':'longanlingxin','language_hints':['zh'],
            'format':'wav','sample_rate':24000,'seed':17,'instruction':instruction}}
        def request_once(attempt):
            if record_path.exists():archive(folder,name,load(record_path))
            state.update(status='submitted',phase='synthesis',retry_count=attempt-1,retryable=False)
            save(record_path,state)
            request=urllib.request.Request(endpoint,data=json.dumps(payload,ensure_ascii=False).encode(),
                headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
            try:
                with urllib.request.urlopen(request,timeout=180) as response:result=json.load(response)
                url=((result.get('output') or {}).get('audio') or {}).get('url')
                if not url:
                    if result.get('code') in ('ServiceUnavailable','Throttling','InternalError'):
                        raise network_retry.NetworkFailure()
                    raise ValueError('配音接口没有返回音频，请检查文本和声音设置。')
                # 下载地址只保存在受保护的本机运行目录，成功后移除。
                save(recovery,{'url':url,'request_id':result.get('request_id'),'text_sha256':expected['text_sha256']})
                state.update(status='download_pending',request_id=result.get('request_id'),phase='download')
                save(record_path,state)
                return result
            except Exception as exc:
                remember_error(exc,'synthesis');raise
        network_retry.call(request_once,checkpoint=checkpoint,on_retry=on_retry)
    saved=load(recovery)
    if saved['text_sha256']!=expected['text_sha256']:raise ValueError('配音下载记录与文本不一致。')
    def download_once(attempt):
        try:
            with urllib.request.urlopen(saved['url'],timeout=180) as response:raw=response.read()
            source=folder/'raw'/(name+'_seed17.wav');source.parent.mkdir(exist_ok=True)
            source.write_bytes(raw)
            with wave.open(str(source),'rb') as src:
                channels,width,rate=src.getnchannels(),src.getsampwidth(),src.getframerate()
                pcm=src.readframes(src.getnframes())
            if not pcm or (channels,width,rate)!=(1,2,24000):raise ValueError('返回的配音格式不正确。')
            partial=audio.with_suffix('.part.wav')
            with wave.open(str(partial),'wb') as out:
                out.setnchannels(channels);out.setsampwidth(width);out.setframerate(rate);out.writeframes(pcm)
            partial.replace(audio)
            state.update(status='complete',request_id=saved['request_id'],output=str(audio),
                duration_seconds=round(len(pcm)/(rate*channels*width),3),sample_rate=rate,channels=channels,
                sample_width_bytes=width,bytes=audio.stat().st_size,sha256=hashlib.sha256(audio.read_bytes()).hexdigest(),
                retryable=False,download_attempt=attempt)
            save(record_path,state);recovery.unlink()
            return audio
        except Exception as exc:
            remember_error(exc,'download');raise
    return network_retry.call(download_once,checkpoint=checkpoint,on_retry=on_retry)
