# 教师微课制作指令

指令版本：**v0.1.2，2026-10-21**。

本目录供本地 Codex 制作会话使用，适用于老师确认讲稿后的分镜与画面阶段。指令说明当前制作目标、固定讲稿、已有成果和课程工具接口。

| 文件 | 用途 |
|---|---|
| [base.md](./base.md) | 会话基础指令，说明课程制作职责与材料依据。 |
| [producer.md](./producer.md) | 会话总指令，说明制作职责、工具用法和 HTML 接口。 |
| [plan.md](./plan.md) | 初次安排全课分镜时的消息。 |
| [scene.md](./scene.md) | 当前段制作或续作消息，使用下表变量。 |
| [resume.md](./resume.md) | 接续已有会话中的分镜与画面制作。 |

`scene.md` 的变量为：

| 变量 | 含义 |
|---|---|
| `{scene_id}` | 当前段号，例如 `s03`。 |
| `{scene_number}` | 当前段在全课中的序号，从 1 开始。 |
| `{scene_total}` | 全课分镜总数。 |
| `{feedback}` | 老师本轮画面反馈；为空时可填「按已确认的课程要求完成当前段。」 |

`base.md` 用作会话的 `baseInstructions`，`producer.md` 用作制作任务的 `developerInstructions`。`plan.md`、`scene.md` 和 `resume.md` 分别用于计划、当前段制作与会话接续消息。各文件按原文加载，仅对 `scene.md` 替换上述变量。

课程工具包含材料读取、计划和源码保存、画面渲染及制作备注。`course_render` 接受可选 `time_fractions`，未传时生成单张中点预览。HTML 接口为 1920×1080、`window.SCENE` 和 `window.film.frame(t)`，具体用法见总指令。

接口依据为 [制作工具与消息装配](../codex_storyboard.py)、[会话运行接口](../codex_runtime.py)、[制作资源装配](../codex_jobs.py)、[分镜提示词](../prompts.py)和[画面渲染入口](../render.mjs)。中文表达使用 [deslop-zh](../../skills/deslop-zh/SKILL.md) 修订。制作 Skill 与风格分支作为画面设计参考，由制作资源装配代码提供。
