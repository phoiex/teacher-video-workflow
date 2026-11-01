"""内容阶段通过 DeepSeek Harness 提交结构化结果。"""
import fcntl
import json
from pathlib import Path
import time

from .common import RUNTIME,digest,load,save
from . import model_roles,network_retry
from .dsh_runtime import Session
from .codex_runtime import text_result,tool


def generate(stage,instructions,message,images=None,profile=None):
    profile=profile or model_roles.for_stage(stage)
    packet={'stage':stage,'profile':profile,'instructions':instructions,'message':message,
            'images':[{**p,'sha256':digest(Path(p['path']).read_bytes())} for p in images or []]}
    folder=RUNTIME/'dsh-requests'/digest(packet);folder.mkdir(parents=True,exist_ok=True)
    with (folder/'request.lock').open('a') as guard:
        fcntl.flock(guard,fcntl.LOCK_EX)
        result=folder/'result.json'
        if result.exists():return load(result)
        save(folder/'request.json',packet)
        definition=tool('submit_result','保存本步骤要求的完整 JSON 对象。',{'result_json':{'type':'string'}})
        def handler(name,args):
            if name!='submit_result':raise ValueError('未提供该工具。')
            data=json.loads(args['result_json'])
            if not isinstance(data,dict):raise ValueError('结果需为 JSON 对象。')
            save(result,data)
            return text_result({'saved':True})
        def once(attempt):
            if result.exists():return load(result)
            label='request-'+str(time.time_ns())
            save(folder/'receipt.json',{'status':'running','harness':'deepseek','stage':stage,
                                      'attempt':attempt,'started_at':time.time(),'label':label})
            try:
                with Session(folder/'session',instructions+'\n将本步骤的完整 JSON 对象通过 submit_result 保存。',
                             [definition],handler,profile=profile) as session:
                    session.run(label,json.dumps(message,ensure_ascii=False),images=images)
                if not result.exists():raise ValueError('未取得本步骤的结构化结果。')
                save(folder/'receipt.json',{'status':'completed','harness':'deepseek','label':label,'finished_at':time.time()})
                return load(result)
            except Exception as exc:
                if result.exists():
                    save(folder/'receipt.json',{'status':'completed','harness':'deepseek','label':label,
                                               'saved_before_exit':True,'finished_at':time.time()})
                    return load(result)
                save(folder/'receipt.json',{'status':'failed','harness':'deepseek','label':label,
                    'retryable':network_retry.is_network_error(exc),'error_type':type(exc).__name__,'finished_at':time.time()})
                raise
        return network_retry.call(once)
