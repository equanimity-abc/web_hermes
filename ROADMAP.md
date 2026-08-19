# 自研 Agent：源码消化 + 增量开发路线

对照 `hermes-agent` / `hermes-webui`，在现有 Vue3 + FastAPI 脚手架上逐步长出真 Agent。

**原则：** 学不变量与骨架，重写精简核心，不 fork 巨石。

---

## 你现在的真实位置

**通用腰（P0–P6）已齐：** 会话耐久化、Agent loop、工具 registry、SSE、审批、工作区沙箱、记忆与压缩。

**漫剧草稿成片（P7–P8 + D0–D8）已齐：** 可改、可锁、可单镜重渲的竖屏草稿流水线；I2V 失败回退静图运镜。

**下一刀：Q7 验收页。** Q6 已交付单人 action 稀疏关键帧（3–5 姿态 mock 补间，改姿态不重配音）。

---

## 源码位置

| 项目 | 路径 |
|------|------|
| hermes-agent | `D:\liangkai\myagent\my_agent_source\hermes-agent-main\hermes-agent-main\` |
| hermes-webui | `D:\liangkai\myagent\my_agent_source\hermes-webui-master\hermes-webui-master\` |
| 你的项目 | `D:\liangkai\myagent\my_tiktok_video\`（backend + frontend） |

---

## 总原则

1. **学骨架，不搬巨石** — 从 hermes-agent 学 loop / registry / 消息不变量；自己写几百行核心，别抄 `run_agent.py`。
2. **学合同，不 fork WebUI** — 从 hermes-webui 学 SSE 事件与会话模型；继续用 Vue3，别改它的 vanilla JS。
3. **一边读一边做** — 每个学习单元对应一个可演示功能；做完再进下一阶段。

---

## 目标架构（精简）

```
Vue3 UI
  ↕ REST + SSE（学 WebUI 合同，不抄 DOM）
FastAPI
  ↕ sessions / start / stream / cancel / approval
Agent.run() 循环
  ↕ OpenAI-compatible LLM（DeepSeek）
Tool Registry
  → file / terminal / web / 业务插件
```

**复用什么：** 消息格式、loop、registry、SSE 事件名、审批流。  
**长期：** 自己维护精简核心，而不是 import 整个 hermes-agent。

---

## Hermes-Agent 分层消化顺序

| 层 | 概念 | 优先级 | 对照源码 | 你项目落地 |
|----|------|--------|----------|------------|
| L1 | 对话循环 | **必读** | `run_agent.py` · `agent-loop.md` | `agent/loop.py` 精简版 while 循环 |
| L2 | 工具系统 | **必读** | `tools/registry.py` · `model_tools.py` · `toolsets.py` | `tools/registry.py` + 首批工具 |
| L3 | 消息 / 流式 / 缓存 | **必读** | `prompt_caching` · 角色交替不变量 | OpenAI 消息格式 + SSE 事件 |
| L4 | 会话 / 状态 | **必读** | `hermes_state.py` · WebUI sessions JSON | SQLite/JSON 持久化会话 |
| L5 | 配置 / 模型 | 够用即可 | `hermes_cli/config.py` · providers | 继续 `.env` + 单一 DeepSeek 客户端 |
| L6 | Skills / 插件 / 委派 | **延后** | `skills_*` · plugins · `delegate_task` | 业务稳定后再加 |
| L7 | CLI / Gateway / WebUI | 只懂边界 | 都调用同一个 `AIAgent` | Vue = WebUI 壳；不 fork 原 WebUI |

### 刻意不抄

- 12k 行 `run_agent.py` 整文件搬运
- Gateway / Telegram / Discord 等平台适配
- Profiles、Kanban、Curator、Cron 全家桶
- Fork hermes-webui 的 vanilla JS 再改成 Vue
- 一开始就做 prompt caching / 多 provider 插件矩阵
- 把业务能力塞进核心 loop（应用 Footprint Ladder）

### Footprint Ladder

新能力优先顺序：扩展现有工具 → 独立脚本/技能 → 插件 → **最后**才进核心 tool schema。  
核心每多一个 tool，每次 API 调用都要付钱。

---

## 开发阶段（边学边做）

每个阶段 = 一小段源码阅读 + 一个可演示的产品增量。做完再进下一阶段。

| 阶段 | 标题 | 周期 | 做 | 学 | 状态 |
|------|------|------|----|----|------|
| **P0** | 打地基 | 已完成 | DeepSeek 聊天 + SSE + 内存会话 + Vue UI | 熟悉自己的代码；对照 WebUI 的 SSE 概念 | ✅ 已完成 |
| **P1** | 会话耐久化 | 约 3–5 天 | 会话列表 API、磁盘/SQLite 持久化、侧边栏可用 | `hermes_state` + WebUI session JSON 模式 | ✅ 已完成 |
| **P2** | 真正的 Agent Loop | 约 1–2 周 | `run()` 多轮循环：LLM → tool_calls → 执行 → 再请求 | `run_agent.run_conversation` + `agent-loop.md` | ✅ 已完成 |
| **P3** | 工具系统 | 约 1–2 周 | registry + 3–5 个工具；SSE 推送 tool 事件；前端工具卡片 | `registry.py` → `model_tools` → `toolsets` | ✅ 已完成 |
| **P4** | 流式契约升级 | 约 3–5 天 | `chat/start` + `stream_id`；`token`/`tool`/`done`/`error`；取消生成 | WebUI `api/streaming.py` + `messages.js` | ✅ 已完成 |
| **P5** | 安全与工作区 | 约 1 周 | 危险命令审批、workspace 根目录、路径沙箱 | WebUI approval 合同；terminal 工具约束 | ✅ 已完成 |
| **P6** | 记忆与压缩 | 约 1 周 | 简单记忆文件 + 超长上下文摘要压缩 | memory 拦截路径；`context_compressor` 思想 | ✅ 已完成 |
| **P7** | 业务插件 | 按需 | 抖音漫剧等业务工具/技能，不改核心 loop | Footprint Ladder：能力放边缘 | ✅ 已完成 |
| **P8** | 成片 | 按需 | 分镜 → 配音 → ffmpeg 竖屏 mp4 | 能力继续放插件边缘 | ✅ 已完成 |
| **D0** | 分镜资产化 | 约 1 周 | `shots.json` + 单镜 `clip.mp4` + `rerender_shot` | 成片从黑盒变成镜头资产 | ✅ 已完成 |
| **D1** | 工作台骨架 | 约 1–2 周 | 分镜台 UI + `/api/drama/*` REST | 不靠聊天也能改一镜 | ✅ 已完成 |
| **D2** | 分层重做 + 锁 | 约 1 周 | `locked` + 指定层重渲 | 锁画面后改台词只换声/字幕 | ✅ 已完成 |
| **D3** | 剧情干预 | 约 1 周 | 剧本编辑器 + 脏镜提示 | 改结局悬念，未锁镜更新 | ✅ 已完成 |
| **D4** | 角色一致性 | 约 1 周 | 角色卡 + 参考图进 prompt + 音色 | 同一角色连续 5 镜更稳，可锁参考图 | ✅ 已完成 |
| **D5** | 候选墙 | 约 1 周 | 每镜 2–4 候选 + 点选锁定 + 手传 | 换图不重配音 | ✅ 已完成 |
| **D6** | 时间线 | 约 1 周 | 镜序/切点/转场/音量 + 导出 | 缩短 Shot4 0.4s 换转场立刻出新 mp4 | ✅ 已完成 |
| **D7** | 任务条 | 约 1 周 | 后台渲染 + 取消 + 重试 + 进度 | 渲 8 镜时聊天仍可用 | ✅ 已完成 |
| **D8** | I2V | 见专章 | 导演式干预到镜头层 | 对已锁关键帧做 2–3s 运动，失败回退静图运镜 | ✅ 已完成 |

---

## 学习单元（建议按 U1→U6）

### U1 · 能在纸上画出 while 循环

| | |
|--|--|
| **读** | `website/docs/developer-guide/agent-loop.md`；`run_agent.py` → `run_conversation`（只跟主路径） |
| **做** | 在自己项目写 `Agent.run()`：无工具，只多轮对话 |
| **过关** | 能口述：user → API → 无 tool_calls → 返回 |

### U2 · 理解工具如何注册与派发

| | |
|--|--|
| **读** | `tools/registry.py`（全文）；任意一个简单 tool 文件的 `register()`；`model_tools.handle_function_call` |
| **做** | 实现 registry + echo/calculator 工具，接入 loop |
| **过关** | 模型能调工具并拿到结果继续回答 |

### U3 · 消息格式与不变量

| | |
|--|--|
| **读** | `AGENTS.md` 中 Prompt Caching / alternation 段落；assistant `tool_calls` + `role=tool` 消息形状 |
| **做** | 断言：历史写入符合 OpenAI 格式；系统提示会话内不变 |
| **过关** | 故意破坏交替能发现 bug |

### U4 · 会话持久化

| | |
|--|--|
| **读** | `hermes_state.py` 的 SessionDB 接口轮廓；WebUI session 字段 |
| **做** | `GET /api/sessions` + 磁盘持久化；修好侧边栏 stub |
| **过关** | 重启进程后会话仍在 |

### U5 · 前端看到工具进度

| | |
|--|--|
| **读** | hermes-webui `api/streaming.py` 事件类型；ARCHITECTURE 中 `token`/`tool`/`done`/`error` |
| **做** | SSE 增加 tool 事件；Vue 渲染工具卡片 |
| **过关** | 一次工具调用在 UI 可见 |

### U6 · 取消与审批

| | |
|--|--|
| **读** | WebUI approval 合同；interrupt 相关路径（概念） |
| **做** | Stop 按钮 + 危险工具审批弹窗 |
| **过关** | 中途取消不留下半截假成功 |

---

## 后端 API 能力优先级（对照 WebUI）

| 优先级 | 概念 | 最小表面 |
|--------|------|----------|
| **P0** | Health | `GET /api/health` |
| **P0** | Sessions | list / get / create / delete；消息 OpenAI 形；磁盘或 SQLite |
| **P0** | Chat + SSE | 流式 token；最终 persist |
| **P1** | Cancel | 中断生成；终端事件诚实（cancelled ≠ done） |
| **P1** | Busy / queue | 流进行中拒绝或排队第二次发送 |
| **P1** | Approvals | SSE `approval` + `POST …/approval/respond`（若有危险工具） |
| **P2** | Stream status + 客户端 inflight | 刷新后可重连，不伪造「已完成」 |
| **P2** | Uploads + workspace | 附件进工作区；路径安全的文件读 |
| **P3+** | 事件 journal / 多 tab / clarify / compress | 有痛点再做 |

---

## 建议的下一步行动

P0–P8 + D0–D8 已齐。业务继续放插件与 `/api/drama/*`，**不要改 `agent/loop.py`**。

下一刀 **Q7**：验收页接入 QC 四项；整集「待修/通过」；`skipped` 不能点通过；响度只重 mix。

---

## 漫剧智能体制作流水线（D0–D8）

一句话目标：**Agent 负责生成与重做，工作台负责改、锁、验收；成片是镜头资产拼出来的，不是一次 `render_episode` 黑盒。**

现在缺的不是再写一轮剧本工具，而是：**结构化资产 + 分镜级重渲 + 可人工改的工作台**。聊天里改 Markdown 再整集重渲，做不到「微调每个视频」。

### 产品原则

1. **人是导演，Agent 是摄制组。** 每一步默认可改、可锁、可只重做下游。
2. **锁住的资产禁止被 Agent 覆盖。** 改剧情只让「未锁定且受影响」的镜头变脏。
3. **粒度到镜头，而不是到集。** 一集是时间线；可改的是 Shot 的画面 / 运镜 / 台词 / 声 / 字幕 / 转场。
4. **聊天不替代工作台。** Agent 用 Skill 推进流程；精细修改走界面。Hermes：Skill 管流程，Tool 管动作，核心 loop 不膨胀。
5. **先做可改的静图运动片，再接 I2V。** 没有分镜工作台就接视频模型，钱和返工会爆炸。

### 产品分层（通用腰 + 漫剧尖端）

| 层 | 是什么 | 用户感知 |
|--|--|--|
| **通用腰** | 对话、工具循环、会话、审批、记忆、工作区 | 「这是个能干事的 Agent」 |
| **漫剧尖端** | 策划→分镜→成片的默认工作流 + 工作台入口 | 「做漫剧特别顺」 |
| **可扩展边** | 其它业务以后也走插件/技能，不进核心 | 不做成「只能做漫剧的壳」 |

```text
┌─────────────────────────────────────────┐
│  Vue：通用聊天 + 「漫剧工作台」入口（壳）   │
└──────────────────┬──────────────────────┘
                   │ SSE + /api/drama REST
┌──────────────────▼──────────────────────┐
│  瘦核心：loop / registry / session /     │
│  stream / approval / memory / workspace │  ← 学 Hermes 不变量，别抄巨石
└──────────────────┬──────────────────────┘
         ┌─────────┴─────────┐
         ▼                   ▼
   通用工具（少）        边缘能力（多）
   calculator…          plugins/tiktok_drama
   read/write_file      skills/tiktok-drama/*（计划）
   memory_*             工作台 REST：人手动改，不经过模型
```

**务必借鉴：** 窄腰（一个 `tiktok_drama(action=…)`）；Skills 管流程、Tools 管动作；新模型/渲染器进 `plugins/`，不改 loop。  
**刻意不抄：** Gateway 全家桶、Kanban、12k 行 `run_agent.py`、fork WebUI。

### 完整流水线（每步都要能手动改）

| 阶段 | Agent 做什么 | 你在界面改什么 | 锁住之后 |
|--|--|--|--|
| **1. 立项** | 题材、受众、logline、集数 | 改标题/定位/禁区 | 系列设定不被乱改 |
| **2. 世界观/人设 Bible** | 角色、关系、口头禅、视觉锚 | 改人设全文；上传定妆图 | 后续出图必须吃参考 |
| **3. 角色资产** | 三视图、服装、配色 | 换参考图、定音色/语速 | 全片脸和声一致 |
| **4. 系列大纲** | 每集钩子/反转/悬念 | 拖拽调集顺序、改集摘要 | 改大纲只脏未锁的集 |
| **5. 分集剧本** | 对白、钩子、时长 | 改词、加删场、标角色 | 不自动改已锁分镜 |
| **6. 分镜表** | 画面/运镜/时长/情绪 | 改每个 Shot 字段、拆镜、调序 | 只重渲脏镜头 |
| **7. 关键帧** | 按画面出图 | 选 1/N 候选、改 prompt、重抽、手传图 | 锁图后改运镜不换图 |
| **8. 镜头运动** | 推拉摇、转场、调色 | 改 camera、zoom、shake、xfade | 锁运动后只换声/字幕 |
| **9. 配音** | 按角色 TTS | 改台词、音色、情绪、音量、起止 | 锁音后画面可单独动 |
| **10. 字幕** | 从对白生成 | 改字、位置、字号、出现时间 | 不重出图 |
| **11. BGM/音效** | 按情绪配乐（后期） | 换轨、duck 人声 | 独立层 |
| **12. 时间线成片** | 拼接 + 转场 | 微调切点、预览、导出 | 导出不覆盖源资产 |
| **13. 验收** | 列出脏镜头/失败项 | 通过 / 退回某 Shot | 通过才算一集完成 |

「改剧情」不是只改 `ep01.md`，而是：改剧本 → 标哪些 Shot 脏 → 你确认后才重做画面/声。  
「微调每个视频」是镜头级：重抽画面、换运镜、重配一句、改字幕、只导出该 clip。

### 数据怎么存（工作台的真相源）

Markdown 给 Agent 写，JSON 给界面改：

```text
workspace/dramas/{slug}/
  project.json              # 元数据、当前阶段、锁
  bible.md + characters/*.png
  outline.md / outline.json
  episodes/epNN.md          # 剧情（人可改）
  videos/epNN/
    shots.json              # 分镜真相：字段 + 锁 + 脏
    shot03_scene.png        # 可手传覆盖
    shot03_overlay.png
    shot03.mp3
    shot03.mp4              # 单镜成片
  videos/epNN.mp4           # 导出，可随时重拼
```

每个 Shot 字段：`画面 / prompt / camera / duration / 对白 / 字幕 / locked[] / dirty[] / status`。  
没有 `shots.json`，界面只能改大段 Markdown，细力度做不出来。

### 界面

聊天继续当 Agent。**旁边加「漫剧工作台」**，不要做成第二个聊天。

| 页 | 干什么 | 状态 |
|--|--|--|
| 项目列表 | 新建 / 打开 / 阶段进度 | D1：打开已有项目 |
| 系列 | Bible、角色卡、大纲时间线 | ✅ D4 |
| 分集剧本 | 左大纲右剧本；改词后提示受影响 Shot | ✅ D3 |
| **分镜台（核心）** | 左 Shot 列表，中预览，右检查器 | ✅ D1 |
| 候选墙 | 一镜多图，点选锁定 | ✅ D5 |
| 时间线 | 镜序、转场、音量条、整集预览 | ✅ D6 |
| 任务条 | 渲染队列、失败重试、取消 | ✅ D7 |

检查器目标：…D6 已有时间线镜序/切点/转场/音量与导出不毁源 clip；D7 已有后台渲染任务条（进度/取消/重试）。回滚版本仍待做。

### Agent 怎么配

```text
通用腰：loop / session / SSE / 审批 / 记忆 / 沙箱   ← 基本不动
    ↓
Skill：drama-pipeline（何时 init、何时出分镜、何时停下来等人）
    ↓
Plugin：tiktok_drama 扩 action（CRUD 镜头、重渲一层、不进核心 schema）
    ↓
工作台 REST：给人手动改，不经过模型
```

Agent 适合：从一句话拉出系列、按 Bible 补分镜、按你的批注重写某镜。  
不适合：拖转场时长、选第 3 张候选图——这些走 UI。  
长任务（出图/TTS/I2V）必须 **后台队列 + 进度事件**（D7），不能卡死一轮聊天。

Skills 建议目录：

```text
skills/
  drama-director/SKILL.md   # Q5 已落地：suggest_coverage，只建议不改镜
  drama-vertical-short/SKILL.md   # 计划
  drama-character-bible/SKILL.md  # 计划
plugins/              # 已有 tiktok_drama.py
```

### 开发阶段

| 代号 | 做什么 | 验收 | 状态 |
|--|--|--|--|
| **D0** | `shots.json`；按镜输出 `clip.mp4` 再拼接；`rerender_shot` | 改 Shot 3 字幕，只重渲 Shot 3，其它镜不动 | ✅ |
| **D1** | 项目列表 + 分镜台 + 检查器 + 预览；`GET/PATCH` 项目、集、Shot | 不靠聊天也能改对白、运镜、时长并保存 | ✅ |
| **D2** | `rerender` 指定 `scene \| voice \| overlay \| clip`；`locked` 生效 | 锁住画面后改台词，只换声和字幕 | ✅ |
| **D3** | 剧本编辑器；「这句改了影响 Shot 2/3」；一键只重写脏镜 | 改结局悬念，未锁镜更新，已锁镜不动 | ✅ |
| **D4** | 角色卡 + 参考图进 prompt；每镜选角色；音色绑定 | 同一角色连续 5 镜比现在稳，可锁参考图 | ✅ |
| **D5** | 每镜出 2–4 张候选，点选锁定，可手传覆盖 | 不喜欢就换图，不重配音 | ✅ |
| **D6** | 镜序拖拽、转场、切点、音量；导出不毁源 clip | 只把 Shot 4 缩短 0.4s 并换转场，立刻出新 mp4 | ✅ |
| **D7** | 后台渲染、可取消、失败重试、工作台进度条 | 渲 8 镜时聊天仍可用 | ✅ |
| **D8** | I2V（口型/BGM 另开里程碑） | 对已锁关键帧做 2–3 秒运动，失败回退静图运镜 | ✅ |

**D8 已交付 I2V + 静图回退。** 口型/BGM/场景模型/逐关键帧见 **Q0–Q8**。

### 拍板的三件事

1. **先 D0+D1**（资产化 + 分镜台），不要先接视频模型。 ← 已做完  
2. **剧情改在剧本页，画面/声改在分镜台**，Agent 只处理「重写/重抽」按钮。  
3. **核心 loop 继续冻结**；新能力进 `tiktok_drama` action + `/api/drama/*`。

---

## 专业级成片（Q0–Q8）

一句话目标：**同一套工作台与锁/脏层，把草稿流水线升级成「分镜类型驱动的摄制组」——对的镜用对的模型，音频分轨，口型只打在该打的脸上，动画走稀疏关键帧而不是全片 24fps。**

评审结论已并入正文：骨架与顺序保留；补齐周期重排、调研闸门、量化 QC、成本前置、Q6 范围缩窄、speaker/版权。

### 大师诊断（相对专业 AI 漫剧）

D0–D8 解决的是 **可改**。专业成片解决的是 **像一部剧**。差距不在再写一个 `render_episode`，而在四件产品级能力：

| 缺口 | 现在 | 专业水准 | 错误接法 |
|--|--|--|--|
| **BGM / 音效** | 只有 TTS + 字幕烧进画面 | VO / BGM / SFX / 环境 分轨；对白时 BGM 自动 duck；成片 -14 LUFS；曲库来源可审计 | 把一首 mp3 直接混进每镜 clip，改词就要重混整集 |
| **口型** | 嘴是静图或 I2V 胡动 | **仅对话特写** 走 talking-head；对不上就回退闭口静图；LSE 分数不达标则降级 | 全镜上 Wav2Lip（远景、群像、动作镜必崩） |
| **场景用不同模型** | 全局一个 `IMAGE_GEN_PROVIDER` + 一个 `I2V_PROVIDER` | 每镜 `kind` → 路由表：定场用便宜静图，对白用角色一致性，动作用贵 I2V；按钮旁显示预估金额 | 每镜都跑同一套 Kling，成本 ×10、脸漂 ×10 |
| **「逐帧动画」** | Ken Burns / 2–3s I2V | **导演式稀疏关键帧**（单人动作镜 3–5 姿态 + 补间/I2V），不是 24fps 手绘 | 全片逐帧、或多角色同框动作当默认验收 |

商业抖音 AI 漫剧能看的，几乎都是：**定妆锁脸 + 特写开口 + 动作短 I2V + 音乐情绪**，外加导演在工作台锁资产。不是「一集一个视频模型黑盒」。

### 质量阶梯（只升该升的镜）

```text
L0  静图 + Ken Burns          ← D8 fallback，定场/群像默认
L1  单关键帧 I2V 2–4s         ← D8，反应镜 / 环境微动
L2  口型 talking-head         ← Q2，仅 dialogue CU/MCU
L3  起止双关键帧 I2V          ← Q3，动作起势→落势
L4  3–5 姿态稀疏关键帧        ← Q6，仅单人 action；专业观感上限
L5  全片 24fps / 动漫中间帧   ← 不做默认路径；单镜实验、人工锁后再说
```

**本计划把「逐帧」定义为 L4，不是 L5。** L5 留给以后单镜实验开关，禁止作为默认渲染。

### 镜头分类（路由的输入）

每镜增加 `kind` + `size` + `speaker`（可手改、可被 Agent 建议）：

| kind | 景别 size | 画面 | 运动 | 口型 | 音频 |
|--|--|--|--|--|--|
| `establishing` | WS | 场景静图（便宜） | L0 缓推 | off | BGM + 环境 |
| `insert` | CU 物件 | 静图 | L0 / 微 I2V | off | SFX |
| `dialogue` | MCU/CU | 角色一致性模型 | L1 idle 或 L2 | **on**（须有 speaker） | VO 主；BGM duck |
| `reaction` | CU | 同角色模型 | L1 眨眼/微表情 | off | 短 VO 或静 |
| `action` | MS | 角色+场景 | L3；单人可升 L4 | off | SFX + 音乐重音 |
| `crowd` | WS | 不必锁每张脸 | L0 | off | 环境 |
| `title` | — | 平面/标题卡 | L0 | off | sting |

默认规则：**未分类 = 有对白 → `dialogue`，否则 `establishing`。** 有对白时 `speaker` 默认该镜 `角色[0]`，检查器必须能改。锁 `kind` 后 Agent 不得覆盖。

**Q0 检查器必有 speaker 下拉**（角色卡列表）。没有 speaker，Q2 无法把口型打到正确的脸上。

### 模型调研闸门（Q0 前半，未完成不准接真 API）

产出一份项目级调研卡，写入 `models.json` 的 `providers`（不要另起不可执行的文档当真相源）：

| 字段 | 含义 |
|--|--|
| `id` | mock / http / kling / hailuo / musetalk / wav2lip … |
| `available` | 当前环境能否调用（key、地域、SDK） |
| `cost_per_shot` | 单镜估费（美元或人民币，统一一种并标明） |
| `rpm` / `timeout_s` | 限流与超时 |
| `fallback` | 失败下一档（必须落到 mock 或 L0） |
| `notes` | 商用条款一句话 |

原则：**先 mock 调通脏层/队列/回退，再把 `available: true` 的真模型接上。** 真模型接不上时，Q2/Q3/Q6 按「降级交付」验收 mock 链路，不阻塞 Q1/Q5/Q7。

### 模型路由表（项目级真相源）

`workspace/dramas/{slug}/models.json`（系列覆盖全局默认）：

```text
{
  "currency": "CNY",
  "providers": {
    "mock":      { "available": true,  "cost_per_shot": 0,    "fallback": "l0" },
    "kling":     { "available": false, "cost_per_shot": 2.5,  "rpm": 10, "fallback": "mock" },
    "musetalk":  { "available": false, "cost_per_shot": 0.8,  "fallback": "mock" }
  },
  "image": {
    "establishing": { "provider": "http", "model": "flux-scene", "cost_per_shot": 0.05 },
    "dialogue":     { "provider": "http", "model": "char-lora", "refs": ["character"] },
    "action":       { "provider": "http", "model": "char-lora" }
  },
  "motion": {
    "establishing": { "ladder": "L0" },
    "dialogue":     { "ladder": "L2", "fallback": "L1" },
    "action":       { "ladder": "L3", "provider": "kling", "fallback": "L1" }
  },
  "lip":  { "provider": "musetalk", "only_kinds": ["dialogue"] },
  "bgm":  { "provider": "library", "duck_db": -12, "license": "user_upload" },
  "sfx":  { "provider": "library" }
}
```

适配器继续放 `plugins/` + `config.py`；**路由按镜读表，禁止再只读一个全局 I2V_PROVIDER。** 全局 env 只当默认值。

**成本前置（不等 Q8）：** 工作台「生成 I2V / 生成口型 / 生成关键帧」旁显示 `cost_per_shot` 与本集累计估算。Q0 就把字段和 UI 占位做上（现有 I2V 按钮即可挂上）。

### 音频总线（与画面同等的一层）

成片从「单轨 TTS」改成四轨再 mix：

```text
videos/epNN/
  shot03.mp3            # VO（已有）
  ep_bgm.wav            # 整集或按 cue 切
  shot03_sfx.wav        # 可选
  mix/epNN_mix.json     # cue：入点、duck、淡入淡出、license
```

规则：

1. BGM **不烧进** 单镜 `shotNN.mp4`；只在 **assemble / export** 混。改词不重出图。
2. 对白存在时 duck BGM（默认 -10～-14 dB）。
3. 导出目标 **-14 LUFS**（抖音），峰值不削波；Q7 用 ebur128 脚本卡线。
4. 工作台时间线增加 BGM 轨 + 音效点；和 D6 切点一样「改参数不毁源 clip」。
5. **版权（Q1 必做）：** 每条 BGM 必须有 `license`：`user_upload`（上传时勾选「我有商用权」）或 `catalog:<id>`（项目内授权/免费商用曲库条目）。没有 license 的曲子禁止进 export。本仓库默认不内置无授权曲包。

### 口型（窄范围）

输入：锁住的 `scene.png`（正脸/3/4 脸）+ 该镜 `voice.mp3` + `speaker`。  
输出：`shotNN_lip.mp4` → 再烧字幕。失败：`lip_source=fallback`，用闭口静图 + L0/L1。

禁区：`establishing` / `crowd` / `action` / 侧脸超过阈值 / 多角色同框未指定 speaker。

**降级交付（Q2）：** mock 口型（例如嘴部轻微开合的本地合成）+ http 适配器 + 失败回退 + LSE 脚本能跑出分数。真 MuseTalk/Wav2Lip 接上算完整交付，接不上不卡 Q1/Q5。

### 稀疏关键帧（专业「逐帧」）

每镜可选 `keys[]`：

```text
{ "t": 0.0, "pose": "起手", "file": "shot03_k1.png" },
{ "t": 1.2, "pose": "击中", "file": "shot03_k2.png" },
{ "t": 2.4, "pose": "收势", "file": "shot03_k3.png" }
```

运动：相邻关键帧做 I2V 或光流补间 → 拼成 `motion.mp4`。工作台：时间轴上钉 3–5 张，点选候选墙锁姿态。

**Q6 验收缩窄：仅单人 `action` 镜。** 多角色同框动作、对手戏对打，明确延后，不进 Q6 过关标准。降级交付：3 张关键帧 + mock/光流补间能重运动且不重 VO；真 I2V 补间算完整交付。

### 新层与锁（扩 D2，不推翻）

| 层 | 何时脏 | 锁住之后 |
|--|--|--|
| `scene` / `overlay` / `voice` / `clip` | 同 D2 | 同 D2 |
| `motion` | 改 camera / keys / kind 运动档 | 只换声/字幕/BGM |
| `lip` | 改对白、VO 或 speaker | 不重出图 |
| `mix` | 改 BGM/SFX/duck | 不重渲任何镜 |

`assemble` 仍只拼接 + mix。

### 量化 QC（脚本驱动，不靠人工扫 40 镜）

阈值写进 `models.json` 的 `qc` 段，Q7 只展示与卡关，算法在 Q4 起落地为可跑脚本（缺依赖时状态为 `skipped`，**不得记为通过**）：

| 指标 | 方法 | 默认阈值 | 不达标 |
|--|--|--|--|
| identity | 锁参考图 vs 镜内人脸，ArcFace 余弦 | ≥ 0.65 | 脏 `scene`/`motion`，提示重抽首帧 |
| 口型 | LSE-C 越高越好 / LSE-D 越低越好（SyncNet 系） | 以调研卡写入为准，先定相对 mock 基线 | `lip_source=fallback` |
| 闪烁 | 相邻帧 SSIM 或 LPIPS | SSIM 均值 ≥ 0.85（可调） | 脏 `motion` |
| 响度 | ffmpeg ebur128 | 综合响度 -16～-12 LUFS，目标 -14；真峰 < -1 dBTP | 只重 `mix` |

Q4 交付 identity 脚本 + 抽检入口；Q7 把四项收进验收页。人工抽看仍保留，但「通过」必须以脚本状态为准。

### Agent 怎么配（仍不改 loop）

```text
Skill：drama-director     根据剧本建议 kind/size/speaker/keys，等人锁
Skill：drama-audio        出 cue 单（情绪→BGM，动作→SFX）；拒绝无 license 的曲子
Skill：drama-qc           跑脚本分数，列出未通过镜
Plugin：tiktok_drama 扩 action
  classify_shots / set_model_route / mix_episode / generate_lip / generate_keys / qc_episode
工作台：改 kind/speaker、钉关键帧、听分轨、看分数与预估金额
```

### 开发阶段（评审后周期）

短刀（约 3–5 天）与重刀（约 3–4 周，允许降级）分开。合计大约 **14–18 周日历**，不是把每刀都写成 1 周。

| 代号 | 周期 | 做什么 | 验收（完整 / 降级） | 状态 |
|--|--|--|--|--|
| **Q0** | 约 3–5 天 | **闸门：** 填 `providers` 调研卡。`kind`/`size`/`speaker`；`models.json`（含 `cost_per_shot`）；检查器下拉；现有 I2V 按钮显示估费；未接新模型时路由只决定 L0/L1 | 对话镜 L1、定场 L0；有对白必能选 speaker；改 kind 只脏 motion/clip；无调研卡不准标 available | ✅ |
| **Q1** | 约 3–5 天 | BGM 上传或曲库条目；`license`；cue；duck；export 混音；时间线 BGM 轨 | 换有 license 的 BGM 立刻出新 mp4，clip 哈希不变；无 license 拒绝导出 | ✅ |
| **Q2** | 约 3–4 周 | 仅 `dialogue` 口型适配器；失败回退；`lip_source`；LSE 脚本能出分 | **完整：** 真口型模型 + 特写开口。**降级：** mock 口型链路 + 回退 + 远景不开口，仍算出片 | ✅ |
| **Q3** | 约 3–4 周 | 运动档 L0–L3 与 kind 绑定；估费；action 默认真 I2V、定场禁止 | **完整：** 8 镜最多 2 镜打贵 I2V。**降级：** 路由与预算 UI 正确，贵模型 available=false 时走 mock/L1 | ✅ |
| **Q4** | 约 1 周 | 运动仍吃角色参考；identity 脚本（ArcFace）；抽检入口 | 同角色连续镜可跑余弦分；低于 0.65 提示重抽首帧且不重配音 | ✅ |
| **Q5** | 约 3–5 天 | 导演语法建议：景别节奏、对白切反应镜、钩子 3s；Agent 只建议 | 一集可建议最多 2 个 reaction，人可删可锁 | ✅ |
| **Q6** | 约 3–4 周 | 单人 action 镜 3–5 关键帧 + 补间/I2V；候选墙锁姿态 | **完整：** 真 I2V 补间。**降级：** mock/光流补间，改姿态不重 VO。多角色同框不验收 | ✅ |
| **Q7** | 约 3–5 天 | 验收页接入 QC 四项；整集「待修/通过」 | 退回单镜；脚本 `skipped` 不能点通过；响度只重 mix | 计划 |
| **Q8** | 约 3–5 天 | 风格包填路由表；成本汇总（字段 Q0 已有） | 切「古风对话」后新镜走角色模型，定场仍便宜 | 计划 |

**顺序硬约束：**

```text
Q0（调研 + 分类 + speaker + 估费字段）
  → Q1（分轨 + 版权）
  → Q2（口型，可降级）与 Q3（运动档，可降级）可并行
  → Q4 identity 脚本
  → Q6 依赖 Q0 + Q3（可降级的运动档）
Q5、Q7 短刀，可分别与 Q4、Q2 后半并行
Q8 依赖 Q0 路由表已稳定
```

没有 kind/speaker 不准接口型；没有 license 不准混 BGM；没有调研卡不准把 provider 标成 available。

### 每刀的代码落点（保持窄腰）

| 刀 | 新文件（建议） | 工作台 | 插件 action |
|--|--|--|--|
| Q0 | `drama_models.py`、`models.json` | kind/size/**speaker**、I2V 估费 | `classify_shots` |
| Q1 | `drama_audio.py` | 时间线 BGM 轨、license 标记 | `mix_episode` |
| Q2 | `drama_lip.py`、LSE 脚本 | 「生成口型」+ 估费 | `generate_lip` |
| Q3 | 扩 `drama_i2v.py` ladder | 运动档 + 估费 | 沿用 `generate_i2v` |
| Q4 | `drama_qc.py` identity | 分数提示 | `qc_shot` |
| Q5 | Skill `drama-director` | 建议条，不自动锁 | `suggest_coverage` |
| Q6 | `drama_keys.py` | 关键帧钉 + 估费 | `generate_keys` |
| Q7 | 扩 `drama_qc.py` | 验收页 | `qc_episode` |
| Q8 | `styles/*.json` | 风格切换 | `apply_style` |

### 明确不做（本系列）

- 不改 `agent/loop.py`。
- 不把 Kling/口型设成全局默认。
- 不做全片 24fps 作为主路径。
- 不把 BGM 烘焙进 `shotNN.mp4`。
- 不在远景/群像上强行口型。
- 不把多角色同框动作放进 Q6 验收。
- 不在调研卡完成前把外部模型标为 `available: true`。
- QC 缺依赖时不把 `skipped` 当成通过。

### 评审备注（已吸收）

外部模型评估：**骨架与顺序正确，可开工；核心是补周期、调研前置、指标脚本化。** 六条已写入上文，对照如下。

| 序号 | 原建议 | 正文落点 |
|--|--|--|
| 1 | 短刀短排；Q2/Q3/Q6 按 3–4 周并允许降级 | 开发阶段表 |
| 2 | 开工前模型调研：可获得性、单价、限流、降级；先 mock | Q0 闸门 + `providers` |
| 3 | identity ArcFace≥0.65；口型 LSE-C/D；闪烁；-14 LUFS | 量化 QC + Q4/Q7 |
| 4 | `cost_per_shot` 与生成按钮估费，不等 Q8 | Q0 字段/占位，Q2/Q3/Q6 按钮 |
| 5 | Q6 先限定单人动作镜 | Q6 验收缩窄 |
| 6 | Q1 版权/曲库；Q0 检查器 speaker | 音频规则第 5 条；镜头分类 |

---

## 怎么用两份源码（方法）

1. **每次只追一条主路径**，例如「用户发一条带工具调用的消息到最终回复」——从入口跟到落盘，画一张流程图。
2. **读完立刻在自己项目写最小实现**（哪怕只有 `echo` 工具），别只做笔记。
3. WebUI 只当 **API/SSE 参考**；Agent 只当 **行为与不变量参考**。

---

## 能力清单（对照现状）

| 能力 | 状态 |
|------|------|
| DeepSeek chat（同步） | ✅ DONE |
| SSE token streaming | ✅ DONE |
| 内存会话历史（按 id CRUD） | ✅ DONE（进程内，重启丢失） |
| Vue 聊天 + markdown | ✅ DONE |
| CORS + Vite proxy | ✅ DONE |
| 启动/停止脚本 | ✅ DONE |
| 会话侧边栏 / list API | ✅ DONE |
| 持久化会话 / JSON 落盘 | ✅ DONE |
| Tools / registry | ✅ DONE（最小 registry + 2 工具） |
| ReAct / agent loop | ✅ DONE |
| 流式 tool_calls | ⚠ 部分（loop 内非流式检测；最终答案流式） |
| Memory / skills / plugins | ✅ DONE（MEMORY.md + `tiktok_drama` 插件） |
| 取消 / interrupt | ✅ DONE |
| 审批（approval） | ✅ DONE |
| 上下文压缩 | ✅ DONE |
| 抖音漫剧插件 | ✅ DONE |
| 分镜成片（配音 mp4） | ✅ DONE |
| 分镜资产 / 单镜重渲（D0） | ✅ DONE |
| 漫剧工作台 REST + 分镜台 UI（D1） | ✅ DONE |
| 分层重做 + 锁（D2） | ✅ DONE |

---

## 相关文档

- 项目 README：[`README.md`](./README.md)
- Canvas 可视化副本（Cursor）：`~/.cursor/projects/d-liangkai-myagent-my-tiktok-video/canvases/agent-learning-roadmap.canvas.tsx`
- 专业级成片计划 Canvas：`~/.cursor/projects/d-liangkai-myagent-my-tiktok-video/canvases/drama-pro-roadmap.canvas.tsx`
