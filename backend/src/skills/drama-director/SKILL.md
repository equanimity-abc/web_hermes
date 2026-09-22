---
name: drama-director
description: 漫剧制作助手。分镜后调 suggest_coverage 给覆盖建议（hook/size_rhythm/reaction/silence，reaction 一集≤2，写入 coverage.suggestions）；渲前 classify_shots+budget 确认定场/对白并锁 scene；失败后 resume_produce 只补缺（返回 regenerate_plan）。只建议/只补缺，不改镜不加锁不点通过；无 QC/验收环节（质量由人在工作台把关）；禁止候选项/重抽/换供应商（只走火山方舟 Ark）。
version: 4.0
tags: [导演, 覆盖建议, 续跑, 只补缺]
---

# drama-director（漫剧制作助手）

## 目标
在漫剧制作两个环节辅助人，产出对应字段，**只建议、只补缺——不改镜、不加锁、不点通过**：
1. 分镜后 → 覆盖建议（`coverage.suggestions`）
2. 渲前/失败后 → 检查点与续跑（`regenerate_plan`）

## 输入
- 必填：`slug`、`episode`、已存在的 `shots.json`（每镜含 `n`/`kind`/`size`/`画面`/`字幕`/`对白`/`duration`/`dialogue_track`）。
- 选填：续跑时上次 `job_id`；整集重渲 `force`。
- 缺失处理：无 `shots.json` → 提示先 `parse_shots`，不调用。

## 流程（按场景分发）

### A. 分镜后 —— 覆盖建议
1. 调 `tiktok_drama action=suggest_coverage slug=… episode=…`。
2. 读 `coverage.suggestions`，按 `type` 分类念给用户。
3. 停，等人在工作台处理「采纳 / 忽略 / 锁定类型」。

### B. 渲前 / 失败后 —— 检查点与续跑
1. 渲前：确认已 `classify_shots`（定场 L0 / 对白 L1）；看 `budget`，超支先提醒调预算。
2. 渲前：对白镜未锁 `scene` → 提醒人先锁画面再开口型。
3. 导出前：BGM 无 license → 禁止导出。
4. 失败后：用户说「继续 / 重试」→ `tiktok_drama action=resume_produce slug=… episode=… [job_id=…]`。
5. 续跑只补缺：读 `regenerate_plan`，已生成的 scene/motion/clip 跳过，只重新生成缺失文件。

## 输出格式

- 覆盖建议 `coverage.suggestions[]`：
```json
{"id":"reaction-3","type":"reaction","status":"open","shot":3,"after_shot":2,"title":"…","reason":"…","patch":{"kind":"reaction","size":"CU","speaker":"悟空"}}
```
  `type`：`hook`（前3秒钩子）/ `size_rhythm`（景别连跑≥3镜，ECU→CU→MCU→MS）/ `reaction`（对白切反应镜）/ `silence`（静音空洞，只读）。

- 续跑 `resume_produce` → `diagnosis.regenerate_plan`：
```
图片shot1不需要重新生成；视频shot1不需要重新生成
图片shot3不需要重新生成；视频shot3需要重新生成
```

## 约束
- 只建议、只补缺：不改 `kind`/`size`、不调 `lock_shot`/`patch`、不点「通过」。
- `reaction` 一集 ≤2 条；已锁 `kind`/`shot` 的镜不重复建议。
- 只补缺：已生成的图片/视频不重画；改词重画交人工在工作台手动点「重新生成」。
- 不整集盲渲（除非用户明确 `force`）。
- 禁止 `generate_candidates` / `choose_candidate` / 候选墙 / 换种子 / 供应商跳转（出图/视频只走火山方舟 Ark）。
- 无 QC/验收动作：不再调 `qc_shot` / `qc_episode`，质量由人在工作台把关。



