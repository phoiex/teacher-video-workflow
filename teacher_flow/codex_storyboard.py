"""课程分镜的受控制作工具；Codex 自己驱动写代码、渲染和看图循环。"""
from __future__ import annotations

import json
import base64
from pathlib import Path
import re
import subprocess
import time

from .common import RENDER_RUNTIME, NODE, TOOL, digest, estimate_seconds, load, save
from .codex_runtime import Session, text_result, tool


INSTRUCTION_DIR = Path(__file__).with_name('instructions')


def instruction(name, **values):
    text = (INSTRUCTION_DIR / (name + '.md')).read_text()
    for key, value in values.items():
        text = text.replace('{' + key + '}', str(value))
    return text.strip()


TOOLS = [
    tool("course_read", "读取固定讲稿、课程要求、风格和当前进度。", {}),
    tool("course_plan", "保存整课分镜计划。按顺序拼接口述必须与固定稿完全一致。",
         {"visual_direction": {"type": "string"}, "scenes": {"type": "array", "items": {
             "type": "object", "properties": {k: {"type": "string"} for k in
                 ("id", "narration", "caption", "animation")},
             "required": ["id", "narration", "caption", "animation"], "additionalProperties": False}}}),
    tool("course_scene", "读取指定分镜和现有HTML源码。", {"scene_id": {"type": "string"}}),
    tool("course_write", "保存指定分镜的完整自包含HTML；不能改变讲稿或分镜内容。",
         {"scene_id": {"type": "string"}, "html": {"type": "string"}}),
    tool("course_render", "按需预览画面，返回图片路径；可选择查看时刻。",
         {"scene_id": {"type": "string"}, "time_fractions": {"type": "array", "items": {"type": "number"}}},
         required=["scene_id"]),
    tool("course_review", "保存当前段的制作备注，按需使用。",
         {"scene_id": {"type": "string"}, "observations": {"type": "string"},
          "approved": {"type": "boolean"}}),
]


def normalized(text):
    return re.sub(r"\s+", "", text)


class BoardTools:
    def __init__(self, folder, inputs, on_progress=None):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.inputs = inputs
        self.on_progress = on_progress or (lambda **fields: None)
        self.allowed_scene = None
        self.allow_plan = False
        self.input_hash = digest(inputs)
        self.viewed_paths = set()
        source = self.folder / "input.json"
        if source.exists() and digest(load(source)) != self.input_hash:
            raise ValueError("制作输入版本不一致")
        save(source, inputs)
        self.plan_path = self.folder / "plan.json"
        if not self.plan_path.exists() and inputs.get("previous_storyboard"):
            board = inputs["previous_storyboard"]
            self._validate_plan(board)
            save(self.plan_path, {"visual_direction": board.get("visual_direction", ""),
                "scenes": [{k: v for k, v in scene.items() if k != "html"} for scene in board["scenes"]]})
            for scene in board["scenes"]:
                if scene.get("html"):
                    (self.folder / (scene["id"] + ".html")).write_text(scene["html"])

    def _validate_plan(self, board):
        scenes = board.get("scenes", [])
        if not scenes: raise ValueError("请提供分镜内容")
        ids = [s.get("id", "") for s in scenes]
        if len(set(ids)) != len(ids) or any(not re.fullmatch(r"s\d{2,}", sid) for sid in ids):
            raise ValueError("段号需唯一，使用s01、s02等")
        if normalized("".join(s.get("narration", "") for s in scenes)) != normalized(self.inputs["script"]):
            raise ValueError("分镜口述改变了固定讲稿，请按原文重新拆分")
        for scene in scenes:
            if any(not isinstance(scene.get(k), str) or not scene[k].strip()
                   for k in ("narration", "caption", "animation")):
                raise ValueError("分镜缺少口述、画面文字或动画说明")

    def observe_event(self, event):
        item = event.get('params', {}).get('item', {})
        if event.get('method') == 'item/completed' and item.get('type') == 'imageView':
            self.viewed_paths.add(str(Path(item['path']).resolve()))

    def scene(self, sid):
        if not re.fullmatch(r"s\d{2,}", sid): raise ValueError("段号无效")
        board = load(self.plan_path)
        found = next((x for x in board["scenes"] if x["id"] == sid), None)
        if not found: raise ValueError("未找到分镜")
        return found

    def call(self, name, args):
        if digest(load(self.folder / "input.json")) != self.input_hash:
            raise ValueError("固定输入被改变，制作已停止")
        if name == "course_read":
            result = text_result({k: self.inputs.get(k) for k in ('requirements', 'script', 'feedback')} | {
                "plan": load(self.plan_path) if self.plan_path.exists() else None,
                "current_scene": self.allowed_scene})
            for reference in self.inputs.get('style_reference_images', []):
                image = Path(reference['path']).read_bytes()
                if digest(image) != reference['sha256']:
                    raise ValueError('参考图内容已变化，请重新读取制作材料')
                result['contentItems'].extend([
                    {'type':'inputText', 'text':reference['name']+'的参考画面，仅参考视觉表达。'},
                    {'type':'inputImage', 'imageUrl':'data:image/png;base64,'+base64.b64encode(image).decode()},
                ])
            return result
        if name == "course_plan":
            if not self.allow_plan: raise ValueError("计划已保存，本轮只制作当前分镜")
            self._validate_plan(args)
            save(self.plan_path, args)
            self.on_progress(message="分镜安排已保存。", total=len(args["scenes"]))
            return text_result({"saved": True, "scenes": len(args["scenes"])})
        sid = args.get("scene_id", "")
        scene = self.scene(sid)
        html = self.folder / (sid + ".html")
        if name == "course_scene":
            return text_result({**scene, "html": html.read_text() if html.exists() else ""})
        if name == "course_write":
            source = args.get("html", "")
            if not isinstance(source, str) or "SCENE" not in source or "frame" not in source:
                raise ValueError("场景需包含SCENE和时间函数")
            html.write_text(source)
            self.on_progress(message=f"正在制作画面：{sid}。", scene_id=sid)
            return text_result({"saved": True, "source_hash": digest(source)})
        if name == "course_render":
            if not html.exists(): raise ValueError("请先保存场景HTML")
            self.on_progress(message=f"正在检查画面：{sid}。", scene_id=sid)
            source_hash = digest(html.read_bytes())
            duration = max(4, estimate_seconds(scene["narration"]))
            directory = self.folder / "frames" / sid / source_hash[:20]
            directory.mkdir(parents=True, exist_ok=True)
            fractions = args.get('time_fractions', [.5])
            if not isinstance(fractions, list) or not fractions or any(
                not isinstance(f, (int, float)) or isinstance(f, bool) or not 0 <= f <= 1
                for f in fractions
            ):
                raise ValueError('time_fractions需为0到1之间的时刻比例')
            images = []
            for fraction in fractions:
                output = directory / f"at-{float(fraction):.8f}.png"
                if not output.exists():
                    task = {"root": str(self.folder.resolve()), "runtime": str(RENDER_RUNTIME),
                        "html": str(html.resolve()), "scene": {**scene, "duration_seconds": duration},
                        "output": str(output.resolve()), "mode": "preview", "time": duration * fraction}
                    spec = output.with_suffix(".render.json")
                    save(spec, task)
                    process = subprocess.run([
                        NODE,
                        str(TOOL / "teacher_flow/render.mjs"), str(spec)],
                        capture_output=True, timeout=75)
                    if process.returncode or not output.exists():
                        output.with_suffix(".error.txt").write_bytes(process.stderr[-8000:])
                        raise ValueError("画面渲染失败：" + process.stderr.decode(errors="replace")[-1600:])
                images.append(output)
            save(self.folder / (sid + ".rendered.json"), {"source_hash": source_hash,
                "paths": [str(x) for x in images], "time_fractions": fractions, "at": time.time()})
            return text_result({"scene_id": sid, "source_hash": source_hash,
                "frames": fractions, "images": [str(p.resolve()) for p in images]})
        if name == "course_review":
            save(self.folder / (sid + ".review.json"), {**args,
                "source_hash": digest(html.read_bytes()) if html.exists() else None,
                "viewed_paths": sorted(self.viewed_paths), "at": time.time()})
            return text_result({"saved": True, "approved": args["approved"]})
        raise ValueError("未提供该课程工具")

    def result(self):
        board = load(self.plan_path)
        self._validate_plan(board)
        for scene in board["scenes"]:
            sid = scene["id"]
            html = self.folder / (sid + ".html")
            if not html.is_file():
                raise ValueError(sid + "尚未保存画面文件")
            scene["html"] = html.read_text()
            scene.setdefault("preview_fraction", .6)
        return board


def produce(folder, session_folder, inputs, on_progress=None, checkpoint=None, pause_requested=None):
    from .codex_runtime import continuation_label
    tools = BoardTools(folder, inputs, on_progress)
    instructions = inputs.get("style_instructions", "") + "\n\n" + instruction('producer')
    job = tools.input_hash[:20]
    def run_part(session, original, prompt):
        label = continuation_label(session_folder, original)
        if label != original:
            prompt = instruction('resume') + '\n\n' + prompt
        if on_progress:
            on_progress(active_label=label, original_label=original)
        return session.run(label, prompt)
    if checkpoint: checkpoint()
    with Session(session_folder, instructions, TOOLS, tools.call, on_event=tools.observe_event,
                 pause_requested=pause_requested, profile=inputs.get('producer_profile')) as session:
        if not tools.plan_path.exists():
            tools.allow_plan = True
            run_part(session, job + "-plan", instruction('plan'))
            tools.allow_plan = False
        plan = load(tools.plan_path)
        total = len(plan["scenes"])
        for i, scene in enumerate(plan["scenes"]):
            if checkpoint: checkpoint()
            sid = scene["id"]
            tools.allowed_scene = sid
            if on_progress: on_progress(message=f"制作分镜：第{i+1}/{total}段。", scene_id=sid, total=total, completed=i)
            label = job + '-' + sid
            prompt = instruction('scene', scene_id=sid, scene_number=i+1,
                                 scene_total=total, feedback=inputs.get('feedback') or '按课程要求制作。')
            run_part(session, label, prompt)
            if on_progress: on_progress(message=f"已完成第{i+1}/{total}段分镜。", completed=i+1, total=total)
        board = tools.result()
        save(Path(folder) / "result.json", board)
        return board
