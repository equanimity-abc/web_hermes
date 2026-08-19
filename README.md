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
| GET | `/api/drama/projects` | 漫剧项目列表 |
| GET | `/api/drama/projects/{slug}` | 项目详情（分集、bible、outline） |
| PATCH | `/api/drama/projects/{slug}` | 改标题 / logline |
| GET | `/api/drama/projects/{slug}/episodes/{n}` | 分集 + 分镜 + 预览 URL |
| PATCH | `/api/drama/projects/{slug}/episodes/{n}` | 改分集标题 / 时长 |
| PATCH | `/api/drama/projects/{slug}/episodes/{n}/shots/{shot}` | 改对白 / 画面 / 字幕 / 角色 / 运镜 / 时长；`lock` / `unlock` / `locked` 锁层 |
| POST | `/api/drama/projects/{slug}/episodes/{n}/script/preview` | 预览剧本改动影响哪些 Shot（不落盘） |
| PUT | `/api/drama/projects/{slug}/episodes/{n}/script` | 保存剧本并同步 `shots.json`；已锁整镜不覆盖 |
| POST | `/api/drama/projects/{slug}/episodes/{n}/rerender-dirty` | 后台重渲脏镜（返回 job_id） |
| POST | `/api/drama/projects/{slug}/episodes/{n}/shots/{shot}/candidates` | 重抽 2–4 张候选图 |
| POST | `/api/drama/projects/{slug}/episodes/{n}/shots/{shot}/choose/{cid}` | 点选候选锁定画面（只重拼 clip，不重配音） |
| POST | `/api/drama/projects/{slug}/episodes/{n}/shots/{shot}/scene` | 手传覆盖本镜画面 |
| POST | `/api/drama/projects/{slug}/episodes/{n}/shots/{shot}/i2v` | 生成 I2V 运动（L0 定场拒绝） |
| POST | `/api/drama/projects/{slug}/episodes/{n}/shots/{shot}/lip` | 生成口型（仅 dialogue CU/MCU，须有 speaker） |
| GET | `/api/drama/projects/{slug}/episodes/{n}/timeline` | 时间线镜序与各镜切点/转场/音量 |
| PATCH | `/api/drama/projects/{slug}/episodes/{n}/timeline` | 保存镜序或批量改时间线 |
| POST | `/api/drama/projects/{slug}/episodes/{n}/export` | 按时间线导出整集（默认后台队列） |
| POST | `/api/drama/projects/{slug}/episodes/{n}/jobs` | 提交后台任务（rerender_dirty / export / …） |
| GET | `/api/drama/jobs` | 列出渲染任务 |
| GET | `/api/drama/jobs/{id}` | 查询任务进度 |
| POST | `/api/drama/jobs/{id}/cancel` | 取消任务 |
| POST | `/api/drama/jobs/{id}/retry` | 重试失败任务 |
| GET | `/api/drama/projects/{slug}/characters` | 角色卡列表 + 可选音色 |
| POST | `/api/drama/projects/{slug}/characters` | 新建角色卡 |
| PUT | `/api/drama/projects/{slug}/characters/{id}` | 更新外形 / 音色 / 别名 |
| DELETE | `/api/drama/projects/{slug}/characters/{id}` | 删除角色卡（参考图已锁时拒绝） |
| POST | `/api/drama/projects/{slug}/characters/{id}/ref` | 上传定妆参考图 |
| POST | `/api/drama/projects/{slug}/characters/{id}/lock-ref` | 锁定/解锁参考图 |

会话落盘目录：`backend/data/sessions/{id}.json`（重启后仍可恢复）。
工作区目录：`backend/data/workspace/`（工具与上传均限制在此沙箱内）。
记忆文件：`backend/data/memory/MEMORY.md`（跨会话；新会话 system 会注入，每轮会刷新）。
漫剧项目：`backend/data/workspace/dramas/{slug}/`（插件 `tiktok_drama` 写入，不改 agent loop）。
成片视频：`backend/data/workspace/dramas/{slug}/videos/epNN.mp4`（分镜静图 + 运镜/转场/调色 + 配音；聊天里可通过 `/api/workspace/file` 预览）。
分镜资产：`videos/epNN/shots.json` + `shotNN.mp4`（改一镜用 `rerender_shot`，其它镜不重渲）。
工作台：前端侧栏切到「漫剧」，REST `/api/drama/*` 直接改分镜（对白 / 运镜 / 时长 / 角色）或剧本，不走 Agent loop。锁住 `scene` 后改台词只重配音和字幕；锁住整镜后改剧本不会覆盖该镜。角色卡的外形进入出图 prompt，音色绑定配音，参考图可锁。分镜页候选墙可重抽 4 张、点选换图或手传覆盖，只换画面不重配音。时间线页可拖拽镜序、裁切头尾、选转场、调音量，点导出立刻出新 epNN.mp4，各镜 shotNN.mp4 不会被覆盖。重渲脏镜/整集导出默认进后台队列，底部任务条显示进度，可取消或重试，聊天不被阻塞。

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
- [x] D0: 分镜资产化（`shots.json` + `rerender_shot` 单镜重渲）
- [x] D1: 漫剧工作台（分镜台 UI + `/api/drama` REST，不靠聊天改镜）
- [x] D2: 分层重做 + 锁（锁画面后改台词只换声/字幕）
- [x] D3: 剧情干预（剧本编辑器 + 脏镜提示；已锁整镜不覆盖）
- [x] D4: 角色一致性（角色卡 + 参考图进 prompt + 每镜选角色 + 音色绑定）
- [x] D5: 候选墙（每镜 2–4 候选 + 点选锁定 + 手传覆盖；换图不重配音）
- [x] D6: 时间线（镜序拖拽 + 切点/转场/音量 + 导出不毁源 clip）
- [x] D7: 任务条（后台渲染队列 + 进度/取消/重试；渲 8 镜时聊天仍可用）
- [x] D8: I2V 运动（对已锁关键帧试 2–3s 运动；失败回退静图 zoompan；工作台可选 off/auto/on）
- [x] Q0: 镜头分类 + 模型路由（kind/size/speaker、models.json 调研卡、L0/L1、I2V 估费）
- [x] Q1: 音频分轨 + 版权（BGM 只在 assemble/export 混入；无 license 拒绝导出；换曲 clip 哈希不变）
- [x] Q2: 口型（仅 dialogue CU/MCU + speaker；mock/http + 失败回退；LSE 代理分数）
- [x] Q3: 运动档 L0–L3（定场禁止 I2V；action 规划 L3；贵模型不可用走 mock；每集最多 2 镜贵 I2V）
- [x] Q4: identity 抽检（锁参考图/连续镜余弦；低于 0.65 脏 scene/motion 不重配音；skipped 不得记为通过）
- [x] Q5: 导演覆盖建议（钩子 3s / 景别节奏 / 最多 2 条 reaction；只建议不改镜；人可忽略可锁）
- [ ] Q6–Q8: 稀疏关键帧 / QC 验收页 / 风格包（见 ROADMAP）