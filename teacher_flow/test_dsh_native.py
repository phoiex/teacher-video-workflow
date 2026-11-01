"""原生 DSH 连接本地模拟模型；验证工具、保存恢复和暂停，不调用外部 API。"""
import base64
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from . import dsh_runtime,model_roles,model_call,dsh_call,common,engine
from .codex_runtime import tool,text_result,SessionPaused


class FakeModel:
    def __init__(self,responder):
        self.requests=[];self.responder=responder;self.received=threading.Event()
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def file_reply(self):
                data=json.dumps({'id':'file-local-fixture','object':'file','bytes':100,'created_at':int(time.time()),
                    'filename':'fixture.png','purpose':'user_data','expires_at':int(time.time())+86400}).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(data)
            def do_GET(self):
                if self.path.startswith('/files/'):return self.file_reply()
                self.send_error(404)
            def do_POST(self):
                body=self.rfile.read(int(self.headers['Content-Length']))
                if self.path=='/files':return self.file_reply()
                assert self.path=='/chat/completions',self.path
                packet=json.loads(body);owner.requests.append(packet);owner.received.set()
                output=owner.responder(packet,len(owner.requests))
                if output=='block':
                    owner.release.wait(15)
                    output={'content':'停止前的测试回复。'}
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                frames=[{'id':'local-fixture','object':'chat.completion.chunk','created':int(time.time()),
                         'model':'deepseek-flash','choices':[{'index':0,'delta':{'role':'assistant',**output},'finish_reason':None}]},
                        {'id':'local-fixture','object':'chat.completion.chunk','created':int(time.time()),
                         'model':'deepseek-flash','choices':[{'index':0,'delta':{},'finish_reason':'tool_calls' if 'tool_calls' in output else 'stop'}],
                         'usage':{'prompt_tokens':100,'completion_tokens':20,'total_tokens':120}}]
                try:
                    for frame in frames:self.wfile.write(('data: '+json.dumps(frame)+'\n\n').encode());self.wfile.flush()
                    self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
                except (BrokenPipeError,ConnectionResetError):pass
        self.release=threading.Event();self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.access={'api_key':'local-fixture-key','base_url':f'http://127.0.0.1:{self.server.server_port}'}
    def close(self):
        self.release.set();self.server.shutdown();self.server.server_close()


def call(name,args):
    return {'tool_calls':[{'index':0,'id':'tool-fixture','type':'function',
                          'function':{'name':name,'arguments':json.dumps(args,ensure_ascii=False)}}]}


@unittest.skipUnless((dsh_runtime.INSTALL/'manifest.json').exists(),'需要课程私有 DSH 运行时')
class NativeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)

    def test_tools_images_and_same_native_session_after_restart(self):
        from PIL import Image
        data=io.BytesIO();Image.new('RGB',(16,16),'green').save(data,format='PNG')
        image='data:image/png;base64,'+base64.b64encode(data.getvalue()).decode()
        model=FakeModel(lambda p,n:call('probe',{}) if n==1 else {'content':'上下文已收到。'})
        self.addCleanup(model.close)
        calls=[]
        def handler(name,args):
            calls.append(name)
            return {'success':True,'contentItems':[{'type':'inputText','text':'CONTINUITY_MARK_731'},
                                                  {'type':'inputImage','imageUrl':image}]}
        with dsh_runtime.Session(self.folder,'使用提供的工具。',[tool('probe','取得测试图',{})],handler,access=model.access) as s:
            sid=s.thread_id;record=s.run('first','调用 probe 查看图像。')
        self.assertEqual(record['status'],'completed');self.assertEqual(calls,['probe'])
        self.assertIn('image_url',json.dumps(model.requests[-1]))
        with dsh_runtime.Session(self.folder,'使用提供的工具。',[tool('probe','取得测试图',{})],handler,access=model.access) as s:
            self.assertEqual(s.thread_id,sid);s.run('second','接着上一轮继续。')
        self.assertIn('CONTINUITY_MARK_731',json.dumps(model.requests[-1],ensure_ascii=False))
        self.assertEqual(len(model.requests),3)

    def test_pause_stops_only_owned_runtime_and_keeps_session(self):
        model=FakeModel(lambda p,n:'block');self.addCleanup(model.close)
        stop=threading.Event()
        with dsh_runtime.Session(self.folder,'测试暂停。',[],lambda *_:text_result({}),
                                 pause_requested=stop.is_set,access=model.access) as s:
            thread=threading.Thread(target=lambda:(model.received.wait(15),stop.set()),daemon=True);thread.start()
            start=time.monotonic()
            with self.assertRaises(SessionPaused):s.run('pause','等待测试。')
            self.assertLess(time.monotonic()-start,12)
            self.assertIsNotNone(s.process.poll())
        self.assertEqual(common.load(self.folder/'turns/pause.json')['status'],'interrupted')
        self.assertTrue(common.load(self.folder/'dsh-session.json')['opened'])
        model.release.set();model.responder=lambda *_:{'content':'接着上次完成。'}
        with dsh_runtime.Session(self.folder,'测试暂停。',[],lambda *_:text_result({}),access=model.access) as resumed:
            resumed.run('continued','继续上一次任务。')
        self.assertIn('等待测试。',json.dumps(model.requests[-1],ensure_ascii=False))

    def test_all_content_roles_route_through_harness_and_reuse_result(self):
        roles={r:{'provider':'deepseek','model':'deepseek-flash','protocol':'chat.completions','harness':'deepseek'}
               for r in ('planner','writer','editor','producer')}
        model_roles.validate(roles)
        model=FakeModel(lambda p,n:call('submit_result',{'result_json':'{"ok":true}'}) if n%2 else {'content':'已保存。'})
        self.addCleanup(model.close)
        token=model_roles.CURRENT.set(roles);self.addCleanup(model_roles.CURRENT.reset,token)
        with patch.object(dsh_call,'RUNTIME',self.folder), \
             patch('teacher_flow.model_connections.connection',return_value=model.access), \
             patch('openai.OpenAI',side_effect=AssertionError('不应走普通 API 客户端')):
            for stage in ('teacher-intake-v1','teacher-script-plan-v1','teacher-script-draft-v2','teacher-script-deslop-v1',
                          'course-material-knowledge-v1','teacher-style-reference-v1'):
                self.assertEqual(model_call.generate(stage,'返回 JSON 对象。',{'fixture':stage}),{'ok':True})
                self.assertEqual(model_call.generate(stage,'返回 JSON 对象。',{'fixture':stage}),{'ok':True})
        self.assertEqual(len(model.requests),12)

    def test_native_storyboard_tools_render_and_view_real_frame(self):
        from .codex_storyboard import produce
        script='信息按权重汇总。'
        html='''<!doctype html><meta charset="utf-8"><body style="background:#101927;color:#8ff">
<h1 id="title" style="font-size:72px;margin:200px 120px"></h1><script>
window.film={frame(t){document.querySelector('#title').textContent=SCENE.caption}};</script>'''
        work=self.folder/'work'
        def respond(packet,n):
            if n==1:return call('course_read',{})
            if n==2:return call('course_plan',{'visual_direction':'ASCII 终端','scenes':[
                {'id':'s01','narration':script,'caption':'加权汇总','animation':'显示标题。'}]})
            if n==3:return {'content':'计划已保存。'}
            if n==4:return call('course_scene',{'scene_id':'s01'})
            if n==5:return call('course_write',{'scene_id':'s01','html':html})
            if n==6:return call('course_render',{'scene_id':'s01'})
            if n==7:return call('view_image',{'path':str(next((work/'frames').rglob('*.png')))})
            return {'content':'画面已保存。'}
        model=FakeModel(respond);self.addCleanup(model.close)
        profile={'provider':'deepseek','model':'deepseek-flash','protocol':'chat.completions','harness':'deepseek'}
        inputs={'script':script,'requirements':{},'style_instructions':'使用 ASCII 终端风格。','producer_profile':profile}
        with patch('teacher_flow.model_connections.connection',return_value=model.access), \
             patch('teacher_flow.codex_runtime.Session.__init__',side_effect=AssertionError('不应启动 Codex')):
            board=produce(work,self.folder/'session',inputs)
        self.assertEqual(board['scenes'][0]['narration'],script)
        self.assertEqual(board['scenes'][0]['html'],html)
        self.assertTrue(list((work/'frames').rglob('*.png')))
        self.assertEqual(len(model.requests),8)

    def test_branch_cannot_resume_other_harness_course(self):
        roles={r:{'provider':'deepseek','model':'deepseek-flash','protocol':'chat.completions','harness':'deepseek'}
               for r in ('planner','writer','editor','producer')}
        with patch.object(common,'COURSES',self.folder/'courses'):
            old=engine.new_course({'requirement':'旧流程课程'})['course_id']
            with self.assertRaisesRegex(ValueError,'其他制作流程'):
                engine.new_course({'resume_course':old,'model_roles':roles})
            current=engine.new_course({'requirement':'新流程课程','model_roles':roles})['course_id']
            self.assertEqual(engine.new_course({'resume_course':current,'model_roles':roles})['course_id'],current)


if __name__=='__main__':unittest.main()
