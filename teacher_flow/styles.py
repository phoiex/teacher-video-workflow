"""老师可选的画面方向；预设名称与制作分支分别保存。"""

PRESETS = {
    "暖色图解": ("warm-explainer.md", "暖色背景、清楚的图形和逐步标注，适合平实的知识讲解。"),
    "ASCII 终端科技": ("ascii-terminal.md", "深色终端、等宽字符、点阵和数据流，保持中文与图形可读。"),
    "空间代码动画": ("openfilm-cinematic.md", "用几何、空间层次和镜头变化解释关系，配色按课程安排。"),
    "自由设计": (None, "结合课程内容自由设计画面。"),
    "自定义": (None, "按老师填写的风格说明和参考素材设计。"),
}
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
    images = {'暖色图解':'warm.png','ASCII 终端科技':'ascii.png','空间代码动画':'openfilm.png'}
    return "\n\n".join(f"**{name}**：{description}" +
        (f"\n\n![{name}参考画面](http://127.0.0.1:8788/teacher-style/{images[name]})" if name in images else '')
        for name, (_, description) in PRESETS.items())


def preview_images(preset):
    from .common import TOOL, digest
    name = {'暖色图解':'warm.png','ASCII 终端科技':'ascii.png','空间代码动画':'openfilm.png'}.get(preset)
    if not name:
        return []
    path = TOOL / 'assets/style' / name
    return [{'name':preset, 'path':str(path), 'sha256':digest(path.read_bytes())}]
