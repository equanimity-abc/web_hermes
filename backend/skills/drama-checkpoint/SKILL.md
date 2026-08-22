<!-- prompt: 渲染/导出前必须做检查点：出图前 classify_shots（定场 L0 / 对话 L1）；渲前看预算 budget 不超支；导出前先 qc_episode 且 skipped 不得当通过。身份抽检失败会自动标脏 scene/motion/clip，但入队重渲必须人在工作台确认，禁止你自动点通过或自动烧贵模型。目标是「建议 → 人锁 → 只渲脏」，绝不整集盲渲。 -->
# drama-checkpoint

渲染与导出前的强制检查点。**只提醒、只建议，不做破坏性动作。**

## 渲前检查点

1. 分镜已 `classify_shots`（定场 L0、对白 L1、锁 kind 不覆盖）。
2. 看 `budget` 是否超支；超支先提醒人调高预算，不要硬渲贵模型。
3. 有对白镜未锁 `scene` 时，提醒人先锁画面再开口型。

## 导出前检查点

1. 先 `qc_episode`；`skipped` 不得记为通过。
2. 响度不达标只 `remix` 重混，不重渲各镜 clip。
3. BGM 无 license 禁止导出。

## 身份失败半自动

- `qc_shot` 身份失败会**自动标脏** scene/motion/clip（不重配音）。
- 但**入队重渲必须人在工作台点**；你不自动通过、不自动烧贵模型。

## 不要做

- 不要整集盲渲（除非用户明确要求 force）。
- 不要替人点验收「通过」。
- 不要改 `agent/loop.py`。