"""路径、持久化和输入版本；本模块不调用模型。"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import shutil
from pathlib import Path
import re
import tempfile
import threading
import time

TOOL = Path(__file__).resolve().parents[1]
try:
    from dotenv import load_dotenv
    load_dotenv(TOOL / '.env', override=False)
except ImportError:
    pass
RUNTIME = Path(os.environ.get("TEACHER_FLOW_RUNTIME", str(TOOL / '.runtime/teacher-flow'))).expanduser().resolve()
COURSES = RUNTIME / "courses"
PYTHON = Path(sys.executable)
PRODUCTION_SKILL = TOOL / 'skills/explainer-video-production'
DESLOP = TOOL / 'skills/deslop-zh/SKILL.md'
RENDER_RUNTIME = Path(os.environ.get('TEACHER_RENDER_RUNTIME', str(RUNTIME.parent / 'renderer'))).expanduser().resolve()
NODE = os.environ.get('TEACHER_NODE_BIN') or shutil.which('node') or 'node'
DEFAULT_VOICE_INSTRUCTION = "普通话自然讲解，清晰从容，语速适中，重点略作强调，句间自然停顿。"
LOCKS: dict[str, threading.RLock] = {}
_LOCK = threading.Lock()


def digest(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(value).hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".save-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def load(path):
    return json.loads(Path(path).read_text())


def course_dir(course_id):
    if not re.fullmatch(r"[a-f0-9]{24}", str(course_id)):
        raise ValueError("课程编号不正确")
    return COURSES / course_id


def state(course_id):
    return load(course_dir(course_id) / "state.json")


def store(course_id, value):
    value["updated_at"] = time.time()
    save(course_dir(course_id) / "state.json", value)


def lock(course_id):
    with _LOCK:
        return LOCKS.setdefault(course_id, threading.RLock())


def estimate_seconds(text):
    chinese = len(re.findall(r"[\u3400-\u9fff]", text))
    english = len(re.findall(r"[A-Za-z]+", text))
    return round(chinese / 240 * 60 + english / 145 * 60 + text.count("。") * 0.35, 1)


def version(value):
    return digest(value)[:20]


def archive(course_id, kind, value):
    path = course_dir(course_id) / "versions" / kind / (version(value) + ".json")
    if not path.exists():
        save(path, value)
    return path


def bridge_config():
    return load(RUNTIME / "bridge.json")


def public_url():
    return bridge_config()["public_url"]
