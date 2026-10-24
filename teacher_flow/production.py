"""确认后的配音、逐场景渲染及恢复；由 Dify 的制作确认触发。"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import wave
import zipfile

from .common import (DEFAULT_VOICE_INSTRUCTION, PYTHON, TOOL, course_dir, digest, estimate_seconds, load,
                     lock, public_url, save, state, store, version)
from .engine import render, validate_board
from . import network_retry, tts_client

ACTIVE = set()
PRESENCE = {}
PRESENCE_LOCK = threading.Lock()


class Paused(Exception):
    pass


def touch(cid):
    with PRESENCE_LOCK:
        PRESENCE[cid] = time.time()


def present(cid):
    with PRESENCE_LOCK:
        return time.time() - PRESENCE.get(cid, 0) < 8


def update(cid, **fields):
    with lock(cid):
        s = state(cid)
        s["production"].update(fields)
        store(cid, s)


def checkpoint(cid):
    s = state(cid)
    if s["production"].get("pause_requested") or not present(cid):
        update(cid, status="paused", message="已暂停。点击「继续制作」接着做。", manual_resume=True)
        raise Paused()


def assert_approved(s):
    if s["approvals"].get("script") != version(s.get("approved_script", "")):
        raise ValueError("当前讲稿尚未确认")
    if s["approvals"].get("storyboard") != version(s.get("board", {})):
        raise ValueError("当前分镜尚未确认")
    validate_board(s["board"], s["approved_script"])


def start(cid):
    with lock(cid):
        s = state(cid)
        assert_approved(s)
        key = version({"script": s["approved_script"], "board": s["board"],
                       "voice_instruction": s["requirements"].get("voice_instruction")
                       or DEFAULT_VOICE_INSTRUCTION})
        current = s.get("production", {})
        if current.get("input_version") != key:
            s["production"] = {"input_version": key, "status": "armed",
                               "message": "正在准备制作。", "manual_resume": False}
            s["phase"] = "production"
            store(cid, s)
        elif current.get("status") == "complete":
            return monitor(cid)
        # 页面关闭后不会因再次显示图片自行恢复；须走control(continue)。
    return monitor(cid)


def maybe_launch(cid):
    with lock(cid):
        s = state(cid)
        p = s.get("production", {})
        if cid in ACTIVE or p.get("status") != "armed" or p.get("manual_resume"):
            return
        ACTIVE.add(cid)
    threading.Thread(target=run, args=(cid,), daemon=True, name=f"course-{cid[:8]}").start()


def sentence_chunks(text):
    pieces = re.findall(r".+?(?:[。！？!?](?:[”」』])?|$)", text, re.S)
    result = []
    for piece in pieces:
        piece = piece.strip()
        while len(piece) > 500:
            candidates = [piece.rfind(x, 1, 480) for x in "，；、,;"]
            end = max(candidates)
            end = end + 1 if end > 0 else 480
            result.append(piece[:end]); piece = piece[end:]
        if piece:
            result.append(piece)
    if re.sub(r"\s+", "", "".join(result)) != re.sub(r"\s+", "", text):
        raise ValueError("配音拆段改变了讲稿")
    return result


def audio_retry_info(cid, s=None):
    """从当前分镜和回执确定可以由用户重交的配音。"""
    s = s or state(cid)
    p = s.get("production", {})
    if p.get("status") != "failed" or cid in ACTIVE:
        return None
    if p.get("failed_step") != "audio" and not p.get("message", "").startswith("配音"):
        return None
    instruction = s.get("requirements", {}).get("voice_instruction") or DEFAULT_VOICE_INSTRUCTION
    folder = course_dir(cid) / "audio"
    completed, total, failed = 0, 0, []
    for i, scene in enumerate(s.get("board", {}).get("scenes", []), 1):
        for j, text in enumerate(sentence_chunks(scene.get("narration", "")), 1):
            total += 1
            name = "tts_" + digest({"text": text, "instruction": instruction, "voice": "longanlingxin"})[:24]
            record = folder / (name + ".json")
            if not record.exists():
                continue
            try:
                data = load(record)
            except (OSError, ValueError):
                return None
            if (data.get("text_sha256") != hashlib.sha256(text.encode()).hexdigest()
                    or data.get("voice") != "longanlingxin" or data.get("instruction") != instruction):
                return None
            if data.get("status") == "complete":
                if not (folder / (name + ".wav")).is_file():
                    return None
                completed += 1
            elif (data.get("status") == "needs_review" and network_retry.receipt_retryable(data)) or (
                    data.get("status") == "submitted" and p.get("failed_step") == "audio"):
                failed.append({"name": name, "scene": i, "sentence": j})
            else:
                return None
    if not failed:
        return None
    first = failed[0]
    return {"completed": completed, "total": total, "failed": failed,
            "message": f"第{first['scene']}段第{first['sentence']}句配音连接中断，已完成 {completed} / {total} 句。"
                       f"重试会重新提交未收到结果的{len(failed)}句，已完成音频继续复用。"}


def archive_audio_retry(cid, s, info):
    folder = course_dir(cid) / "audio"
    archive = folder / "attempts" / str(time.time_ns())
    archive.mkdir(parents=True, mode=0o700)
    names = list(dict.fromkeys(x["name"] for x in info["failed"]))
    for name in names:
        (folder / (name + ".json")).rename(archive / (name + ".json"))
    save(archive / "retry.json", {"action": "teacher_retry", "names": names,
                                "input_version": s["production"]["input_version"],
                                "previous_outcome": "unknown"})
    s["production"]["audio_retry_count"] = s["production"].get("audio_retry_count", 0) + 1


def join_wav(paths, target):
    parts = []
    config = None
    times = []
    elapsed = 0
    for path in paths:
        with wave.open(str(path), "rb") as src:
            current = (src.getnchannels(), src.getsampwidth(), src.getframerate())
            if config and config != current:
                raise ValueError("音频格式不一致")
            config = current
            frames = src.readframes(src.getnframes())
            seconds = src.getnframes() / src.getframerate()
            parts.append(frames); times.append((elapsed, elapsed + seconds)); elapsed += seconds
    with wave.open(str(target), "wb") as out:
        out.setnchannels(config[0]); out.setsampwidth(config[1]); out.setframerate(config[2])
        for frames in parts:
            out.writeframes(frames)
    return elapsed, times


def timed(t):
    ms = round(t * 1000)
    h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); sec, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{sec:02},{ms:03}"


def run(cid):
    root = course_dir(cid)
    try:
        checkpoint(cid)
        s = state(cid); assert_approved(s)
        instruction = s["requirements"].get("voice_instruction") or DEFAULT_VOICE_INSTRUCTION
        freeze = s["production"]["input_version"]
        audio_dir = root / "audio"; audio_dir.mkdir(exist_ok=True)
        build = root / "build" / freeze; build.mkdir(parents=True, exist_ok=True)
        scenes = s["board"]["scenes"]
        prepared = []
        for i, scene in enumerate(scenes):
            audios = []
            texts = sentence_chunks(scene["narration"])
            for j, text in enumerate(texts):
                checkpoint(cid)
                name = "tts_" + digest({"text": text, "instruction": instruction,
                                        "voice": "longanlingxin"})[:24]
                text_path = audio_dir / (name + ".txt")
                if not text_path.exists():
                    text_path.write_text(text)
                update(cid, status="running", retrying=False, message=f"配音：第{i+1}/{len(scenes)}段，第{j+1}/{len(texts)}句")
                try:
                    def audio_retry(event):
                        update(cid, retrying=True, retry_attempt=event['attempt'],
                               message=f"配音：第{i+1}/{len(scenes)}段，第{j+1}/{len(texts)}句。"+event['message'])
                    tts_client.synthesize(text,name,audio_dir,instruction,
                                          checkpoint=lambda:checkpoint(cid),on_retry=audio_retry)
                except Paused:
                    raise
                except Exception:
                    update(cid, failed_step="audio", failed_clip=name, failed_scene=i+1, failed_sentence=j+1)
                    raise
                wav = audio_dir / (name + ".wav")
                if not wav.exists():
                    raise RuntimeError("配音文件不存在")
                audios.append(wav)
            combined = build / (scene["id"] + ".wav")
            duration, times = join_wav(audios, combined)
            prepared.append({**scene, "duration_seconds": math.ceil((duration + 0.6) * 30) / 30,
                             "audio": str(combined), "cues": [
                                 {"text": text, "start": begin, "end": end}
                                 for text, (begin, end) in zip(texts, times)]})
        total = sum(x["duration_seconds"] for x in prepared)
        save(build / "timeline.json", prepared)
        target = float(s["requirements"]["duration_minutes"]) * 60
        if total > target and state(cid)["production"].get("accepted_duration") != round(total, 3):
            update(cid, status="duration_review", actual_seconds=round(total, 3),
                   message=f"预计成片{total/60:.2f}分钟，超过目标{target/60:g}分钟。")
            return
        for i, scene in enumerate(prepared):
            checkpoint(cid)
            update(cid, status="running", retrying=False, failed_step="animation",
                   message=f"制作画面：第{i+1}/{len(prepared)}段")
            html = root / "boards" / version(s["board"]) / (scene["id"] + ".html")
            output = build / (scene["id"] + ".mp4")
            signature = version({"scene": scene, "html": digest(html.read_bytes())})
            done = output.with_suffix(".done.json")
            if done.exists() and output.exists() and load(done).get("signature") == signature:
                continue
            for attempt in range(2):
                try:
                    render(cid, scene, html, output, mode="video", audio=scene["audio"],
                           cues=scene["cues"], ffmpeg=shutil.which("ffmpeg"),
                           progress=str(build / "render-progress.json"))
                    break
                except (RuntimeError, subprocess.TimeoutExpired):
                    if attempt or not present(cid):
                        raise
                    update(cid, message=f"第{i+1}段未完成，正在重试。")
            save(done, {"signature": signature})
        checkpoint(cid)
        update(cid, failed_step="export",message="正在合成视频和字幕。")
        final_dir = root / "deliverables" / freeze; final_dir.mkdir(parents=True, exist_ok=True)
        playlist = build / "concat.txt"
        playlist.write_text("\n".join("file '"+str(build/(x["id"]+".mp4"))+"'" for x in prepared))
        movie = final_dir / "lesson.mp4"
        subprocess.run([shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "concat", "-safe", "0", "-i", str(playlist), "-c", "copy",
                        "-movflags", "+faststart", str(movie)], check=True, capture_output=True, timeout=180)
        subtitles=[]; offset=0
        for scene in prepared:
            for cue in scene["cues"]:
                subtitles.append(f"{len(subtitles)+1}\n{timed(offset+cue['start'])} --> "
                                 f"{timed(offset+cue['end'])}\n{cue['text']}\n")
            offset += scene["duration_seconds"]
        (final_dir / "lesson.srt").write_text("\n".join(subtitles))
        (final_dir / "讲稿.txt").write_text(s["approved_script"])
        subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-i", str(movie),
                        "-f", "null", "-"], check=True, capture_output=True, timeout=300)
        with zipfile.ZipFile(final_dir / "制作工程.zip", "w", zipfile.ZIP_DEFLATED) as z:
            for folder in (root/"boards"/version(s["board"]), audio_dir):
                for file in folder.iterdir():
                    if file.is_file() and file.suffix in (".html",".png",".json",".txt",".wav"):
                        z.write(file, str(file.relative_to(root)))
            z.write(build/"timeline.json", "timeline.json")
            z.write(final_dir/"讲稿.txt", "讲稿.txt")
        update(cid, status="complete", message="视频已完成。", output_version=freeze,
               actual_seconds=round(total, 3),retrying=False)
    except Paused:
        pass
    except Exception as exc:
        update(cid, status="failed", message=str(exc)[:250], error_type=type(exc).__name__)
    finally:
        with lock(cid):
            ACTIVE.discard(cid)


def monitor(cid):
    s = state(cid); p = s.get("production", {})
    status = p.get("status", "not_started")
    view = "## 制作进度\n\n" + p.get("message", "尚未开始") + "\n\n"
    if status != "complete":
        view += f"![实时制作进度]({public_url()}/presence/{cid})\n\n"
        view += "关闭页面后，当前片段完成并保存，随后暂停。回来后点击「继续制作」。\n\n"
    if status == "duration_review":
        view += f"按已完成的配音计算，成片约{p['actual_seconds']/60:.2f}分钟。可选择「接受这个时长」或「修改讲稿」。\n\n"
    view += f"课程编号：`{cid}`"
    if s.get("notice"):
        view = "**" + s["notice"] + "**\n\n" + view
    return {"course_id": cid, "view": view, "done": status in ("complete", "needs_script"),
            "status": status, "version": p.get("input_version", "")}


def control(cid, action, expected_version):
    with lock(cid):
        s=state(cid); p=s["production"]
        if expected_version != p.get("input_version"):
            raise ValueError("课程内容已更新，请刷新进度")
        if action == "check":
            return monitor(cid)
        # 完成后的过期按钮不能把结果退回暂停，也不重新启动制作。
        if p.get("status") == "complete" and action in ("pause", "continue", "accept_duration"):
            return monitor(cid)
        if action == "pause":
            if p.get("status") not in ("armed", "running"):
                return monitor(cid)
            p["pause_requested"] = True
            if cid not in ACTIVE:
                p.update(status="paused",manual_resume=True,message="已暂停，进度保留。")
        elif action in ("continue", "accept_duration"):
            if p.get("status") == "failed":
                retry = audio_retry_info(cid, s) if action == "continue" else None
                local_retry = action=='continue' and p.get('failed_step') in ('animation','export') and cid not in ACTIVE
                if not retry and not local_retry:
                    raise ValueError("上次制作尚未完成，需先检查错误记录")
                if retry:
                    archive_audio_retry(cid, s, retry)
                for field in ("error_type", "failed_step", "failed_clip", "failed_scene", "failed_sentence"):
                    p.pop(field, None)
            if action == "accept_duration":
                if p.get("status") != "duration_review":
                    raise ValueError("当前没有待确认的时长变化")
                p["accepted_duration"] = p["actual_seconds"]
                s["requirements"]["duration_minutes"] = str(p["actual_seconds"]/60)
            if p.get("status") not in ("complete", "running") and (action=="accept_duration" or p.get("status")!="duration_review"):
                p.update(status="armed",manual_resume=False,pause_requested=False,
                         message="正在继续制作。")
        elif action == "revise":
            if cid in ACTIVE:
                raise ValueError("请先暂停制作，再修改讲稿")
            p.update(pause_requested=True,manual_resume=True)
            s["approvals"].pop("script",None);s["approvals"].pop("storyboard",None)
            s["phase"]="script"
            p["message"]="进度已保存。返回填写页，输入课程编号后可修改讲稿。"
            p["status"]="needs_script"
        elif action != "check":
            raise ValueError("操作不正确")
        s["production"]=p;store(cid,s)
    return monitor(cid)
