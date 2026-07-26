"""FastAPI 主应用 - 聊天 API 服务"""

from __future__ import annotations

import json
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from config import config
from llm_client import llm_client
from session_store import SessionStore

app = FastAPI(title="Agent Chat API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

store = SessionStore(config.SESSION_DATA_DIR)


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
    return {"status": "ok"}


@app.get("/api/sessions")
async def list_sessions():
    """列出全部会话摘要（侧边栏用）"""
    return {"sessions": store.list_summaries()}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "session_id": session["id"],
        "title": session.get("title"),
        "created_at": session.get("created_at"),
        "updated_at": session.get("updated_at"),
        "messages": session.get("messages") or [],
    }


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    store.delete(session_id)
    return {"status": "deleted"}


@app.post("/api/chat")
async def chat(req: ChatRequest) -> ChatResponse:
    """非流式聊天（一次性返回）"""
    session = store.get_or_create(req.session_id)
    session_id = session["id"]
    messages = session["messages"]

    messages.append({"role": "user", "content": req.message})
    store.save(session)

    try:
        content = await llm_client.chat(messages)
        messages.append({"role": "assistant", "content": content})
        store.save(session)
        return ChatResponse(session_id=session_id, content=content)
    except Exception as e:
        messages.pop()
        store.save(session)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """流式聊天（SSE 实时推送）"""
    session = store.get_or_create(req.session_id)
    session_id = session["id"]
    messages = session["messages"]

    messages.append({"role": "user", "content": req.message})
    store.save(session)

    async def event_generator() -> AsyncGenerator[dict, None]:
        full_content = ""
        try:
            # 尽早把 session_id 交给前端（新建会话时侧边栏可刷新）
            yield {"data": json.dumps({"session_id": session_id})}

            async for token in llm_client.chat_stream(messages):
                full_content += token
                yield {"data": token}

            messages.append({"role": "assistant", "content": full_content})
            store.save(session)
            yield {"event": "done", "data": json.dumps({"session_id": session_id})}
        except Exception as e:
            if messages and messages[-1].get("role") == "user":
                messages.pop()
                store.save(session)
            yield {"event": "error", "data": str(e)}

    return EventSourceResponse(event_generator())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=True)
