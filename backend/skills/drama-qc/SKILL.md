<!-- prompt: 验收用 tiktok_drama action=qc_episode。跑身份/口型/闪烁/响度四项脚本。skipped 不得记为通过。响度不达标只重 mix，禁止重渲各镜 clip。通过/退回在工作台由人点。 -->
# drama-qc

人是导演，Agent 是质检员。分数写进 `shots.json` 的 `qc`，**不要把 skipped 当成通过，不要为了响度去重渲 clip**。

## 何时调用

分镜已出画面/成片之后，用：

`tiktok_drama action=qc_episode slug=… episode=…`

然后停下来，把「待修 / 可点通过」和 `block_reason` 告诉用户，请他们在漫剧工作台 **验收页** 点 **通过** 或 **退回本镜**。

## 规则

1. **四项：** 身份（锁参考图余弦 ≥ 0.65）、口型（LSE-C/D mock 基线）、闪烁（相邻帧 SSIM ≥ 0.85）、响度（-16～-12 LUFS，目标 -14，真峰 < -1 dBTP）。
2. **`skipped` 不能点通过。** 缺依赖、没文件、没出分，一律待修。
3. **`n/a` 不挡关。** 定场无角色不抽身份；非对话特写不开口型。
4. **响度只重 mix。** 失败时提示 `mix_episode` / 工作台「重混音」，禁止 `rerender_shot` 各镜。
5. 身份失败脏 `scene`/`motion`/`clip`，不重配音。闪烁失败脏 `motion`/`clip`。
6. 禁止替用户点通过。锁和验收是人的权力。

## 不要做

- 不要把人工抽看当成脚本通过。
- 不要为响度重做 VO / 画面。
- 不要改 `agent/loop.py`。
