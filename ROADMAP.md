# 自研 Agent：源码消化 + 增量开发路线

对照 `hermes-agent` / `hermes-webui`，在现有 Vue3 + FastAPI 脚手架上逐步长出真 Agent。

**原则：** 学不变量与骨架，重写精简核心，不 fork 巨石。

---

## 你现在的真实位置

**通用腰（P0–P6）已齐：** 会话耐久化、Agent loop、工具 registry、SSE、审批、工作区沙箱、记忆与压缩。

**漫剧草稿成片（P7–P8 + D0–D4）已齐：** 插件 `tiktok_drama` 能立项 / 写 bible·角色卡·大纲·分集；`shots.json` 单镜重渲；工作台可改对白/运镜；锁住画面后改台词只换声和字幕；剧本页改结局时已锁整镜不动；同一角色连续镜头共用外形 prompt 与音色，参考图可锁。

**下一刀：D5 候选墙。** D4 已能按角色卡出图/配音，锁定妆图后不会被覆盖。完整计划见下文 **漫剧智能体制作流水线（D0–D8）**。

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
| **D5–D8** | 候选 / 时间线 / 队列 / I2V | 见专章 | 导演式干预到镜头层 | 见下文 D0–D8 | 计划中 |

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

P0–P8 + D0–D4 已齐。业务继续放插件与 `/api/drama/*`，**不要改 `agent/loop.py`**。

下一刀 **D5**：每镜出 2–4 张候选，点选锁定，可手传覆盖。验收：不喜欢就换图，不重配音。

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
| 候选墙 | 一镜多图，点选锁定 | D5 |
| 时间线 | 镜序、转场、音量条、整集预览 | D6 |
| 任务条 | 渲染队列、失败重试、取消 | D7 |

检查器目标：**保存 / 仅重做这一层 / 解锁 / 回滚版本**。D1 已有保存 + 重渲本镜；D2 已有锁与分层重做；D3 已有锁定整镜与剧本影响提示；D4 已有角色勾选与音色绑定。回滚版本仍待做。

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

Skills 建议目录（尚未落地）：

```text
skills/
  drama-vertical-short/SKILL.md
  drama-character-bible/SKILL.md
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
| **D5** | 每镜出 2–4 张候选，点选锁定，可手传覆盖 | 不喜欢就换图，不重配音 | 计划 |
| **D6** | 镜序拖拽、转场、切点、音量；导出不毁源 clip | 只把 Shot 4 缩短 0.4s 并换转场，立刻出新 mp4 | 计划 |
| **D7** | 后台渲染、可取消、失败重试、工作台进度条 | 渲 8 镜时聊天仍可用 | 计划 |
| **D8** | I2V、口型、BGM（有工作台之后再做） | 对已锁关键帧做 2–3 秒运动，失败回退静图运镜 | 计划 |

**D5 之前不要上 I2V。** D0–D4 已齐。

### 拍板的三件事

1. **先 D0+D1**（资产化 + 分镜台），不要先接视频模型。 ← 已做完  
2. **剧情改在剧本页，画面/声改在分镜台**，Agent 只处理「重写/重抽」按钮。  
3. **核心 loop 继续冻结**；新能力进 `tiktok_drama` action + `/api/drama/*`。

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
