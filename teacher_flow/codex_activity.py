"""从当前会话的事件尾部读取连接状态；不改变制作任务。"""
from functools import lru_cache
import json
from pathlib import Path

TAIL_BYTES = 512 * 1024


@lru_cache(maxsize=64)
def _scan(path, turn_id, started_at, size, modified_ns, inode):
    waiting = False
    latest = started_at
    with Path(path).open('rb') as stream:
        offset = max(0, size - TAIL_BYTES)
        stream.seek(offset)
        lines = stream.read(size - offset).splitlines()
    if offset:
        lines = lines[1:]
    for raw in lines:
        try:
            event = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            continue
        at = event.get('time', 0)
        params = event.get('params') or {}
        if at < started_at or params.get('turnId', turn_id) != turn_id:
            continue
        latest = max(latest, at)
        method = event.get('method', '')
        if method == 'error':
            error = params.get('error') or {}
            info = error.get('codexErrorInfo') or {}
            message = error.get('message', '').lower()
            if params.get('willRetry') and (
                    'waiting for network' in message or 'reconnecting' in message or
                    isinstance(info, dict) and 'responseStreamDisconnected' in info):
                waiting = True
        elif (method.startswith('producer/tool_') or
              method.startswith('item/') and 'delta' in method.lower() or
              method in ('item/started', 'item/completed') and
              (params.get('item') or {}).get('type') not in (None, 'userMessage') or
              method in ('thread/tokenUsage/updated', 'turn/completed')):
            waiting = False
    return waiting, latest


def current_activity(session_folder, receipt):
    path = Path(session_folder) / 'events.jsonl'
    if not path.exists() or not receipt.get('turn_id'):
        return False, receipt.get('started_at', 0)
    stat = path.stat()
    return _scan(str(path), receipt['turn_id'], receipt.get('started_at', 0),
                 stat.st_size, stat.st_mtime_ns, stat.st_ino)
