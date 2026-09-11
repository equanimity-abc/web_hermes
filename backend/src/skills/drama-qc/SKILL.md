<!-- prompt: 验收用 tiktok_drama action=qc_episode。跑身份/口型/闪烁/响度四项脚本。skipped 不得记为通过。响度不达标只重 mix，禁止重渲各镜 clip。通过/退回在工作台由人点。所有步骤禁止候选项结果与重抽（禁止 generate_candidates / choose_candidate / 自动换种子）。 -->
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
5. 身份失败脏 `scene`/`motion`/`clip`，不重配音；**已锁画面不脏 scene、不重绘**。闪烁失败脏 `motion`/`clip`，禁止自动重做 I2V。
6. 禁止替用户点通过。锁和验收是人的权力。
7. **禁止候选项与重抽：** 身份不过且画面未锁时提示人改定妆后单次出图；已锁则提示先解锁再换图。禁止候选墙、禁止换种子自动重抽、禁止备用供应商跳转。
8. **步骤契约（正式输出）：**
   - `step1_script/`：剧本唯一真相源（`epNN.md` + `epNN/shots.json`），冻结后自动化不得改写；仅工作台手动改剧本可更新。
   - `step2_character/{temp,output,state}/`：角色定妆；角色名单从 step1 读取；正式图在 `output/`。
   - `step3_scene/{temp,output,state}/`：分镜画面；叙事从 step1、定妆从 step2；正式画面在 `output/`。
   - `step4_video/{temp,output,state}/`：运动片 / 口型视频（I2V·lip）。
   - `step5_audio/{temp,output,state}/`：配音 VO。
   - `step6_final/{temp,output,state}/`：单镜成片 + 整集导出。
   - 下一步只认正式 `output`（或 step1）；不满足则日志报错并 Fail Loud。

## 不要做

- 不要把人工抽看当成脚本通过。
- 不要为响度重做 VO / 画面。
- 不要改 `agent/loop.py`。
