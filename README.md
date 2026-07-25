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
| POST | `/api/chat/stream` | 流式聊天（SSE） |
| GET | `/api/sessions/{id}` | 获取会话历史 |
| DELETE | `/api/sessions/{id}` | 删除会话 |

## 开发路线

完整计划见根目录 [`ROADMAP.md`](./ROADMAP.md)（源码消化顺序 + P0–P7 增量开发 + 学习单元）。

- [x] Phase 1 / P0: 聊天界面（DeepSeek + Vue 3）
- [ ] P1: 会话耐久化（列表 API + 落盘 + 侧边栏）
- [ ] P2–P3: Agent Loop + 工具系统
- [ ] P4–P5: 流式契约升级 + 审批/工作区
- [ ] P6–P7: 记忆压缩 + 抖音漫剧等业务插件