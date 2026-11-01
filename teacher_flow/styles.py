"""界面选项、制作分支与参考材料共用一份风格目录。"""
import json

from .common import TOOL, PRODUCTION_SKILL, digest

CATALOG = json.loads((TOOL / 'assets/style/catalog.json').read_text())
DETAILS = {item['name']: item for item in CATALOG['presets']}
PRESETS = {name: (item['branch'], item['description']) for name, item in DETAILS.items()}
KEEP = "沿用当前风格"


def validate_preset(value):
    value = str(value or "").strip()
    if value and value not in PRESETS:
        raise ValueError("请选择已有的画面风格，其他要求可写在风格说明中")
    return value


def resolve(choice, details, current=""):
    choice = str(choice or "").strip()
    if choice == KEEP:
        choice = current
    choice = validate_preset(choice)
    details = str(details or "").strip()
    if not choice:
        choice = "自定义" if details else "自由设计"
    if choice == "自定义" and not details:
        raise ValueError("请填写自定义风格说明，或选择自由设计")
    return {"style_preset": choice, "style": details}


def branch(style="", preset=""):
    if preset in PRESETS:
        return PRESETS[preset][0]
    # 已开始的旧版课程仍使用原有文字判断。
    style = style.lower()
    if "暖" in style:
        return "warm-explainer.md"
    if "ascii" in style or "终端" in style:
        return "ascii-terminal.md"
    if any(word in style for word in ("科技", "空间", "openfilm", "代码动画")):
        return "openfilm-cinematic.md"
    return None


def choices_markdown():
    blocks = []
    for name, (_, description) in PRESETS.items():
        item = DETAILS[name]
        text = f"**{name}**：{description}"
        if item.get('image'):
            text += f"\n\n![{name}参考画面](http://127.0.0.1:8788/teacher-style/{item['image']})"
        if item.get('video_url'):
            text += f"\n\n[查看参考作品]({item['video_url']})"
        blocks.append(text)
    return "\n\n".join(blocks)


def preview_images(preset):
    name = DETAILS.get(preset, {}).get('image')
    if not name:
        return []
    path = TOOL / 'assets/style' / name
    return [{'name':preset, 'path':str(path), 'sha256':digest(path.read_bytes())}]


def reference_sources(preset):
    sources = []
    for item in DETAILS.get(preset, {}).get('sources', []):
        path = (PRODUCTION_SKILL / item['file']).resolve()
        if not path.is_relative_to(PRODUCTION_SKILL.resolve()) or not path.is_file():
            raise ValueError('风格参考材料路径无效')
        sources.append({**{key: item[key] for key in ('id', 'name', 'kind', 'source_url', 'sha256')},
                        'path': str(path)})
    return sources
