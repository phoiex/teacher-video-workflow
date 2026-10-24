"""阿里云百炼语音配置，凭据从本地环境读取。"""
import os
import re

MODEL = os.environ.get('TTS_MODEL', 'qwen-audio-3.0-tts-plus')


def read_credential(name):
    key = {'API Key': 'DASHSCOPE_API_KEY', 'Workspace ID': 'DASHSCOPE_WORKSPACE_ID'}[name]
    value = os.environ.get(key, '').strip()
    if not value:
        raise ValueError(f'请在 .env 中填写 {key}。')
    if name == 'Workspace ID' and not re.fullmatch(r'[a-zA-Z0-9-]+', value):
        raise ValueError('百炼工作空间 ID 格式不正确。')
    return value
