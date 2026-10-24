"""只提供本机 Dify 工具和课程素材，不另建教师前端。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import secrets
import os
import re
import signal
import threading
import time

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from PIL import Image, ImageDraw, ImageFont

from . import engine, production, production_ui, codex_jobs, stage_operations, network_retry
from .model_roles import default_roles
from .common import RUNTIME, bridge_config, course_dir, lock, public_url, state, store, load

app=FastAPI(title="教师微课本机工具", docs_url=None, redoc_url=None)
POOL=ThreadPoolExecutor(max_workers=2)
SHUTTING_DOWN=False


def authorize(value):
    expected=bridge_config()["token"]
    if not secrets.compare_digest(value or "", "Bearer "+expected):
        raise HTTPException(status_code=401, detail="本机工具鉴权失败")


def stream_operation(fn, *args):
    future=POOL.submit(stage_operations.execute,fn,*args)
    def chunks():
        # 定时空白保持本机HTTP连接；完整结果仍是一个JSON对象。
        while not future.done():
            yield b"\n"
            try: future.result(timeout=2)
            except TimeoutError: continue
            except Exception: break
        try:
            value={"ok":True,**future.result()}
        except Exception as exc:
            value={"ok":False,"error":str(exc)[:300],"error_type":type(exc).__name__,
                   "retryable":network_retry.is_network_error(exc)}
        yield json.dumps(value,ensure_ascii=False).encode()
    return StreamingResponse(chunks(),media_type="application/json",
                             headers={"Cache-Control":"no-store","X-Accel-Buffering":"no"})


@app.get("/health")
def health():
    return {"ok":True,"service":"teacher-flow","model":default_roles()['producer']['model'],
            "generation_on_install":False,"shutting_down":SHUTTING_DOWN,
            "storyboard_model":default_roles()['producer']['model'],
            "storyboard_backend":"codex" if codex_jobs.enabled() else "single_request"}


@app.get('/stage-status/{run_id}')
def stage_status(run_id:str):
    try:result=stage_operations.status_for_run(run_id)
    except ValueError:raise HTTPException(404)
    return JSONResponse(result,headers={'Cache-Control':'no-store',
        'Access-Control-Allow-Origin':'http://127.0.0.1:8788'})


@app.post('/api/materials/prepare')
def materials_prepare(payload:dict,authorization:str|None=Header(default=None)):
    authorize(authorization)
    return stream_operation(engine.prepare_materials, payload['course_id'])


def public_storyboard_status(cid):
    return codex_jobs.public_status(cid)


@app.get('/storyboard-status/{cid}')
def storyboard_status(cid:str,present:int=0):
    state(cid)
    if present:codex_jobs.touch(cid)
    return JSONResponse(public_storyboard_status(cid),headers={'Cache-Control':'no-store'})


@app.post('/storyboard-control/{cid}')
def storyboard_control(cid:str,payload:dict,request:Request):
    if request.headers.get('origin') != public_url():raise HTTPException(403)
    try:
        generation=payload.get('retry_generation')
        if payload.get('action')=='retry' and (type(generation) is not int or generation<0):
            raise ValueError('请刷新制作进度后重试。')
        codex_jobs.control(cid,payload['key'],payload['action'],generation)
    except (ValueError,KeyError) as exc:
        message=str(exc) if isinstance(exc,ValueError) else '制作状态已更新，请重新查看。'
        raise HTTPException(409,detail=message) from exc
    return JSONResponse(public_storyboard_status(cid),headers={'Cache-Control':'no-store'})


@app.post('/api/storyboard/resume')
def storyboard_resume(payload:dict,authorization:str|None=Header(default=None)):
    authorize(authorization)
    codex_jobs.control(payload['course_id'],payload['version'],'continue')
    return {'ok':True,'done':False,'course_id':payload['course_id']}


@app.get('/storyboard-panel/{cid}')
def storyboard_panel(cid:str,channel:str):
    state(cid)
    # 配置以JSON嵌入，防止参数成为HTML或脚本。
    config=json.dumps({'cid':cid,'channel':channel},ensure_ascii=True).replace('<','\\u003c')
    body=Path(__file__).with_name('storyboard-panel.html').read_text().replace('__CONFIG__',config)
    return HTMLResponse(body,headers={'Cache-Control':'no-store',
        'Content-Security-Policy':"frame-ancestors http://127.0.0.1:8788; default-src 'self'; "
            "script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'"})


@app.get('/storyboard-run-panel/{run_id}')
def storyboard_run_panel(run_id:str,channel:str):
    if not re.fullmatch(r'[a-f0-9-]{36}',run_id):raise HTTPException(404)
    mapping=RUNTIME/'workflow-runs'/(run_id+'.json')
    if not mapping.exists():raise HTTPException(404)
    return storyboard_panel(load(mapping)['course_id'],channel)


@app.post("/api/shutdown")
def shutdown(authorization:str|None=Header(default=None)):
    global SHUTTING_DOWN
    authorize(authorization)
    SHUTTING_DOWN=True
    for cid in list(production.ACTIVE):
        production.update(cid,pause_requested=True,message="当前片段保存后停止。")
    def finish():
        while production.ACTIVE:
            time.sleep(.5)
        os.kill(os.getpid(),signal.SIGTERM)
    threading.Thread(target=finish,daemon=True).start()
    return {"ok":True,"message":"当前片段保存后停止本机工具。"}


@app.post("/api/new")
def create(payload:dict,authorization:str|None=Header(default=None)):
    authorize(authorization)
    if SHUTTING_DOWN:raise HTTPException(503,detail="正在保存并退出")
    return {"ok":True,**engine.new_course(payload)}


@app.post("/api/{stage}/show")
def show(stage:str,payload:dict,producer:str='',authorization:str|None=Header(default=None)):
    authorize(authorization)
    if stage=="production":
        return {"ok":True,**production.monitor(payload["course_id"])}
    return stream_operation(engine.show,payload["course_id"],stage,producer)

@app.post("/api/script/prepare/{step}")
def prepare_script(step:str,payload:dict,authorization:str|None=Header(default=None)):
    authorize(authorization)
    if SHUTTING_DOWN:raise HTTPException(503,detail="正在保存并退出")
    return stream_operation(engine.prepare_script,payload["course_id"],step)


@app.post("/api/style/prepare")
def prepare_style(payload:dict,authorization:str|None=Header(default=None)):
    authorize(authorization)
    if SHUTTING_DOWN:raise HTTPException(503,detail="正在保存并退出")
    return stream_operation(engine.prepare_references,payload["course_id"])


@app.post("/api/{stage}/apply")
def apply(stage:str,payload:dict,authorization:str|None=Header(default=None)):
    authorize(authorization)
    try:
        if stage=="production":
            return {"ok":True,**production.control(payload["course_id"],payload["action"],payload["version"])}
        return {"ok":True,**engine.apply(payload["course_id"],stage,payload)}
    except ValueError as exc:
        # 表单输入或版本问题返回到本轮审核，不调用模型。
        with lock(payload["course_id"]):
            s=state(payload["course_id"]);s["notice"]=str(exc);store(payload["course_id"],s)
        return {"ok":True,"done":False,"course_id":payload["course_id"],"view":str(exc)}


@app.post("/api/production/start")
def begin(payload:dict,authorization:str|None=Header(default=None)):
    authorize(authorization)
    return {"ok":True,**production.start(payload["course_id"])}


@app.post("/api/result")
def result(payload:dict,authorization:str|None=Header(default=None)):
    authorize(authorization)
    cid=payload["course_id"];s=state(cid);p=s["production"]
    if p.get("status")=="needs_script":
        return {"ok":True,"view":f"## 修改讲稿\n\n进度已保存。返回填写页，在「课程编号」中填入 `{cid}`，点击「运行」后修改讲稿。"}
    if p.get("status")!="complete":
        return {"ok":False,"error":"成片尚未完成，不能交付"}
    base=f"{public_url()}/assets/{cid}/deliverables/{p['output_version']}"
    return {"ok":True,"view":f"## 视频已完成\n\n"
            f"<video src=\"{base}/lesson.mp4\" controls></video>\n\n"
            f"[下载视频]({base}/lesson.mp4) · [下载字幕]({base}/lesson.srt) · "
            f"[下载制作文件]({base}/制作工程.zip)\n\n课程编号：`{cid}`"}


@app.get("/assets/{cid}/{relative:path}")
def asset(cid:str,relative:str):
    root=course_dir(cid).resolve();path=(root/relative).resolve()
    if not path.is_relative_to(root) or path.suffix.lower() not in (".png",".jpg",".wav",".mp4",".srt",".zip"):
        raise HTTPException(404)
    if not path.is_file(): raise HTTPException(404)
    return FileResponse(path,filename=path.name if path.suffix in (".srt",".zip") else None)


@app.get("/presence/{cid}")
def presence(cid:str):
    state(cid)
    def frames():
        font_path=Path(os.environ.get("TEACHER_FONT_PATH", "/System/Library/Fonts/STHeiti Medium.ttc"))
        font=ImageFont.truetype(str(font_path),23) if font_path.exists() else ImageFont.load_default()
        while not SHUTTING_DOWN:
            production.touch(cid)
            production.maybe_launch(cid)
            p=state(cid).get("production",{})
            image=Image.new("RGB",(760,110),"#eef2f7")
            draw=ImageDraw.Draw(image)
            text=p.get("message","等待制作")
            lines=[text[i:i+29] for i in range(0,min(len(text),87),29)]
            draw.multiline_text((20,18),"\n".join(lines),font=font,fill="#17283f",spacing=6)
            buf=io.BytesIO();image.save(buf,format="JPEG")
            data=buf.getvalue()
            yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "+str(len(data)).encode()+b"\r\n\r\n"+data+b"\r\n"
            time.sleep(1)
    return StreamingResponse(frames(),media_type="multipart/x-mixed-replace; boundary=frame",
                             headers={"Cache-Control":"no-store","X-Accel-Buffering":"no"})


@app.get("/production-status/{cid}")
def production_status(cid:str):
    return JSONResponse(production_ui.snapshot(cid),headers={"Cache-Control":"no-store"})


@app.get("/production-panel/{cid}")
def production_panel(cid:str,channel:str):
    state(cid)
    return HTMLResponse(production_ui.panel_html(cid,channel),headers={
        "Cache-Control":"no-store",
        "Content-Security-Policy":"frame-ancestors http://127.0.0.1:8788; default-src 'self'; "
                                  "script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                                  "img-src 'self'; media-src 'self'; connect-src 'self'",
    })
