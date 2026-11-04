# 风格样片

[中文试看](https://phoiex.github.io/teacher-video-workflow/) · [English previews](https://phoiex.github.io/teacher-video-workflow/en.html)

十种风格各有中文和英文样片，共 20 段，均为 8 秒、1080p30、静音。原中文场景由 DeepSeek Flash（max）通过 DeepSeek Harness 生成，各会话使用对应的风格 Skill 与参考图。英文版沿用这些动画，翻译画面文字并调整排版后本地导出。

三个信息对象按60%、30%、10%的示意权重汇总，便于比较画面材质、构图和动作。拼贴片尾补齐了等式中的百分号。

视频与封面保存在 `assets/style/`，本目录按风格保存中文场景；`en/` 保存对应英文场景和导出参数。原作者参考作品和许可见[来源说明](../../assets/style/CREDITS.md)。

安装渲染器后，可重新导出指定样片（不调用模型或配音）：

```sh
.venv/bin/python scripts/render_style_preview.py warm
.venv/bin/python scripts/render_style_preview.py warm --language en
```

视频与源码的哈希、来源和检查范围见[中文清单](../../assets/style/previews.json)与[英文清单](../../assets/style/previews-en.json)。
