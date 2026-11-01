"""DeepSeek Harness 原生 SDK 会话；课程工具与状态由本地服务提供。"""
from __future__ import annotations

import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import queue
import re
import secrets
import subprocess
import threading
import time
import uuid

from .common import RUNTIME, TOOL, load, save
from .codex_runtime import SessionPaused
from .network_retry import NetworkFailure

VERSION='0.1.5-rc.1'
INSTALL=Path(os.environ.get('TEACHER_DSH_RUNTIME', str(RUNTIME.parent/'deepseek-harness')))


def runtime_paths():
    manifest=load(INSTALL/'manifest.json')
    package=Path(manifest['package']);node=Path(manifest['node_bin'])
    if manifest['version']!=VERSION or load(package/'package.json')['version']!=VERSION or not node.is_file():
        raise RuntimeError('DeepSeek 制作运行时版本不符，请重新检查安装。')
    server=package/'node_modules/@deepseek-ai/dsh-sdk-jsonrpc-server/lib/index.js'
    if hashlib.sha256(server.read_bytes()).hexdigest()!=manifest.get('sdk_server_sha256'):
        raise RuntimeError('DeepSeek 会话恢复接口已变化，请核对课程运行时。')
    return node,package


class Session:
    def __init__(self,folder,instructions,tools,handler,on_event=None,pause_requested=None,profile=None,access=None):
        self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.profile=profile or {'provider':'deepseek','model':'deepseek-flash','protocol':'chat.completions','harness':'deepseek'}
        if self.profile['provider']!='deepseek':raise ValueError('这个分支使用 DeepSeek 模型。')
        if access is None:
            from .model_connections import connection
            access=connection(self.profile)
        self.secret=access['api_key'];self.handler=handler;self.tools=tools
        self.on_event=on_event or (lambda _:None);self.pause_requested=pause_requested or (lambda:False)
        self.messages=queue.Queue();self.write_lock=threading.Lock();self.event_lock=threading.Lock()
        self.process=None;self.closed=False;self.active_label=None;self.counter=0
        pointer=self.folder/'dsh-session.json'
        previous=load(pointer) if pointer.exists() else {}
        self.thread_id=previous.get('session_id') or str(uuid.uuid4())
        if previous and previous.get('model')!=self.profile['model']:raise ValueError('已有制作会话的模型不一致。')
        self.tool_token=secrets.token_urlsafe(32)
        node,package=runtime_paths()
        owner=self
        class Bridge(BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def answer(self,code,value):
                raw=json.dumps(value,ensure_ascii=False).encode()
                self.send_response(code);self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(raw)));self.end_headers()
                try:self.wfile.write(raw)
                except (BrokenPipeError,ConnectionResetError):pass
            def authorize(self):
                return secrets.compare_digest(self.headers.get('Authorization',''),'Bearer '+owner.tool_token)
            def do_GET(self):
                if not self.authorize():return self.answer(401,{'error':'工具鉴权失败'})
                if self.path!='/tools':return self.answer(404,{})
                return self.answer(200,owner.tools)
            def do_POST(self):
                if not self.authorize():return self.answer(401,{'error':'工具鉴权失败'})
                if self.path!='/call':return self.answer(404,{})
                try:
                    packet=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    if packet['name'] not in {t['name'] for t in owner.tools}:raise ValueError('未提供该工具')
                    owner.record('producer/tool_started',{'name':packet['name']})
                    result=owner.handler(packet['name'],packet['args'])
                    owner.record('producer/tool_completed',{'name':packet['name']})
                    self.answer(200,result)
                except Exception as exc:self.answer(400,{'success':False,'error':owner.clean(str(exc))})
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Bridge)
        self.server.daemon_threads=False
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        home=self.folder/'dsh-home';home.mkdir(exist_ok=True,mode=0o700)
        workspace=self.folder/'workspace';workspace.mkdir(exist_ok=True)
        # 使用原生 SDK 内核、持久会话和上下文压缩；工具目录绑定本课程。
        patch=[{'id':name,'disabled':True} for name in ('persistent-bash','persistent-pwsh')]
        patch.append({'id':'llm-deepseek','config':{'baseURL':access['base_url']}})
        patch += [{'insert':[
            {'id':'attachment-local','name':'@deepseek-ai/dsh-attachment-local'},
            {'id':'token-meter','name':'@deepseek-ai/dsh-token-meter'},
            {'id':'compaction-basic','name':'@deepseek-ai/dsh-compaction-basic'},
            {'id':'course-tools','name':str(TOOL/'teacher_flow/dsh_tools.mjs')},
        ]}]
        patch_file=self.folder/'dsh.patch.json';save(patch_file,patch)
        env={**os.environ,'DSH_HOME':str(home),'DSH_SYSTEM_PROMPT':instructions,
             'DEEPSEEK_API_KEY':self.secret,'DEEPSEEK_BASE_URL':access['base_url'],
             'TEACHER_DSH_MODULES':str(package/'node_modules'),
             'TEACHER_DSH_TOOL_URL':f'http://127.0.0.1:{self.server.server_port}',
             'TEACHER_DSH_TOOL_TOKEN':self.tool_token,'DO_NOT_TRACK':'1'}
        if previous.get('opened'):env['TEACHER_DSH_RESUME']=self.thread_id
        try:
            self.process=subprocess.Popen([str(node),str(package/'lib/bin.js'),'--profile','sdk-minimal',
                '--patch',str(patch_file)],cwd=workspace,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,text=True,bufsize=1,start_new_session=True)
            self.reader_thread=threading.Thread(target=self._read,daemon=True);self.reader_thread.start()
            self.diagnostic_thread=threading.Thread(target=self._diagnostics,daemon=True);self.diagnostic_thread.start()
            params={'cwd':str(workspace),'provider':'deepseek-official','model':self.profile['model']}
            if self.profile.get('reasoning_effort'):params['reasoningEffort']=self.profile['reasoning_effort']
            result=self.request('initialize',params,timeout=45)
            if result['serverInfo']['name']!='deepseek-harness-sdk-runtime':raise RuntimeError('制作内核身份不符')
            save(pointer,{'session_id':self.thread_id,'model':self.profile['model'],'harness':'deepseek',
                          'version':VERSION,'opened':previous.get('opened',False),
                          'created_at':previous.get('created_at',time.time())})
            self.record('producer/resumed' if previous else 'producer/created',{'thread_id':self.thread_id,'harness':'deepseek'})
        except BaseException:
            self.close();raise

    def clean(self,text):
        return str(text).replace(self.secret,'[redacted]').replace(self.tool_token,'[redacted]')

    def record(self,method,params):
        event={'time':time.time(),'method':method,'params':params}
        with self.event_lock:
            with (self.folder/'events.jsonl').open('a') as output:output.write(self.clean(json.dumps(event,ensure_ascii=False))+'\n')
        self.on_event(event)

    def _read(self):
        try:
            for line in self.process.stdout:
                try:message=json.loads(line)
                except ValueError:
                    self.messages.put({'reader_error':'DeepSeek SDK 返回了非协议内容。'});continue
                self.messages.put(message)
        finally:self.messages.put({'process_exited':True})

    def _diagnostics(self):
        for line in self.process.stderr:
            with (self.folder/'runtime.log').open('a') as out:out.write(self.clean(line))

    def send(self,method,params=None):
        self.counter+=1;packet={'jsonrpc':'2.0','id':self.counter,'method':method}
        if params is not None:packet['params']=params
        with self.write_lock:
            self.process.stdin.write(json.dumps(packet,ensure_ascii=False)+'\n');self.process.stdin.flush()
        return self.counter

    def next_message(self,timeout=.25):
        try:message=self.messages.get(timeout=timeout)
        except queue.Empty:return None
        if message.get('reader_error'):raise RuntimeError(message['reader_error'])
        if message.get('process_exited'):raise RuntimeError('DeepSeek 制作会话已退出，请查看运行记录。')
        if message.get('method'):
            self.record(message['method'],message.get('params',{}))
        return message

    def request(self,method,params=None,timeout=30):
        request_id=self.send(method,params);deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            message=self.next_message()
            if message and message.get('id')==request_id:
                if message.get('error'):raise RuntimeError(self.clean(message['error'].get('message','SDK 请求失败')))
                return message.get('result',{})
        raise TimeoutError('DeepSeek SDK 未在启动期限内就绪。')

    def run(self,label,prompt,images=None):
        if not re.fullmatch(r'[a-zA-Z0-9_-]+',label):raise ValueError('制作步骤编号不正确')
        receipt=self.folder/'turns'/(label+'.json')
        if receipt.exists():
            previous=load(receipt)
            if previous.get('status')=='completed':return previous
            raise ValueError('上次制作已保存，请使用断点重试继续。')
        self.active_label=label
        record={'status':'submitting','started_at':time.time(),'thread_id':self.thread_id,
                'turn_id':label,'harness':'deepseek','model':self.profile['model']}
        save(receipt,record)
        content=[{'type':'text','text':prompt}]
        for item in images or []:
            path=Path(item['path']);mime=mimetypes.guess_type(path.name)[0] or 'image/png'
            content.extend([{'type':'text','text':item.get('image_id',item.get('name',path.name))},
                {'type':'image','data':base64.b64encode(path.read_bytes()).decode(),'mimeType':mime}])
        end=None
        try:
            request_id=self.send('session/prompt',{'sessionId':self.thread_id,'contentBlocks':content})
            accepted=False;idle=False;saw_start=False
            while True:
                if self.pause_requested():
                    self.close();raise SessionPaused()
                message=self.next_message()
                if message is None:continue
                if message.get('id')==request_id:
                    if message.get('error'):raise RuntimeError(self.clean(message['error']['message']))
                    accepted=True;record.update(status='running',message_id=message['result']['messageId']);save(receipt,record)
                    pointer=self.folder/'dsh-session.json';saved=load(pointer);saved['opened']=True;save(pointer,saved)
                params=message.get('params',{})
                if params.get('sessionId')!=self.thread_id:continue
                if message.get('method')=='session.event':
                    event=params['event']
                    if event.get('type')=='llm/retry':
                        from .network_retry import progress
                        notify=progress.get()
                        if notify:notify({'status':'retrying','waiting':True,'message':'模型连接中断，正在重连。'})
                    elif event.get('type')=='llm/retry-started':
                        from .network_retry import progress
                        notify=progress.get()
                        if notify:notify({'status':'running','waiting':False,'message':'正在重新连接模型。'})
                    if event.get('type')=='turn/end':end=event.get('data',{})
                    if event.get('type')=='turn/start':idle=False;end=None;saw_start=True
                if message.get('method')=='session.status':idle=params.get('status')=='idle'
                if accepted and saw_start and idle and end is not None:
                    reason=end.get('stopReason',end.get('reason'))
                    if isinstance(reason,dict):
                        failure=reason.get('error') or {}
                        code=failure.get('code');http=failure.get('status') or failure.get('statusCode')
                        if code in ('TRANSPORT','TIMEOUT','RATE_LIMIT','SERVER') or http in (408,425,429,500,502,503,504):
                            raise NetworkFailure(status_code=http)
                        reason=reason.get('kind')
                    if reason not in ('completed','stop','end_turn','done'):
                        raise RuntimeError('DeepSeek 制作未正常结束：'+str(reason))
                    record.update(status='completed',finished_at=time.time(),stop_reason=reason)
                    save(receipt,record);self.record('turn/completed',{'turnId':label});return record
        except SessionPaused:
            record.update(status='interrupted',finished_at=time.time());save(receipt,record);raise
        except BaseException as exc:
            record.update(status='failed' if end is not None else 'unknown',error_type=type(exc).__name__,
                          error=self.clean(str(exc)),finished_at=time.time());save(receipt,record);raise

    def close(self):
        if self.closed:return
        self.closed=True
        if self.process and self.process.poll() is None:
            try:self.send('shutdown')
            except (OSError,ValueError):pass
            try:self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
        self.server.shutdown();self.server.server_close()
        for name in ('reader_thread','diagnostic_thread'):
            thread=getattr(self,name,None)
            if thread:thread.join(timeout=2)
        if self.process:
            for stream in (self.process.stdin,self.process.stdout,self.process.stderr):
                if stream:stream.close()

    def __enter__(self):return self
    def __exit__(self,*_):self.close()
