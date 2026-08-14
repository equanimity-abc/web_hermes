# 🧠 Agent Chat - 通用智能体框架

基于 DeepSeek + FastAPI + Vue 3 的通用智能体框架，支持 ReAct 模式工具调用。

## 项目结构

```
├── backend/            # Python FastAPI 后端
│   ├── config.py       # 配置管理
│   ├── llm_client.py   # DeepSeek API 封装（可插拔）
│   ├── main.py         # FastAPI 主应用
│   └── requirements.txt
│
├── frontend/           # Vue 3 前端
│   ├── src/
│   │   ├── App.vue              # 应用壳（组装布局）
│   │   ├── api/                 # HTTP / SSE
│   │   ├── composables/         # 会话 / 聊天 / 侧栏等逻辑
│   │   ├── components/          # layout + chat 组件
│   │   ├── styles/              # 全局样式
│   │   ├── utils/               # markdown / clipboard
│   │   └── main.js
│   └── package.json
│
└── README.md
```

## 快速开始

### 1. 配置 API Key

```bash
cd backend
copy .env.example .env
```

编辑 `backend/.env`，填入你的 DeepSeek API Key：
```
DEEPSEEK_API_KEY=sk-your-actual-api-key
```

### 2. 启动后端

```bash
cd backend
pip install -r requirements.txt
python main.py
```

后端运行在 http://localhost:8000

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev
```

前端运行在 http://localhost:5173

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| POST | `/api/chat` | 非流式聊天 |
| POST | `/api/chat/start` | 开始一轮生成，返回 `stream_id` |
| GET | `/api/chat/stream/{stream_id}` | SSE 订阅/重连（`token`/`tool`/`done`/`error`/`cancelled`） |
| POST | `/api/chat/cancel` | 取消生成（终端事件为 `cancelled`，不是 `done`） |
| POST | `/api/chat/approval/respond` | 批准/拒绝危险工具（`approved` / `denied`） |
| POST | `/api/chat/stream` | 兼容旧客户端的一次性 POST SSE |
| GET | `/api/workspace` | workspace 根目录信息 |
| GET | `/api/workspace/file` | 预览/下载沙箱内文件（mp4 等） |
| POST | `/api/workspace/upload` | 上传附件到 workspace 沙箱 |
| GET | `/api/memory` | 读取跨会话长期记忆 |
| PUT | `/api/memory` | 写入长期记忆（`append` / `replace`） |
| GET | `/api/sessions` | 会话列表（摘要） |
| GET | `/api/sessions/{id}` | 获取会话历史 |
| DELETE | `/api/sessions/{id}` | 删除会话 |

会话落盘目录：`backend/data/sessions/{id}.json`（重启后仍可恢复）。
工作区目录：`backend/data/workspace/`（工具与上传均限制在此沙箱内）。
记忆文件：`backend/data/memory/MEMORY.md`（跨会话；新会话 system 会注入，每轮会刷新）。
漫剧项目：`backend/data/workspace/dramas/{slug}/`（插件 `tiktok_drama` 写入，不改 agent loop）。
成片视频：`backend/data/workspace/dramas/{slug}/videos/epNN.mp4`（按分镜出画面 + 运镜 + 配音；聊天里可通过 `/api/workspace/file` 预览）。

## 开发路线

完整计划见根目录 [`ROADMAP.md`](./ROADMAP.md)（源码消化顺序 + P0–P7 增量开发 + 学习单元）。

- [x] Phase 1 / P0: 聊天界面（DeepSeek + Vue 3）
- [x] P1: 会话耐久化（列表 API + JSON 落盘 + 侧边栏）
- [x] P2: Agent Loop（calculator / get_current_time）
- [x] P3: 工具系统（workspace 文件工具 + ToolCard + 插件目录）
- [x] P4: 流式契约升级（`stream_id` / 取消 / busy）
- [x] P5: 审批与工作区加固（approval + upload + 路径沙箱）
- [x] P6: 记忆与压缩（MEMORY.md + 上下文摘要）
- [x] P7: 抖音漫剧插件（`tiktok_drama`，不改 agent loop）
- [x] P8: 分镜成片（`render_episode` → 竖屏配音 mp4）