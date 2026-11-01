# 极简动态排版

用大字、数字和少量图标组织视觉重点。黑白与留白形成清楚的层级，关键词通过位置、替换、遮罩揭示和大小变化参与解释。

适合开场问题、成对概念比较、关键数值和回顾。字的变化跟随含义：对照项并排出现，变化前后的词在同一位置替换，数字按计算过程更新。学生需要阅读时让画面停稳。

原作者 Skill 和组件以 Remotion 实现。参考其中的卡片结构、文字动效和缓动参数，在本工作流的自包含 HTML 中按场景时刻求值；旁白长度和教师指定时长决定停留时间。中文字体选择系统中清楚可读的字形。

[参考画面](../assets/style-reference/kinetic-typography.png) · [作者 Skill](../references/upstream/kinetic-typography/01-SKILL.md) · [卡片组件](../references/upstream/kinetic-typography/02-Recap.tsx) · [视觉参数](../references/upstream/kinetic-typography/03-tokens.ts) · [许可](../references/upstream/kinetic-typography/04-LICENSE)

来源：IskakovDamir/apple-motion，作者独立整理的风格工具。组件为参考代码，本分支按当前课程渲染接口适配。
