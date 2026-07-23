"""FastAPI 主应用 - 聊天 API 服务"""

import uuid
import json
from typing import AsyncGenerator
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from config import config
from llm_client import llm_client

app = FastAPI(title="Agent Chat API", version="0.1.0")

# CORS 配置（允许前端跨域）
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# 简单的内存会话管理（后续可替换为数据库）
# ============================================================
sessions: dict[str, list[dict]] = {}

SYSTEM_PROMPT = "你是一个乐于助人的AI助手，可以用中文回答问题。"


def get_or_create_session(session_id: str | None) -> tuple[str, list[dict]]:
    """获取或创建会话"""
    if session_id and session_id in sessions:
        return session_id, sessions[session_id]
    new_id = session_id or str(uuid.uuid4())
    sessions[new_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    return new_id, sessions[new_id]


# ============================================================
# 请求模型
# ============================================================
class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str


class ChatResponse(BaseModel):
    session_id: str
    content: str


# ============================================================
# API 路由
# ============================================================

@app.get("/api/health")
async def health():
    """健康检查"""
    return {"status": "ok"}


@app.post("/api/chat")
async def chat(req: ChatRequest) -> ChatResponse:
    """非流式聊天（一次性返回）"""
    session_id, history = get_or_create_session(req.session_id)

    # 添加用户消息
    history.append({"role": "user", "content": req.message})

    try:
        # 调用 LLM
        content = await llm_client.chat(history)
        # 保存助手回复
        history.append({"role": "assistant", "content": content})
        return ChatResponse(session_id=session_id, content=content)
    except Exception as e:
        # 移除失败的用户消息
        history.pop()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """流式聊天（SSE 实时推送）"""
    session_id, history = get_or_create_session(req.session_id)

    # 添加用户消息
    history.append({"role": "user", "content": req.message})

    async def event_generator() -> AsyncGenerator[dict, None]:
        full_content = ""
        try:
            async for token in llm_client.chat_stream(history):
                full_content += token
                yield {"data": token}
            # 保存完整回复
            history.append({"role": "assistant", "content": full_content})
            # 发送结束信号，附带 session_id
            yield {"event": "done", "data": json.dumps({"session_id": session_id})}
        except Exception as e:
            history.pop()  # 移除失败的用户消息
            yield {"event": "error", "data": str(e)}

    return EventSourceResponse(event_generator())


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """获取会话历史"""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id, "messages": sessions[session_id]}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除会话"""
    if session_id in sessions:
        del sessions[session_id]
    return {"status": "deleted"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=True)