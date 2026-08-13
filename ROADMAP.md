# 自研 Agent：源码消化 + 增量开发路线

对照 `hermes-agent` / `hermes-webui`，在现有 Vue3 + FastAPI 脚手架上逐步长出真 Agent。

**原则：** 学不变量与骨架，重写精简核心，不 fork 巨石。

---

## 你现在的真实位置

当前是可用的 DeepSeek 聊天应用（SSE + 内存会话）。UI 上的「Agent 模式」文案是展示层；**尚未有工具循环、registry、持久化会话列表**。

下一刀应先修 **会话耐久化（P1）**，再啃 **Agent Loop（P2）**。

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

P0–P7 骨架已齐。之后按痛点加能力即可：业务工具继续丢进 `backend/tools/plugins/`，不要改 `agent/loop.py`。

P7 已完成：插件 `tiktok_drama`（guide / init / list / get / save_bible / save_outline / save_episode），项目落在 `workspace/dramas/{slug}/`；system prompt 动态列出工具 + 插件 hint。

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

---

## 相关文档

- 项目 README：[`README.md`](./README.md)
- Canvas 可视化副本（Cursor）：`~/.cursor/projects/d-liangkai-myagent-my-tiktok-video/canvases/agent-learning-roadmap.canvas.tsx`
