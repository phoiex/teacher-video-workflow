"""固定版本的 Codex SDK 接口；课程状态和工具实现留在制作服务。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
import re
import threading
import time

from .common import RUNTIME, load, save

SDK_VERSION = "0.154.0"
INSTALL = RUNTIME.parent / "codex-harness"
SDK_PYTHON = Path(sys.executable)
BASE_INSTRUCTIONS = Path(__file__).with_name('instructions').joinpath('base.md').read_text().strip()


class SessionPaused(Exception):
    """用户已要求暂停，当前请求已结束。"""


def provider_settings(runtime=None, profile=None):
    from .model_roles import default_roles, validate
    from .model_connections import connection
    roles = default_roles()
    profile = profile or roles['producer']
    validate({**roles, 'producer': profile})
    if profile['protocol'] == 'responses':
        return {**profile, **connection(profile, runtime),
                'provider_id': 'teacher_' + profile['provider'],
                'reasoning_effort': profile.get('reasoning_effort')}
    from .model_adapter_setup import ensure
    bridge = ensure(profile)
    return {**profile, 'provider_id': 'teacher_' + profile['provider'] + '_adapter',
            'api_key': bridge['token'], 'base_url': bridge['base_url'],
            'model_context_window': bridge.get('model_context_window'),
            'reasoning_effort': profile.get('reasoning_effort')}


def continuation_label(folder, label):
    pointer = Path(folder) / 'continuations' / (label + '.json')
    if not pointer.exists():
        return label
    record = load(pointer)
    target = record.get('continuation_label', '')
    if (record.get('authorized_by') != 'user' or record.get('original_label') != label
            or not re.fullmatch(re.escape(label) + r'-[a-zA-Z0-9-]+', target)):
        raise ValueError('续作授权与原任务不一致')
    return target


def text_result(value, success=True):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return {"success": success, "contentItems": [{"type": "inputText", "text": text}]}


def tool(name, description, properties, required=None):
    return {"type": "function", "name": name, "description": description,
            "inputSchema": {"type": "object", "properties": properties,
                            "required": required or list(properties), "additionalProperties": False}}


class Session:
    """独立 home + 同一 thread；不自动重发失败或未知的 turn。"""

    def __init__(self, folder, instructions, tools, handler, on_event=None, pause_requested=None, profile=None):
        from openai_codex.client import CodexClient, CodexConfig
        from openai_codex import __version__
        if __version__ != SDK_VERSION:
            raise RuntimeError("制作运行时版本不符")
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.on_event = on_event or (lambda event: None)
        self.pause_requested = pause_requested or (lambda: False)
        self.handler = handler
        self.events = self.folder / "events.jsonl"
        self.guard = threading.Lock()
        self.active_turn = None
        self.timed_out = False
        credential = provider_settings(profile=profile)
        self.model = credential['model']
        self.provider_id = credential['provider_id']
        self.reasoning_effort = credential['reasoning_effort']
        self.secret = credential["api_key"]
        home = self.folder / "home"
        home.mkdir(exist_ok=True, mode=0o700)
        cwd = self.folder / "workspace"
        cwd.mkdir(exist_ok=True)
        config = '\n'.join([
            'model = ' + json.dumps(self.model),
            'model_provider = ' + json.dumps(self.provider_id),
            *(['model_reasoning_effort = ' + json.dumps(self.reasoning_effort)]
              if self.reasoning_effort is not None else []),
            'approval_policy = "never"',
            'sandbox_mode = "read-only"', 'web_search = "disabled"',
            'project_doc_max_bytes = 0',
            *(['model_context_window = ' + str(credential['model_context_window'])]
              if credential.get('model_context_window') else []),
            '[features]', 'shell_tool = false', 'multi_agent = false', 'apps = false',
            'hooks = false', 'goals = false', 'remote_plugin = false',
            '[features.code_mode]', 'enabled = false',
            '[model_providers.' + self.provider_id + ']', 'name = "Course production"',
            'base_url = ' + json.dumps(credential["base_url"]),
            'wire_api = "responses"', 'env_key = "TEACHER_COURSE_API_KEY"',
            'request_max_retries = 0', 'stream_max_retries = 2',
            'stream_idle_timeout_ms = 900000',
        ]) + '\n'
        (home / "config.toml").write_text(config)
        os.chmod(home / "config.toml", 0o600)
        self.client = CodexClient(CodexConfig(cwd=str(cwd),
            env={"CODEX_HOME": str(home), "TEACHER_COURSE_API_KEY": self.secret},
            client_name="teacher_course_producer", client_title="Course producer",
            experimental_api=True), approval_handler=self._request)
        try:
            self.client.start()
            self.client.initialize()
            saved = self.folder / "session.json"
            if saved.exists():
                sid = load(saved)["thread_id"]
                response = self.client.thread_resume(sid, {
                    "model": self.model, "modelProvider": self.provider_id,
                    "approvalPolicy": "never", "sandbox": "read-only",
                    "baseInstructions": BASE_INSTRUCTIONS,
                    "developerInstructions": instructions,
                })
                self.thread_id = response.thread.id
                if self.thread_id != sid:
                    raise RuntimeError("恢复的制作会话不一致")
                self._record({"method": "producer/resumed", "thread_id": sid,
                              "model": self.model, "provider": self.provider_id})
            else:
                response = self.client.thread_start({
                    "model": self.model, "modelProvider": self.provider_id,
                    "approvalPolicy": "never", "sandbox": "read-only",
                    "baseInstructions": BASE_INSTRUCTIONS,
                    "cwd": str(cwd), "developerInstructions": instructions,
                    "dynamicTools": tools,
                })
                self.thread_id = response.thread.id
                save(saved, {"thread_id": self.thread_id, "sdk_version": SDK_VERSION,
                             "created_at": time.time(), "model": self.model,
                             "provider": self.provider_id})
                self._record({"method": "producer/created", "thread_id": self.thread_id,
                              "model": self.model, "provider": self.provider_id})
        except BaseException:
            self.client.close()
            raise

    def _record(self, event):
        # 图像本体已在课程目录；日志只保留哈希/路径及像素输入数量。
        def clean(value):
            if isinstance(value, str):
                if value.startswith("data:image/"):
                    return "[image content stored in course files]"
                return value.replace(self.secret, "[redacted]")
            if isinstance(value, list): return [clean(x) for x in value]
            if isinstance(value, dict): return {k: clean(v) for k, v in value.items()}
            return value
        event = clean(event)
        with self.guard:
            with self.events.open("a") as out:
                out.write(json.dumps({"time": time.time(), **event}, ensure_ascii=False) + "\n")
        self.on_event(event)

    def _request(self, method, params):
        if method != "item/tool/call":
            self._record({"method": "producer/permission_denied", "request": method})
            return {"decision": "decline"}
        try:
            args = params.get("arguments", {})
            if isinstance(args, str): args = json.loads(args)
            self._record({"method": "producer/tool_started", "tool": params.get("tool"),
                          "arguments": args})
            result = self.handler(params["tool"], args)
            self._record({"method": "producer/tool_completed", "tool": params["tool"],
                          "success": result.get("success"),
                          "image_count": sum(x.get("type") == "inputImage"
                                             for x in result.get("contentItems", []))})
            return result
        except Exception as exc:
            message = str(exc).replace(self.secret, "[redacted]")[:1000]
            self._record({"method": "producer/tool_failed", "error": message})
            return text_result({"error": message}, False)

    def run(self, label, prompt, *, seconds=None, token_limit=None):
        from openai_codex.api import Thread
        receipt = self.folder / "turns" / (label + ".json")
        if receipt.exists():
            previous = load(receipt)
            if previous.get("status") == "completed": return previous
            raise RuntimeError("上次制作请求未完成，已保留会话；请先核查，不重复提交")
        if self.pause_requested():
            raise SessionPaused()
        record = {"label": label, "status": "submitting", "thread_id": self.thread_id,
                  "started_at": time.time(), "prompt": prompt,
                  "model": self.model, "provider": self.provider_id}
        save(receipt, record)
        turn = None
        timer = None
        final = ""
        terminal = None
        uncached_and_output = 0
        usage_seen = set()
        watch_done = threading.Event()
        user_paused = threading.Event()
        pause_watch = None
        pause_deadline = None
        response_failure = None
        try:
            thread = Thread(self.client, self.thread_id)
            turn = thread.turn(prompt, **({'effort':self.reasoning_effort} if self.reasoning_effort is not None else {}))
            self.active_turn = turn
            record.update(status="running", turn_id=turn.id)
            save(receipt, record)
            def watch_pause():
                nonlocal pause_deadline
                while not watch_done.wait(.15):
                    if not self.pause_requested():
                        continue
                    user_paused.set()
                    self._record({'method': 'producer/pause_requested', 'turn_id': turn.id})
                    def close_if_waiting():
                        if not watch_done.is_set():
                            self.client.close()
                    pause_deadline = threading.Timer(5, close_if_waiting)
                    pause_deadline.daemon = True
                    pause_deadline.start()
                    try:
                        turn.interrupt()
                    except Exception:
                        close_if_waiting()
                    return
            pause_watch = threading.Thread(target=watch_pause, daemon=True)
            pause_watch.start()
            def stop():
                self.timed_out = True
                try: turn.interrupt()
                except Exception: pass
            if seconds is not None:
                timer = threading.Timer(seconds, stop)
                timer.daemon = True
                timer.start()
            for event in turn.stream():
                payload = event.payload
                data = payload.model_dump(mode="json", by_alias=True) if hasattr(payload, "model_dump") else payload
                self._record({"method": event.method, "params": data})
                if event.method == 'error':
                    error = data.get('error') or {}
                    message = '\n'.join(str(error.get(k) or '') for k in ('message', 'additionalDetails'))
                    match = re.search(r'\[course-model:(empty_model_output|provider_output_limit)\]', message)
                    if match and response_failure is None:
                        response_failure = {'code': match.group(1), 'message': message}
                        # The SDK retries unfamiliar SSE error codes as disconnects.
                        # These two outcomes are already terminal at the provider.
                        # Stop that replay; actual connection failures keep normal retries.
                        if data.get('willRetry'):
                            turn.interrupt()
                if event.method == "item/completed":
                    item = data.get("item", {})
                    if item.get("type") == "agentMessage": final = item.get("text", final)
                if event.method == "turn/completed": terminal = data.get("turn", {})
                if event.method == "thread/tokenUsage/updated":
                    usage = data.get("tokenUsage", {}).get("last", {})
                    record["usage"] = data.get("tokenUsage")
                    signature = json.dumps(data.get("tokenUsage", {}).get("total", {}), sort_keys=True)
                    if signature not in usage_seen:
                        usage_seen.add(signature)
                        uncached_and_output += (max(0, usage.get("inputTokens", 0)
                                                   - usage.get("cachedInputTokens", 0))
                                                + usage.get("outputTokens", 0))
                    record['uncached_input_plus_output'] = uncached_and_output
                    if token_limit is not None and uncached_and_output > token_limit: stop()
            record.update(status=(terminal or {}).get("status", "unknown"),
                          final=final, terminal=terminal, finished_at=time.time(),
                          timed_out=self.timed_out, pause_requested=user_paused.is_set())
            if response_failure:
                record.update(status='failed', response_failure=response_failure,
                              native_status=(terminal or {}).get('status'))
            save(receipt, record)
            if user_paused.is_set() and record['status'] != 'completed':
                raise SessionPaused()
            if record["status"] != "completed":
                raise RuntimeError("制作请求未正常结束，已保存会话和片段")
            return record
        except BaseException as exc:
            if response_failure:
                record.update(status='failed', response_failure=response_failure, finished_at=time.time())
                save(receipt, record)
            if record["status"] not in ("completed", "failed", "interrupted"):
                record.update(status="unknown", error_type=type(exc).__name__, finished_at=time.time())
                save(receipt, record)
            if user_paused.is_set():
                record['pause_requested'] = True
                save(receipt, record)
                raise SessionPaused() from exc
            raise
        finally:
            watch_done.set()
            if pause_deadline: pause_deadline.cancel()
            if pause_watch: pause_watch.join(timeout=.5)
            if timer: timer.cancel()
            self.active_turn = None

    def close(self):
        self.client.close()

    def __enter__(self): return self
    def __exit__(self, *_): self.close()
