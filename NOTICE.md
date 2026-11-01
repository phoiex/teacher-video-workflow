# 来源与许可

| 内容 | 来源与许可 |
|---|---|
| Dify 工作流平台及 `dify-overlay/` | [langgenius/dify](https://github.com/langgenius/dify)，固定提交见 `dify-base.json`。改动沿用 [Dify 许可](licenses/DIFY-LICENSE)，保留原界面标识。 |
| 中文去 AI 味 Skill | [phoiex/deslop-zh](https://github.com/phoiex/deslop-zh)，基于 [ninehills/public-skills](https://github.com/ninehills/public-skills) 优化，保留 [MIT 版权声明](skills/deslop-zh/LICENSE)。 |
| ASCII 风格方法 | 参考 [world.execute-me-ascii](https://github.com/yym8224961/world.execute-me-ascii) 的公开创作提示词与播放链路。仓库提供整理后的方法和自己的参考图，未分发原作播放器、音乐或场景源码。 |
| 空间代码动画方法 | 参考 [OpenFilm](https://github.com/openfilm/openfilm) 与 [one-prompt](https://github.com/openfilm/examples/tree/main/one-prompt)。具体来源与提交记录在 Skill 分支中。 |
| 暖色图解方法 | 根据 B 站[《稳稳地接住你》](https://www.bilibili.com/video/BV1uTpU6GEHw/)的画面提炼，作者为忧郁水壶hu。 |

`teacher_flow/`、安装脚本和工作流配置为本项目代码，采用根目录的 MIT 许可。依赖的 Codex SDK、LiteLLM、Chromium、FFmpeg 和文档读取库使用各自许可，由安装脚本或包管理器下载。

新增七种风格的参考图片、原作者指南与代码见 [风格材料来源](assets/style/CREDITS.md)，逐文件来源及许可保存在 `skills/explainer-video-production/references/upstream/`。这些材料沿用原许可，不并入本项目 MIT 授权。

DeepSeek Harness 通过 `runtime/deepseek/package-lock.json` 固定版本，由 npm 安装；对应依赖保留各自许可。本项目仅在私有运行副本补接原生会话恢复入口，不分发个人账户或订阅配置。

本项目生成的十段参考短片及可编辑场景见[样片说明](examples/style-previews/README.md)，制作时使用的作者风格资料与代码许可仍按上述来源保留。
