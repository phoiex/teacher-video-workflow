"""将长分镜任务保存为本地作业；Dify 每次只等一个短轮询。"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import time

from .common import (PRODUCTION_SKILL, TOOL, course_dir, digest, load, save, state, version)
from . import styles
from .codex_runtime import SDK_PYTHON, SessionPaused, continuation_label
from .common import RUNTIME


class Paused(Exception):
    pass


def enabled():
    return True


def update_job(folder, **fields):
    with (folder / 'state.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        data = load(folder / 'job.json')
        data.update(fields, updated_at=time.time())
        save(folder / 'job.json', data)
        return data


def inputs_for(s):
    branch = styles.branch(s['requirements'].get('style', ''), s['requirements'].get('style_preset', ''))
    resources = PRODUCTION_SKILL.joinpath('SKILL.md').read_text()
    if branch:
        resources += '\n\n' + PRODUCTION_SKILL.joinpath('branches', branch).read_text()
    resources += ('\n\n本课程使用固定讲稿和既有课程工具。已完成讲稿确认；本阶段只制作分镜。'
                  '不增加样片或配音，不询问模型分工。完成后交回工作流，由老师按既定模式确认。')
    inputs = {'requirements': s['requirements'], 'script': s['approved_script'],
            'previous_storyboard': s.get('board'), 'feedback': s.get('board_feedback', ''),
            'style_instructions': resources}
    if s.get('model_roles'):
        inputs['producer_profile'] = s['model_roles']['producer']
    if s.get('style_preview_version'):
        inputs['style_reference_images'] = styles.preview_images(s['requirements'].get('style_preset', ''))
    return inputs


def job_dir(cid, key):
    if len(key) != 20 or any(c not in '0123456789abcdef' for c in key):
        raise ValueError('制作任务编号不正确')
    return course_dir(cid) / 'harness/jobs' / key


def _pause_requested(folder):
    path = folder / 'control.json'
    return path.exists() and load(path).get('pause') is True


def _worker_alive(pid):
    if not pid: return False
    try: os.kill(pid, 0)
    except ProcessLookupError: return False
    result = subprocess.run(['ps', '-p', str(pid), '-o', 'stat='], capture_output=True, text=True)
    return bool(result.stdout.strip()) and not result.stdout.strip().startswith('Z')


def _finish_pause(folder):
    with (folder / 'launch.lock').open('a') as launch_guard:
        fcntl.flock(launch_guard, fcntl.LOCK_EX)
        data = load(folder / 'job.json')
        if not _pause_requested(folder) or data['status'] in ('complete', 'paused'):
            return data
        if _worker_alive(data.get('pid')):
            return data
        with (folder / 'worker.lock').open('a') as worker_guard:
            try: fcntl.flock(worker_guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: return data
            if (folder / 'result.json').exists():
                return update_job(folder, status='complete', message='分镜已保存，可以查看。')
            return update_job(folder, status='paused', message='已暂停，制作进度已保存。', error_type=None)


def _signal_legacy_worker(pid, cid, key):
    if not _worker_alive(pid): return
    command = subprocess.check_output(['ps', '-p', str(pid), '-o', 'command='], text=True)
    expected = f'-m teacher_flow.codex_jobs {cid} {key}'
    if expected not in command or os.getpgid(pid) != pid:
        raise ValueError('未找到对应的制作进程，请刷新进度。')
    os.kill(pid, signal.SIGINT)


def _prepare_continuation(cid, key, data, action):
    folder = job_dir(cid, key)
    session = course_dir(cid) / 'harness/sessions' / data['script_version']
    plan = folder / 'work/plan.json'
    labels = ([key + '-' + scene['id'] for scene in load(plan)['scenes']]
              if plan.exists() else [key + '-plan'])
    for original in labels:
        effective = continuation_label(session, original)
        path = session / 'turns' / (effective + '.json')
        if not path.exists(): break
        record = load(path)
        artifact = plan if original.endswith('-plan') else folder / 'work' / (original.removeprefix(key + '-') + '.html')
        if record.get('status') == 'completed' and artifact.exists(): continue
        pointer = session / 'continuations' / (original + '.json')
        label = original + '-' + action + '-' + secrets.token_hex(6)
        recovery = {'authorized_by': 'user', 'original_label': original,
                    'continuation_label': label, 'previous_label': effective,
                    'previous_status': record.get('status'), 'at': time.time(),
                    'previous_continuation': load(pointer) if pointer.exists() else None}
        save(session / 'retries' / (label + '.json'), recovery)
        save(pointer, recovery)
        break


def status(cid):
    pointer = course_dir(cid) / 'harness/current.json'
    if not pointer.exists(): return {'status': 'idle', 'message': '等待分镜制作。'}
    key = load(pointer)['key']
    folder = job_dir(cid, key)
    data = load(folder / 'job.json')
    if _pause_requested(folder):
        data = _finish_pause(folder)
    if data['status'] in ('queued', 'running') and data.get('pid'):
        try: os.kill(data['pid'], 0)
        except ProcessLookupError:
            # 重启时只核查已保存成果，不重发任何模型请求。
            if (folder / 'result.json').exists():
                data.update(status='complete', message='分镜已保存，可以查看。')
            else:
                data.update(status='unknown', message='制作进程已退出，记录已保存，需要先核查上次请求。')
            save(folder / 'job.json', data)
    return {**data, 'course_id': cid, 'key': key}


def touch(cid):
    save(course_dir(cid) / 'harness/presence.json', {'at': time.time()})


def saved_artifacts(folder):
    work = folder / 'work'
    plan = work / 'plan.json'
    saved, previewed = [], []
    if not plan.exists():
        return saved, previewed
    for scene in load(plan).get('scenes', []):
        sid = scene.get('id', '')
        if not re.fullmatch(r's\d{2,}', sid):
            continue
        source = work / (sid + '.html')
        if not source.is_file() or not source.stat().st_size:
            continue
        saved.append(sid)
        rendered = work / (sid + '.rendered.json')
        if rendered.exists():
            record = load(rendered)
            if (record.get('source_hash') == digest(source.read_bytes()) and record.get('paths')
                    and all(Path(p).is_file() for p in record['paths'])):
                previewed.append(sid)
    return saved, previewed


def public_status(cid):
    data = status(cid)
    public = {k: data.get(k) for k in ('status', 'message', 'completed', 'total', 'scene_id', 'key', 'updated_at')}
    public['retry_generation'] = data.get('retry_generation', 0)
    saved, previewed = saved_artifacts(job_dir(cid, data['key'])) if data.get('key') else ([], [])
    public.update(saved_scenes=saved, previewed_scenes=previewed)
    if data.get('key') and data['status'] not in ('paused', 'complete') and _pause_requested(job_dir(cid, data['key'])):
        public.update(status='pausing', message='正在暂停，保留当前制作进度。')
    elif data['status'] == 'running' and data.get('active_label'):
        from .codex_activity import current_activity
        session = course_dir(cid) / 'harness/sessions' / data['script_version']
        path = session / 'turns' / (data['active_label'] + '.json')
        if path.exists():
            receipt = load(path)
            if receipt.get('status') in ('running', 'submitting'):
                waiting, last_event = current_activity(session, receipt)
                public['updated_at'] = max(public.get('updated_at') or 0, last_event)
                if waiting:
                    public.update(status='network_wait', message='等待网络恢复，正在重连。')
    elif data['status'] == 'failed':
        reason = '本轮未完成，已有进度已保留。'
        label = data.get('active_label')
        if label:
            receipt = course_dir(cid) / 'harness/sessions' / data['script_version'] / 'turns' / (label + '.json')
            if receipt.exists():
                turn = load(receipt)
                error = (turn.get('terminal') or {}).get('error') or {}
                detail = error.get('codexErrorInfo') or {}
                code = (detail.get('responseTooManyFailedAttempts') or {}).get('httpStatusCode') if isinstance(detail, dict) else None
                message = (turn.get('response_failure') or {}).get('message') or '\n'.join(
                    str(error.get(k) or '') for k in ('message', 'additionalDetails'))
                if '模型响应已结束，但没有返回正文或工具调用' in message or 'empty_model_output' in message:
                    reason = '模型结束了响应，但没有返回制作内容。可以从当前课程重试。'
                elif '服务商结束了本次输出' in message or 'provider_output_limit' in message:
                    reason = '服务商结束了本次输出，制作尚未完成。可以从断点重试。'
                elif turn.get('status') == 'completed':
                    if not (job_dir(cid, data['key']) / 'work/plan.json').exists():
                        reason = '模型结束了响应，但没有保存分镜计划。可以从当前课程重试。'
                    else:
                        reason = '模型结束了响应，但当前片段尚未保存。可以从断点重试。'
                elif code == 429 or '429 Too Many Requests' in message:
                    reason = '制作服务暂时无法接受请求（429），请稍后再试。'
                elif '408' in message or 'request body receive timeout' in message.lower():
                    reason = '模型请求超时（408），制作已停止。'
                elif 'timeout' in message.lower() or 'timed out' in message.lower():
                    reason = '模型请求超时，制作已停止。'
                elif 'cannot connect to host' in message.lower():
                    reason = '暂时无法连接模型服务，制作已停止。'
                elif 'stream disconnected' in message or 'error sending request' in message:
                    reason = '模型连接中断，制作已停止。'
        sid = data.get('scene_id')
        if sid in saved:
            which = f'第{int(sid[1:])}段'
            reason += which + ('草稿和预览已保存。' if sid in previewed else '草稿已保存。')
        prefix = '本次重试未成功：' if public['retry_generation'] else '制作中断：'
        public['message'] = prefix + reason
    elif data['status'] == 'unknown':
        public['message'] = '暂时无法确认制作结果，已保存的片段会保留。'
    return public


def _launch(cid, key):
    folder = job_dir(cid, key)
    if not SDK_PYTHON.exists(): raise RuntimeError('课程制作运行时尚未安装')
    with (folder / 'worker.log').open('ab') as log:
        process = subprocess.Popen([str(SDK_PYTHON), '-m', 'teacher_flow.codex_jobs', cid, key],
            cwd=TOOL, env={**os.environ, 'PYTHONPATH': str(TOOL)},
            stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    update_job(folder, pid=process.pid)


def ensure(cid, s):
    if s.get('approvals', {}).get('script') != version(s.get('approved_script', '')):
        raise ValueError('请先确认当前讲稿')
    inputs = inputs_for(s)
    key = version(inputs)
    folder = job_dir(cid, key)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    # 多个Dify轮询或浏览器不能启动同一制作任务两次。
    with (folder / 'launch.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        if not (folder / 'job.json').exists():
            save(folder / 'input.json', inputs)
            save(folder / 'job.json', {'status': 'queued', 'message': '正在安排分镜。',
                'script_version': s['approvals']['script'], 'created_at': time.time(),
                'completed': 0, 'total': 0, 'control_token': secrets.token_urlsafe(24)})
            touch(cid)
            _launch(cid, key)
        save(course_dir(cid) / 'harness/current.json', {'key': key})
    return status(cid)


def poll(cid, s, seconds=20):
    data = ensure(cid, s)
    until = time.monotonic() + seconds
    while data['status'] in ('queued', 'running') and time.monotonic() < until:
        time.sleep(.4)
        data = status(cid)
    if data['status'] == 'complete':
        result = load(job_dir(cid, data['key']) / 'result.json')
        if state(cid)['approvals'].get('script') != data['script_version']:
            raise ValueError('讲稿已变更，请重新确认后制作')
        return data, result
    return data, None


def retry_job(cid, key, retry_generation=None):
    folder = job_dir(cid, key)
    with (folder / 'launch.lock').open('a') as launch_guard:
        fcntl.flock(launch_guard, fcntl.LOCK_EX)
        data = load(folder / 'job.json')
        if (data['status'] not in ('failed', 'unknown') or
                retry_generation is not None and retry_generation != data.get('retry_generation', 0)):
            return
        with (folder / 'worker.lock').open('a') as worker_guard:
            try:
                fcntl.flock(worker_guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError('制作仍在运行，请稍后查看进度。') from exc
            saved = state(cid)
            if (saved.get('approvals', {}).get('script') != data['script_version'] or
                    version(saved.get('approved_script', '')) != data['script_version']):
                raise ValueError('讲稿已变化，请确认当前讲稿后继续。')
            if (folder / 'result.json').exists():
                update_job(folder, status='complete', message='分镜已保存，可以查看。')
                return
            _prepare_continuation(cid, key, data, 'retry')
            touch(cid)
            save(folder / 'control.json', {'pause': False})
            update_job(folder, status='queued', pid=None, error_type=None,
                       retry_generation=data.get('retry_generation', 0) + 1,
                       message='正在从已保存的进度继续制作。')
            try:
                _launch(cid, key)
            except Exception:
                update_job(folder, status='failed', message='制作服务暂时无法启动，请稍后重试。')
                raise


def control(cid, key, action, retry_generation=None):
    data = status(cid)
    if data.get('key') != key: raise ValueError('制作任务已更新')
    folder = job_dir(cid, key)
    if action == 'retry':
        retry_job(cid, key, retry_generation)
    elif action == 'pause' and data['status'] in ('queued', 'running'):
        with (folder / 'launch.lock').open('a') as guard:
            fcntl.flock(guard, fcntl.LOCK_EX)
            latest = load(folder / 'job.json')
            if latest['status'] in ('queued', 'running'):
                ctl = load(folder / 'control.json') if (folder / 'control.json').exists() else {}
                ctl.update(pause=True, requested_at=ctl.get('requested_at') or time.time())
                save(folder / 'control.json', ctl)
                update_job(folder, message='正在暂停，保留当前制作进度。')
                if latest.get('pause_protocol') != 'native-turn-v1' and not ctl.get('signal_sent_at'):
                    _signal_legacy_worker(latest.get('pid'), cid, key)
                    save(folder / 'control.json', {**ctl, 'signal_sent_at': time.time()})
    elif action == 'continue' and data['status'] == 'paused':
        with (folder / 'launch.lock').open('a') as guard:
            fcntl.flock(guard, fcntl.LOCK_EX)
            latest = load(folder / 'job.json')
            if latest['status'] == 'paused':
                saved = state(cid)
                if (saved.get('approvals', {}).get('script') != latest['script_version'] or
                        version(saved.get('approved_script', '')) != latest['script_version']):
                    raise ValueError('讲稿已变化，请确认当前讲稿后继续。')
                with (folder / 'worker.lock').open('a') as worker_guard:
                    try: fcntl.flock(worker_guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError as exc: raise ValueError('正在保存暂停进度，请稍后继续。') from exc
                    _prepare_continuation(cid, key, latest, 'continue')
                    touch(cid)
                    save(folder / 'control.json', {'pause': False})
                    update_job(folder, status='queued', pid=None, error_type=None,
                               retry_generation=latest.get('retry_generation', 0)+1,
                               message='正在继续分镜制作。')
                    try:
                        _launch(cid, key)
                    except Exception:
                        update_job(folder, status='failed', message='制作服务暂时无法启动，请稍后重试。')
                        raise
    return status(cid)


def worker(cid, key):
    from .codex_storyboard import produce
    folder = job_dir(cid, key)
    with (folder / 'worker.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        def update(**fields):
            update_job(folder, **fields, pid=os.getpid())
        def checkpoint():
            ctl = folder / 'control.json'
            presence = course_dir(cid) / 'harness/presence.json'
            if ((ctl.exists() and load(ctl).get('pause')) or
                not presence.exists() or time.time() - load(presence)['at'] > 12):
                raise Paused()
            approved = state(cid).get('approvals', {}).get('script')
            if approved != load(folder / 'job.json')['script_version']:
                raise ValueError('当前讲稿版本已变化')
        try:
            update(status='running', message='正在安排分镜。', pause_protocol='native-turn-v1')
            inputs = load(folder / 'input.json')
            session_folder = course_dir(cid) / 'harness/sessions' / version(inputs['script'])
            result = produce(folder / 'work', session_folder, inputs,
                             on_progress=update, checkpoint=checkpoint,
                             pause_requested=lambda: _pause_requested(folder))
            # 最后一段完成后也核对讲稿；不因离开页面丢弃已完成成果。
            if state(cid)['approvals'].get('script') != load(folder / 'job.json')['script_version']:
                raise ValueError('当前讲稿版本已变化')
            save(folder / 'result.json', result)
            update(status='complete', completed=len(result['scenes']), total=len(result['scenes']),
                   message='分镜已保存，可以查看。')
        except (Paused, SessionPaused):
            update(status='paused', message='已保存完成的片段。点击继续后接着制作。')
        except BaseException as exc:
            data = load(folder / 'job.json')
            active = data.get('active_label')
            receipt = session_folder / 'turns' / (active + '.json') if active and 'session_folder' in locals() else None
            uncertain = bool(receipt and receipt.exists() and
                             load(receipt).get('status') in ('unknown', 'submitting', 'running'))
            update(status='unknown' if uncertain else 'failed',
                   message='制作中断，已保存完成的片段。可以从断点重试。',
                   error_type=type(exc).__name__)
            raise


if __name__ == '__main__':
    worker(sys.argv[1], sys.argv[2])
