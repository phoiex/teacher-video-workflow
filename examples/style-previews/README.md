# 风格样片

[在线试看](https://phoiex.github.io/teacher-video-workflow/)

十段均为8秒、1080p30、静音，由 DeepSeek Flash（max）通过 DeepSeek Harness 生成场景，再由本机渲染器导出。各会话使用对应的风格 Skill 与参考图。

三个信息对象按60%、30%、10%的示意权重汇总，便于比较画面材质、构图和动作。拼贴片尾补齐了等式中的百分号。

视频与封面保存在 `assets/style/`，本目录按风格保存场景源码与导出参数。原作者参考作品和许可见[来源说明](../../assets/style/CREDITS.md)。

安装渲染器后，可重新导出指定样片（不调用模型或配音）：

```sh
.venv/bin/python scripts/render_style_preview.py warm
```

视频与源码的哈希、模型和检查范围见[样片清单](../../assets/style/previews.json)。
