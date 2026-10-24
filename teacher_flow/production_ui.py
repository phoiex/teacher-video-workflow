"""制作进度的只读展示契约；操作由父页面提交给Dify原审核接口。"""
import json
from pathlib import Path
import re

from .common import course_dir, load, public_url, state
from .production import audio_retry_info


def snapshot(cid):
    s = state(cid)
    p = s.get("production", {})
    status = p.get("status", "not_started")
    total = len(s.get("board", {}).get("scenes", []))
    build = course_dir(cid) / "build" / str(p.get("input_version", ""))
    completed = len(list(build.glob("*.done.json"))) if build.is_dir() else 0
    message = str(p.get("message") or "")
    phase = ("audio" if message.startswith("配音") else
             "export" if "合成" in message else "animation")
    progress = 0
    if phase == "animation":
        progress = completed / max(1, total)
    elif phase == "audio":
        match = re.search(r"第(\d+)/(\d+)段", message)
        progress = (int(match[1]) - 1) / max(1, total) if match else 0
    titles = {"audio": "正在合成配音", "animation": "正在制作动画", "export": "正在导出并检查视频"}
    if status == "running" and phase == "animation":
        message = f"已完成 {completed} / {total} 段动画。"
    elif status == "running" and phase == "export":
        message = "正在合并片段、整理字幕，并检查视频能否完整播放。"
    actions = {
        "armed": ["pause"], "running": ["pause"], "paused": ["continue"],
        "duration_review": ["accept_duration", "revise"],
        "complete": [], "needs_script": [], "failed": [],
    }.get(status, [])
    if p.get("pause_requested") and status in ("armed", "running"):
        actions = []
        message = "当前片段保存后暂停。"
    result = {"status": status, "title": titles.get(phase, "正在制作"),
              "message": message, "completed_segments": completed, "total_segments": total,
              "progress": min(100, max(0, round(progress * 100))),
              "actions": actions, "actual_seconds": p.get("actual_seconds"),
              "target_seconds": float(s.get("requirements", {}).get("duration_minutes") or 0) * 60,
              "phase": phase, "files": {}}
    if status=='running' and p.get('retrying'):
        result.update(title='网络连接正在重试',message=p.get('message','正在重试。'))
    if status == "complete":
        output = str(p.get("output_version", ""))
        folder = course_dir(cid) / "deliverables" / output
        for name in ("lesson.mp4", "lesson.srt", "制作工程.zip"):
            if (folder / name).is_file():
                result["files"][name] = f"{public_url()}/assets/{cid}/deliverables/{output}/{name}"
        result.update(title="视频已完成", message="可以播放或下载成片。", progress=100)
    elif status == "paused":
        result.update(title="制作已暂停", message="已完成的片段已保存，点击继续后接着制作。")
    elif status == "duration_review":
        result.update(title="需要确认视频时长")
    elif status == "failed":
        result.update(title="制作遇到问题")
        retry = audio_retry_info(cid, s)
        if retry:
            result.update(title="配音连接中断", message=retry["message"], actions=["continue"],
                          action_labels={"continue": "重试未完成配音"}, phase="audio",
                          audio_completed=retry["completed"], audio_total=retry["total"])
        elif p.get('failed_step') in ('animation','export'):
            result.update(actions=['continue'],action_labels={'continue':'从已保存进度重试'})
    elif status == "armed":
        result.update(title="正在准备制作", message="正在读取已确认的讲稿和分镜。")
    elif status == "needs_script":
        result.update(title="返回讲稿修改")
    return result


def panel_html(cid, channel):
    course_dir(cid)
    if not re.fullmatch(r"[a-zA-Z0-9_-]{8,80}", channel):
        raise ValueError("页面标识不正确")
    return (Path(__file__).with_name("production-panel.html").read_text()
            .replace("__COURSE__", json.dumps(cid))
            .replace("__CHANNEL__", json.dumps(channel)))
