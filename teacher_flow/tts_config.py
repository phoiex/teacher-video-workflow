"""阿里云百炼语音配置，凭据从本地环境读取。"""
import os
import re

MODEL = os.environ.get('TTS_MODEL', 'qwen-audio-3.0-tts-plus')
VOICE = os.environ.get('TTS_VOICE', 'longanlingxin')
LEGACY = {'model': 'qwen-audio-3.0-tts-plus', 'voice': 'longanlingxin'}


def snapshot():
    return {'model': MODEL, 'voice': VOICE}


def for_course(course):
    return dict(course.get('tts_settings') or LEGACY)


def clip_name(text, instruction, settings):
    from .common import digest
    fields = {'text': text, 'instruction': instruction, 'voice': settings['voice']}
    if settings != LEGACY:
        fields['model'] = settings['model']
    return 'tts_' + digest(fields)[:24]


def read_credential(name):
    key = {'API Key': 'DASHSCOPE_API_KEY', 'Workspace ID': 'DASHSCOPE_WORKSPACE_ID'}[name]
    value = os.environ.get(key, '').strip()
    if not value:
        raise ValueError(f'请在 .env 中填写 {key}。')
    if name == 'Workspace ID' and not re.fullmatch(r'[a-zA-Z0-9-]+', value):
        raise ValueError('百炼工作空间 ID 格式不正确。')
    return value
