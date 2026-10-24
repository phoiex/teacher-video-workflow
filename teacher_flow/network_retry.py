"""网络调用的有限重试、可中断等待与进度通知。"""
from contextvars import ContextVar
import socket
import ssl
import time
import urllib.error

ATTEMPTS = 3
DELAYS = (2, 5)
progress = ContextVar('network_progress', default=None)


class NetworkFailure(RuntimeError):
    def __init__(self, message='网络连接暂时不可用，请从已保存的进度重试。', *, status_code=None, retry_after=None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after
        self.retryable = True


def is_network_error(exc):
    if isinstance(exc, NetworkFailure):
        return True
    status = getattr(exc, 'status_code', None) or getattr(exc, 'code', None)
    if isinstance(status, int):
        if status == 429 and any(word in str(exc).lower() for word in ('insufficient_quota', 'balance', 'quota exhausted')):
            return False
        return status in (408, 425, 429, 500, 502, 503, 504)
    if isinstance(exc, (TimeoutError, ConnectionError, socket.gaierror, ssl.SSLError)):
        return True
    if isinstance(exc, urllib.error.URLError):
        return True
    return type(exc).__name__ in {
        'APIConnectionError', 'APITimeoutError', 'ConnectError', 'ConnectTimeout',
        'ReadTimeout', 'WriteTimeout', 'ReadError', 'WriteError', 'RemoteProtocolError',
        'PoolTimeout', 'ChunkedEncodingError', 'IncompleteRead',
    }


def receipt_retryable(record):
    if 'retryable' in record:
        return record['retryable'] is True
    code = record.get('http_status') or (record.get('provider_error') or {}).get('status')
    if code is not None:
        return int(code) in (408, 425, 429, 500, 502, 503, 504)
    return record.get('error_type') in {
        'URLError', 'TimeoutError', 'TimeoutExpired', 'ConnectionError', 'APIConnectionError',
        'APITimeoutError', 'ConnectError', 'ConnectTimeout', 'ReadTimeout', 'RemoteProtocolError',
    }


def wait(delay, checkpoint=None):
    until = time.monotonic() + delay
    while time.monotonic() < until:
        if checkpoint:
            checkpoint()
        time.sleep(min(.2, max(0, until-time.monotonic())))


def call(fn, *, on_retry=None, checkpoint=None, attempts=ATTEMPTS):
    for attempt in range(1, attempts + 1):
        if checkpoint:
            checkpoint()
        if attempt > 1:
            event={'status':'retrying','attempt':attempt,'max_attempts':attempts,'waiting':False,
                   'message':f'正在重试（第{attempt}/{attempts}次）。'}
            for notify in (progress.get(),on_retry):
                if notify:notify(event)
        try:
            return fn(attempt)
        except Exception as exc:
            if not is_network_error(exc):
                raise
            if attempt == attempts:
                raise NetworkFailure(status_code=getattr(exc, 'status_code', None)) from exc
            retry_after = getattr(exc, 'retry_after', None)
            headers = getattr(getattr(exc, 'response', None), 'headers', None)
            if retry_after is None and headers:
                retry_after = headers.get('retry-after')
            try:
                delay = max(DELAYS[min(attempt-1, len(DELAYS)-1)], min(60, float(retry_after or 0)))
            except (TypeError, ValueError):
                delay = DELAYS[min(attempt-1, len(DELAYS)-1)]
            event = {'status': 'retrying', 'attempt': attempt+1, 'max_attempts': attempts,
                     'waiting': True,
                     'delay_seconds': delay, 'message': f'连接中断，{delay:g}秒后重试（第{attempt+1}/{attempts}次）。'}
            for notify in (progress.get(), on_retry):
                if notify:
                    notify(event)
            wait(delay, checkpoint)
