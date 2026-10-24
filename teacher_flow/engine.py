"""课程状态和审核契约；审核提交必须对应当前展示版本。"""
from __future__ import annotations

import copy
import json
import math
import re
import subprocess
import time
from pathlib import Path

from . import model_call, prompts, style_references, styles, codex_jobs, materials, network_retry
from .common import (COURSES, DEFAULT_VOICE_INSTRUCTION, RENDER_RUNTIME, NODE, RUNTIME, TOOL, archive, course_dir, digest,
                     estimate_seconds, lock, public_url, save, state, store, version)

FIELDS = ["topic", "audience", "duration_minutes", "objectives", "prerequisites", "style", "style_preset",
            "voice_instruction", "production_mode", "approved_script", "feedback", "screen_text", "knowledge_selection"]


def normalize(text):
    return re.sub(r"\s+", "", text)


def new_course(payload):
    from .model_roles import validate as validate_models, default_roles
    models = validate_models(payload.get('model_roles')) or default_roles()
    text = str(payload.get("requirement") or "").strip()
    source_files = materials.validate_files(payload.get('source_files'))
    if not text and not source_files and not payload.get('resume_course'):
        raise ValueError("请描述课程要求，或上传PDF、PPTX课件。")
    if not text:
        text = '根据上传课件准备讲解课程。'
    resume = str(payload.get("resume_course") or "").strip()
    if resume:
        saved = state(resume)
        bind_run(payload.get('run_id'), resume)
        return {"course_id": resume, "notice": "课程已打开", "phase": saved["phase"]}
    style_preset = styles.validate_preset(payload.get("style_preset"))
    references = style_references.validate_files(payload.get("style_files"))
    cid = digest({"run": payload.get("run_id") or time.time_ns(), "requirement": text})[:24]
    with lock(cid):
        if not (course_dir(cid) / "state.json").exists():
            store(cid, {"id": cid, "requirement": text,
                        "source_text": str(payload.get("source_text") or ""),
                        "source_files": source_files,
                        "knowledge_focus": str(payload.get('knowledge_focus') or '').strip(),
                        "existing_script": str(payload.get("existing_script") or ""),
                        "style_preset": style_preset,
                        "style_notes": str(payload.get("style_notes") or "").strip(),
                        "style_files": references,
                        "style_preview_version": 1,
                        **({'model_roles': models} if models else {}),
                        "phase": "requirements", "created_at": time.time(),
                        "approvals": {}, "errors": [], "production": {}})
    bind_run(payload.get('run_id'), cid)
    return {"course_id": cid, "notice": "课程已建立", "phase": "requirements"}


def bind_run(run_id, cid):
    if isinstance(run_id, str) and re.fullmatch(r'[a-f0-9-]{36}', run_id):
        save(RUNTIME / 'workflow-runs' / (run_id + '.json'), {'course_id': cid})


def response(cid, content, fields=None, done=False):
    return {"course_id": cid, "view": content, "done": done,
            "version": state(cid).get("display_version", ""),
            **{name: str((fields or {}).get(name, "")) for name in FIELDS}}


def prepare_materials(cid):
    with lock(cid):
        s = state(cid)
        if not s.get('source_files'):
            return response(cid, '按填写的课程要求继续。', done=True)
        if s.get('materials', {}).get('status') == 'complete':
            return response(cid, '课件知识点已整理。', done=True)
        prepared = materials.extract(cid, s['source_files'])
        prepared['knowledge_points'] = materials.catalog(prepared, s.get('knowledge_focus', ''))
        prepared['status'] = 'complete'
        s['materials'] = prepared
        archive(cid, 'materials', prepared)
        store(cid, s)
        return response(cid, '课件知识点已整理，请选择本次讲解范围。', done=True)

def prepare_references(cid):
    """复用已完成的风格说明；网络中断后沿保存的素材继续。"""
    with lock(cid):
        s = state(cid)
        if not s.get("style_files") or s["approvals"].get("requirements"):
            return response(cid, "未提供参考素材，按当前风格继续。", done=True)
        if s.get("style_reference") and not s["style_reference"].get('retryable'):
            return response(cid, "参考素材处理记录已保留。", done=True)
        prepared = style_references.prepare(cid, s["style_files"])
        result = {"status": "unavailable", "assets": prepared["assets"], "issues": prepared["issues"]}
        s["style_reference"] = result
        store(cid, s)
        if not prepared["images"]:
            return response(cid, "参考素材未能读取，请在课程要求中补充风格说明。", done=True)
        result["status"] = "analyzing"
        store(cid, s)
        try:
            raw = model_call.generate("teacher-style-reference-v1", prompts.assemble("style_reference"), {
                "course_request": s["requirement"], "style_preset": s.get("style_preset", ""),
                "teacher_preferences": s.get("style_notes", ""), "assets": prepared["assets"],
                "frames": [{k: v for k, v in image.items() if k != "path"} for image in prepared["images"]],
            }, images=prepared["images"])
            archive(cid, "style_reference_raw", raw)
            result["description"] = style_references.style_description(
                raw, {image["image_id"] for image in prepared["images"]})
            result["status"] = "partial" if result["issues"] else "complete"
        except network_retry.NetworkFailure:
            result.update(status='network_error', retryable=True)
            store(cid, s)
            raise
        except Exception:
            result["status"] = "unavailable"
            result["issues"].append({"name": "风格提炼",
                "message": "未取得完整风格说明，已保留素材和处理记录。可在下方自行填写。"})
        archive(cid, "style_reference", result)
        store(cid, s)
        return response(cid, "参考素材已处理，请核对风格说明。", done=True)


def prepare_script(cid, step):
    """分开保存初稿和表达修改结果；当前审核稿与老师原稿不自动改写。"""
    if step not in ("plan", "draft", "deslop"):
        raise ValueError("讲稿步骤不正确")
    with lock(cid):
        s = state(cid)
        if not s["approvals"].get("requirements"):
            raise ValueError("请先确认课程要求")
        if s["approvals"].get("script") or ("draft" in s and not s.get("script_feedback")):
            return response(cid, "已有讲稿已保留。", done=True)
        if s["existing_script"] and "draft" not in s and not s.get("script_feedback"):
            s["draft"] = {"title": s["requirements"]["topic"], "script": s["existing_script"],
                          "added_content": [], "teacher_message": ""}
            archive(cid, "script", s["draft"])
            store(cid, s)
            return response(cid, "已读取原讲稿。", done=True)

        inputs = {"requirements": s["requirements"], "materials": s["source_text"],
                  "previous_script": s.get("draft", {}).get("script", s["existing_script"]),
                  "feedback": s.get("script_feedback", "")}
        source_images = []
        if s.get('materials'):
            inputs['courseware'], source_images = materials.selected_content(
                s['materials'], s['requirements'].get('knowledge_ids', []))
        input_version = version(inputs)
        job = s.get("script_job", {})
        if step == 'plan':
            if job.get('input_version') != input_version or not job.get('plan'):
                job = {'input_version':input_version, 'status':'planning',
                       'pipeline':'plan_write_deslop_v1'}
                s['script_job']=job;store(cid,s)
                plan=model_call.generate('teacher-script-plan-v1',prompts.assemble('script_plan'),
                                         inputs,images=source_images)
                if not isinstance(plan,dict) or not plan.get('sequence'):
                    raise ValueError('教学安排未返回完整结果。')
                job.update(plan=plan,status='awaiting_draft')
                archive(cid,'teaching_plan',plan);store(cid,s)
            return response(cid,'教学安排已保存，准备写稿。',done=True)
        if step == "draft":
            if job.get("input_version") != input_version or "raw" not in job:
                job = {**(job if job.get('input_version') == input_version else {}),
                       "input_version": input_version, "status": "writing",
                       "pipeline": "plan_write_deslop_v1" if job.get('plan') else "write_then_deslop_v1"}
                s["script_job"] = job
                store(cid, s)
                writer_inputs={**inputs, **({'teaching_plan':job['plan']} if job.get('plan') else {})}
                raw = model_call.generate("teacher-script-draft-v2", prompts.assemble("script"), writer_inputs, images=source_images)
                if not isinstance(raw, dict) or not isinstance(raw.get("script"), str) or not raw["script"].strip():
                    raise ValueError("未收到完整讲稿初稿，请查看错误记录")
                job.update(raw=raw, raw_version=version(raw), status="awaiting_deslop")
                archive(cid, "script_raw", raw)
                store(cid, s)
            return response(cid, "初稿已保存。", done=True)

        if job.get("input_version") != input_version or not job.get("raw"):
            raise ValueError("请先完成讲稿初稿")
        job["status"] = "editing_expression"
        store(cid, s)
        edited = model_call.generate("teacher-script-deslop-v1", prompts.assemble("script_deslop"), {
            "requirements": s["requirements"], "draft": job["raw"],
        })
        if not isinstance(edited, dict) or not isinstance(edited.get("script"), str) or not edited["script"].strip():
            raise ValueError("表达修改未返回完整讲稿，初稿已保留")
        s["draft"] = {**job["raw"], "script": edited["script"].strip(),
                      "teacher_message": str(edited.get("teacher_message") or "")}
        s.pop("script_feedback", None)
        job.update(status="complete", final_version=version(s["draft"]))
        archive(cid, "script_deslopped", s["draft"])
        archive(cid, "script", s["draft"])
        store(cid, s)
        return response(cid, "讲稿已准备好，可以审核。", done=True)


def show(cid, stage, producer=''):
    with lock(cid):
        s = state(cid)
        if stage == "requirements":
            if s.get('source_files') and s.get('materials', {}).get('status') != 'complete':
                raise ValueError('请先完成课件解析，再确认讲解范围。')
            if "intake" not in s:
                s["intake"] = model_call.generate("teacher-intake-v1", prompts.assemble("intake"), {
                    "requirement": s["requirement"], "materials": s["source_text"],
                    "courseware_knowledge": s.get('materials', {}).get('knowledge_points', []),
                    "knowledge_focus": s.get('knowledge_focus', ''),
                    "has_existing_script": bool(s["existing_script"]),
                })
                store(cid, s)
            data = copy.deepcopy(s.get("requirements") or s["intake"])
            if not s.get("requirements"):
                notes = [str(data.get("style") or ""), s.get("style_notes", ""),
                         s.get("style_reference", {}).get("description", "")]
                data["style"] = "\n\n".join(dict.fromkeys(item for item in notes if item))
                data["style_preset"] = s.get("style_preset") or ("自定义" if data["style"] else "自由设计")
            data["voice_instruction"] = data.get("voice_instruction") or DEFAULT_VOICE_INSTRUCTION
            rows = [f"| {label} | {str(data.get(name, '')) or '待补充'} |" for name, label in [
                ("topic","主题"),("audience","授课对象"),("duration_minutes","视频时长（分钟）"),
                ("objectives","教学目标"),("prerequisites","学生基础"),
                ("voice_instruction","语速和语气")]]
            message = s["intake"].get("teacher_message", "")
            questions = s["intake"].get("questions") or []
            view = "## 课程要求\n\n" + message + "\n\n| 项目 | 内容 |\n|---|---|\n" + "\n".join(rows)
            if questions:
                view += "\n\n还需补充：\n" + "\n".join("- "+str(q) for q in questions)
            if not data.get("style") and data.get("style_preset") == "自由设计":
                view += "\n\n未指定画面风格，将按课程内容设计。"
            view += f"\n\n### 画面风格\n\n当前选择：**{data.get('style_preset') or '自定义'}**。\n\n"
            view += styles.choices_markdown()
            reference = s.get("style_reference", {})
            if reference.get("assets"):
                view += "\n\n### 参考素材\n\n"
                for asset in reference["assets"]:
                    label = asset["name"].replace("\n", " ")
                    if asset["kind"] == "video":
                        times = "、".join(f"{t:g}" for t in asset["sample_times"])
                        view += f"- {label}：抽看 {times} 秒的连续画面；动效说明以这些片段为依据。\n"
                    else:
                        view += f"- {label}：已读取图片。\n"
            if reference.get("status") == "analyzing":
                view += "\n\n参考风格提炼尚无完整结果，已保留记录，不会重复请求。"
            for issue in reference.get("issues", []):
                view += f"\n\n{issue['name']}：{issue['message']}"
            fields = data
            if not s.get('materials'):
                fields['knowledge_selection'] = data.get('knowledge_focus', s.get('knowledge_focus', ''))
            if s.get('materials'):
                material = s['materials']
                view = '## 上传课件\n\n' + '\n'.join(
                    f'- {d["name"]}：{d["pages"]}页' for d in material['documents']) + '\n\n' + view
                if material.get('issues'):
                    view += '\n\n### 材料中需核对的内容\n\n' + '\n'.join('- '+x for x in material['issues'])
                fields['knowledge_selection'] = materials.selection_value(material, data.get('knowledge_ids'))
        elif stage == "script":
            # 兼容正在运行的旧版流程；新版画布在此前分别调用两步。
            prepare_script(cid, "draft")
            prepare_script(cid, "deslop")
            s = state(cid)
            draft = s["draft"]; text = draft.get("script", "").strip()
            if not text:
                raise ValueError("未收到讲稿，请查看错误记录")
            seconds = estimate_seconds(text)
            target = float(s["requirements"]["duration_minutes"]) * 60
            s["draft_estimate"] = seconds
            view = f"## 讲稿\n\n**{draft.get('title','')}**\n\n{text}\n\n"
            view += f"目标时长 {target/60:g} 分钟，预计 {seconds/60:.1f} 分钟。\n\n"
            if seconds > target:
                view += f"预计超出约 {seconds-target:.0f} 秒。接受这个时长可点「确认讲稿和时长」；需要缩短时，在修改意见中说明。\n\n"
            added = draft.get("added_content") or []
            if added:
                view += "材料之外补充了：\n" + "\n".join("- "+str(x) for x in added) + "\n\n"
            view += draft.get("teacher_message", "")
            fields = {"approved_script": text}
        elif stage == "storyboard":
            if not s["approvals"].get("script"):
                raise ValueError("请先确认讲稿")
            needs_board = "board" not in s or bool(s.get("board_feedback"))
            if needs_board and producer == 'codex' and codex_jobs.enabled():
                progress, board = codex_jobs.poll(cid, s)
                if board is None:
                    return {**response(cid, progress['message'], done=False), 'ready': False,
                            'paused': progress['status'] == 'paused', 'version': progress['key']}
                validate_board(board, s['approved_script'])
                save_board(cid, board)
                s['board'] = board
                s['storyboard_backend'] = 'codex-sdk-0.154.0'
                s.pop('board_feedback', None)
                archive(cid, 'storyboard', board)
            elif needs_board:
                feedback = s.pop("board_feedback", "")
                s["board"] = model_call.generate("teacher-storyboard-v1",
                    prompts.assemble("storyboard", s["requirements"].get("style", ""),
                                     s["requirements"].get("style_preset", "")), {
                        "requirements": s["requirements"], "script": s["approved_script"],
                        "previous_storyboard": s.get("board"), "feedback": feedback,
                    })
                archive(cid, "storyboard_candidate", s["board"])
                try:
                    validate_board(s["board"], s["approved_script"])
                    save_board(cid, s["board"])
                except (ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
                    # 已取得完整回复后的明确结构/渲染失败才修复一次；
                    # 调用结果未知时由上层保存状态，此处只修复内容结构。
                    errors = list((course_dir(cid)/"boards"/version(s["board"])).glob("*.error.txt"))
                    detail = errors[-1].read_text(errors="replace")[-4000:] if errors else str(exc)
                    s["board"] = model_call.generate("teacher-storyboard-repair-v1",
                        prompts.assemble("storyboard", s["requirements"].get("style", ""),
                                         s["requirements"].get("style_preset", "")), {
                            "requirements": s["requirements"], "script": s["approved_script"],
                            "previous_storyboard": s["board"], "feedback": feedback,
                            "render_or_contract_error": detail,
                            "repair_instruction": "仅修正本次明确错误，保持已确认口述，修复后返回完整分镜JSON。"})
                    archive(cid, "storyboard_repair", s["board"])
                    validate_board(s["board"], s["approved_script"])
                    save_board(cid, s["board"])
                archive(cid, "storyboard", s["board"])
            elif s.pop("captions_changed", False):
                save_board(cid, s["board"])
            if s["requirements"]["production_mode"] == "直接制作":
                s["approvals"]["storyboard"] = version(s["board"])
                s["phase"] = "ready"
            board = s["board"]
            view = "## 分镜\n\n" + board.get("visual_direction", "") + "\n"
            bv = version(board)
            for scene in board["scenes"]:
                sid = scene["id"]
                view += (f"\n### {sid} · {scene['caption']}\n\n"
                         f"![{sid}分镜]({public_url()}/assets/{cid}/boards/{bv}/{sid}.png)\n\n"
                         f"讲稿：{scene['narration']}\n\n画面变化：{scene['animation']}\n")
            view += "\n修改画面文字时，每段一行，保留段号，如「s02：新标题」。"
            fields = {"screen_text": "\n".join(x["id"]+"："+x["caption"] for x in board["scenes"])}
        else:
            raise ValueError("阶段不正确")
        if s.get("notice"):
            view = "**" + s.pop("notice") + "**\n\n" + view
        s["display_stage"] = stage
        s["display_version"] = version({"stage": stage, "view": view, "fields": fields})
        s["display_fields"] = copy.deepcopy(fields)
        store(cid, s)
        done = bool(s["approvals"].get(stage))
        return response(cid, view, fields, done=done)


def apply(cid, stage, payload):
    with lock(cid):
        s = state(cid)
        if s.get("display_stage") != stage or payload.get("version") != s.get("display_version"):
            raise ValueError("内容已更新，请刷新后确认")
        action = payload.get("action")
        if action not in ("approve", "revise"):
            raise ValueError("操作无效")
        if stage == "requirements":
            fields = {name: str(payload.get(name, "")).strip() for name in
                      ("topic","audience","duration_minutes","objectives","prerequisites","style",
                       "voice_instruction","production_mode")}
            # 旧执行图只有style字段，按旧契约保存；新图显式保存选择的分支。
            if "style_preset" in payload:
                fields.update(styles.resolve(payload["style_preset"], fields["style"],
                    s.get("display_fields", {}).get("style_preset", "")))
            if s.get('materials'):
                fields['knowledge_ids'] = materials.selected_ids(payload.get('knowledge_selection', ''), s['materials'])
                fields['knowledge_points'] = [p['title'] for p in s['materials']['knowledge_points']
                                             if p['id'] in fields['knowledge_ids']]
            elif 'knowledge_selection' in payload:
                fields['knowledge_focus'] = str(payload['knowledge_selection']).strip()
            fields["voice_instruction"] = fields["voice_instruction"] or DEFAULT_VOICE_INSTRUCTION
            voice_units = sum(2 if "\u3400" <= ch <= "\u9fff" else 1
                              for ch in fields["voice_instruction"])
            if voice_units > 100:
                raise ValueError("语速和语气的说明请控制在约50个汉字以内")
            try:
                minutes = float(fields["duration_minutes"])
            except ValueError:
                minutes = 0
            if not fields["topic"] or not fields["audience"] or not math.isfinite(minutes) or minutes <= 0:
                raise ValueError("请填写主题、授课对象和视频时长")
            if fields["production_mode"] not in ("先看分镜", "直接制作"):
                raise ValueError("请选择先看分镜或直接制作")
            if fields != s.get("requirements"):
                s["approvals"] = {}
                s.pop("draft", None); s.pop("board", None)
                s.pop("script_job", None); s.pop("script_feedback", None)
            s["requirements"] = fields
            s["approvals"]["requirements"] = version(fields)
            s["phase"] = "script"
            archive(cid, "requirements", fields)
            done = True
        elif stage == "script":
            text = str(payload.get("approved_script", "")).strip()
            if not text:
                raise ValueError("讲稿不能为空")
            original = s["draft"]["script"]
            s["draft"]["script"] = text
            s["approvals"].pop("script", None); s["approvals"].pop("storyboard", None)
            if action == "revise":
                feedback = str(payload.get("feedback", "")).strip()
                if feedback:
                    s["script_feedback"] = feedback
                done = False
            else:
                # 对修改后的超时量先重新展示，不能把旧稿的时长确认套在新稿上。
                seconds = estimate_seconds(text)
                if text != original and seconds > max(float(s["requirements"]["duration_minutes"])*60,
                                                       s.get("draft_estimate", 0)) + 1:
                    s["draft"]["teacher_message"] = "修改后的讲稿更长了，请重新确认预计时长。"
                    done = False
                else:
                    s["approved_script"] = text
                    s["approvals"]["script"] = version(text)
                    s["requirements"]["duration_minutes"] = str(max(
                        float(s["requirements"]["duration_minutes"]), seconds/60))
                    s.pop("board", None)
                    s["phase"] = "storyboard"
                    done = True
            archive(cid, "script", s["draft"])
        elif stage == "storyboard":
            lines = str(payload.get("screen_text", "")).splitlines()
            captions = {}
            for line in lines:
                if not line.strip():
                    continue
                match = re.match(r"^(s\d+)\s*[:：]\s*(.+)$", line.strip())
                if not match or match.group(1) in captions:
                    raise ValueError("每行画面文字需保留唯一段号，例如s01：标题")
                captions[match.group(1)] = match.group(2)
            if set(captions) != {x["id"] for x in s["board"]["scenes"]}:
                raise ValueError("画面文字中的段号与当前分镜不一致")
            changed = any(x["caption"] != captions[x["id"]] for x in s["board"]["scenes"])
            for scene in s["board"]["scenes"]:
                scene["caption"] = captions[scene["id"]]
            feedback = str(payload.get("feedback", "")).strip()
            if action == "revise" and feedback:
                s["board_feedback"] = feedback
            if changed:
                s["captions_changed"] = True
            done = action == "approve" and not changed
            if done:
                s["approvals"]["storyboard"] = version(s["board"])
                s["phase"] = "ready"
            else:
                s["approvals"].pop("storyboard", None)
            archive(cid, "storyboard", s["board"])
        else:
            raise ValueError("阶段不正确")
        store(cid, s)
        return response(cid, "已保存。", done=done)


def validate_board(board, script):
    scenes = board.get("scenes", [])
    if not scenes:
        raise ValueError("分镜数量无效")
    ids = [x.get("id", "") for x in scenes]
    if len(set(ids)) != len(ids) or any(not re.fullmatch(r"s\d{2,}", x) for x in ids):
        raise ValueError("分镜段号不正确")
    if normalize("".join(x.get("narration", "") for x in scenes)) != normalize(script):
        raise ValueError("分镜中的讲稿与已确认版本不一致，制作已暂停")
    for scene in scenes:
        if not all(isinstance(scene.get(k), str) and scene[k].strip()
                   for k in ("narration","caption","animation","html")):
            raise ValueError("分镜缺少口述、画面文字、动画说明或场景源码")
        if "frame" not in scene["html"] or "SCENE" not in scene["html"]:
            raise ValueError("场景缺少时间函数或可编辑文字接口")


def render(cid, scene, html, output, **extra):
    task = {"root": str(course_dir(cid)), "runtime": str(RENDER_RUNTIME),
            "html": str(html), "scene": scene, "output": str(output), **extra}
    path = output.with_suffix(".render.json")
    save(path, task)
    process = subprocess.run(
        [NODE,
         str(TOOL / "teacher_flow/render.mjs"), str(path)],
        capture_output=True, timeout=3600 if extra.get("mode")=="video" else 60,
    )
    if process.returncode:
        # 生成的页面可能输出任意文字，仅保留隔离渲染器错误在本课目录供核查。
        output.with_suffix(".error.txt").write_bytes(process.stderr[-8000:])
        raise RuntimeError("画面未能生成，制作已暂停")
    if not output.exists() or output.stat().st_size < 100:
        raise RuntimeError("未取得有效渲染文件")


def save_board(cid, board):
    folder = course_dir(cid) / "boards" / version(board)
    folder.mkdir(parents=True, exist_ok=True)
    for scene in board["scenes"]:
        html = folder / (scene["id"] + ".html")
        if not html.exists():
            html.write_text(scene["html"])
        preview = folder / (scene["id"] + ".png")
        if not preview.exists():
            duration = max(4, estimate_seconds(scene["narration"]))
            render(cid, {**scene, "duration_seconds": duration}, html, preview, mode="preview",
                   time=duration * min(0.9, max(0.1, float(scene.get("preview_fraction", .5)))))
    save(folder / "storyboard.json", board)
