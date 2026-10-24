# 中文去 AI 味写作 Skill（优化版）

用于中文写作和 AI 使用过程，减少文稿、说明文档、代码注释及界面文案中的 AI 腔调，让表达自然、准确、直接。

适用于技术博客、产品说明、API 文档、UI 微文案、社交媒体、发行说明和学术写作。

## 本版调整

在原版规则基础上，补充和细化了虚假对比、无端防御、定语堆叠、总分口号、过度叙事和过度安抚等问题的处理。按写作场景区分标点、口语化程度和中英留白，并加入审稿检查模式。

完整规则见 [SKILL.md](./SKILL.md)。

## 使用

将本仓库作为一个 Skill 导入支持 `SKILL.md` 的 AI 工具，调用名称为 `deslop-zh`。也可以直接读取 [SKILL.md](./SKILL.md)，将其作为中文改写与审稿规范。

默认模式直接输出改写后的文本。需要审稿时，明确提出检查要求，工具会按规则编号列出原句与修改建议。

## 来源与致谢

本项目是基于 **[ninehills/public-skills](https://github.com/ninehills/public-skills)** 中的 **[deslop-zh](https://github.com/ninehills/public-skills/blob/main/deslop-zh/SKILL.md)** 制作的优化版本。原版提供了中文去 AI 味写作的核心原则、模式归纳、场景策略和示例，感谢原作者及贡献者的工作。

本轮迭代也参考了凡特 Phant 的视频 **[《AI 垃圾文风实力排行》](https://www.bilibili.com/video/BV1WfJr6kE6H/)** 提出的文风问题。Skill 内原有的其他参考来源继续保留在 `metadata.sources` 中。

沿用原项目的 MIT 许可，保留原版权声明，详见 [LICENSE](./LICENSE)。
