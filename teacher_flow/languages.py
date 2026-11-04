"""课程语言控制讲稿、画面文字、配音与字幕；教师界面仍使用中文。"""
from .common import DEFAULT_VOICE_INSTRUCTION

LABELS = {'zh': '中文（普通话）', 'en': 'English'}
VOICE_INSTRUCTIONS = {
    'zh': DEFAULT_VOICE_INSTRUCTION,
    'en': 'Clear English, calm tone, moderate pace.',
}


def normalize(value, *, default='zh'):
    text = str(value or '').strip().lower()
    if not text:
        return default
    if text in ('zh', 'zh-cn', '中文', '简体中文', '普通话', '中文（普通话）'):
        return 'zh'
    if text in ('en', 'en-us', 'en-gb', 'english', '英文', '英语'):
        return 'en'
    raise ValueError('课程语言请选择中文或 English。')


def for_course(course):
    return normalize((course.get('requirements') or {}).get('course_language')
                     or course.get('course_language'))


def voice_instruction(course):
    return (course.get('requirements') or {}).get('voice_instruction') or VOICE_INSTRUCTIONS[for_course(course)]


def instructions(language):
    if normalize(language) == 'en':
        return ('本课使用英文。讲稿正文、课程标题和学生看到的画面文字使用自然英文；'
                '初稿与独立改写保持同一语言。去AI写作资料中的通用表达原则适用，'
                '其中针对中文的措辞、标点示例不用于英文。采用适合受众口述的英文，'
                '保留专有名词、公式和教师确认的原文。面向教师的操作提示仍用中文。')
    return '本课使用简体中文讲稿、普通话配音和简体中文字幕；专有名词与公式按内容保留。'
