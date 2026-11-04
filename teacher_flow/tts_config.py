"""阿里云百炼语音配置，凭据从本地环境读取。"""
import os
import re

MODEL = os.environ.get('TTS_MODEL', 'qwen-audio-3.0-tts-plus')
VOICE = os.environ.get('TTS_VOICE', 'longanlingxin')
LEGACY = {'model': 'qwen-audio-3.0-tts-plus', 'voice': 'longanlingxin'}


def with_language(settings, language):
    from .languages import normalize
    result = dict(settings)
    if normalize(language) == 'en':
        result['language'] = 'en'
    else:
        result.pop('language', None)
    return result


def snapshot(language='zh'):
    return with_language({'model': MODEL, 'voice': VOICE}, language)


def for_course(course):
    from .languages import for_course as course_language
    settings = dict(course.get('tts_settings') or LEGACY)
    return with_language(settings, settings.get('language') or course_language(course))


def clip_name(text, instruction, settings):
    from .common import digest
    fields = {'text': text, 'instruction': instruction, 'voice': settings['voice']}
    if {k: v for k, v in settings.items() if k != 'language'} != LEGACY:
        fields['model'] = settings['model']
    if settings.get('language', 'zh') != 'zh':
        fields['language'] = settings['language']
    return 'tts_' + digest(fields)[:24]


def read_credential(name):
    key = {'API Key': 'DASHSCOPE_API_KEY', 'Workspace ID': 'DASHSCOPE_WORKSPACE_ID'}[name]
    value = os.environ.get(key, '').strip()
    if not value:
        raise ValueError(f'请在 .env 中填写 {key}。')
    if name == 'Workspace ID' and not re.fullmatch(r'[a-zA-Z0-9-]+', value):
        raise ValueError('百炼工作空间 ID 格式不正确。')
    return value
