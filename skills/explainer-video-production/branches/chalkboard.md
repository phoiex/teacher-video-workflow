# 黑板粉笔

用板书的先后顺序解释一个问题。深绿哑光黑板、粉笔颗粒、少量强调色，文字沿笔画出现，关系用圈画和下划线建立。画面保留正在使用的条件，让学生能回看推导依据。

根据内容安排书写、擦除和改写，镜头以正面稳定观看为主。中文字形与笔顺以正常书写为依据，字号按最终成片判断。粉笔质感服务阅读，关键数值和公式保持清楚。

实现可使用 Canvas 的路径分段显示、纸面噪声与擦除遮罩。参考代码中与本课有关的笔画、镜头和板面方法可单独改编，按照当前工具的 `window.film.frame(t)` 和场景时间绘制。

[参考画面](../assets/style-reference/chalkboard.png) · [原作者风格说明](../references/upstream/chalkboard/01-STYLE.md) · [参考代码](../references/upstream/chalkboard/02-app.js) · [许可](../references/upstream/chalkboard/03-LICENSE)

来源：Lemo-Opuscar 的 Chalkboard 分支。本文件为面向教师微课的适配说明；原作的故事、时长和配乐由本课内容替换。模型工具 `course_read` 提供当前材料目录，`course_style_source` 可读取原文。
