"""英文按句子和完整单词拆配音，字幕使用对应音频的真实起止时间。"""
import re
import textwrap

LINE_WIDTH = 60


def _sentences(text):
    start = 0
    for match in re.finditer(r'[.!?][\"\u201d\u2019]?(?=\s+|$)', text):
        part = text[start:match.end()]
        if re.search(r'\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|vs|e\.g|i\.e)\.$', part, re.I):
            continue
        if re.search(r'(?:\b[A-Z]\.)+$', part):
            continue
        yield part
        start = match.end()
    if text[start:].strip():
        yield text[start:]


def _lines(text):
    return textwrap.wrap(text, width=LINE_WIDTH, break_long_words=False, break_on_hyphens=False)


def english_speech_chunks(text):
    result = []
    for sentence in _sentences(text):
        lines = _lines(sentence)
        result.extend(' '.join(lines[i:i+2]) for i in range(0, len(lines), 2))
    if any(len(part) > 500 for part in result):
        raise ValueError('英文讲稿中有过长的连续字符，请检查链接或未分词的文本。')
    if re.sub(r'\s+', '', ''.join(result)) != re.sub(r'\s+', '', text):
        raise ValueError('配音拆段改变了讲稿')
    return result


def caption(text, language='zh'):
    if language != 'en':
        return text
    words = text.split()
    normalized = ' '.join(words)
    if len(normalized) <= LINE_WIDTH:
        return normalized
    options = [(' '.join(words[:i]), ' '.join(words[i:])) for i in range(1, len(words))]
    options = [(left, right) for left, right in options if max(len(left), len(right)) <= LINE_WIDTH]
    if options:
        left, right = min(options, key=lambda pair: abs(len(pair[0]) - len(pair[1])))
        return left + '\n' + right
    return '\n'.join(_lines(text))
