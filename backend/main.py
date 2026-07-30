"""FastAPI 主应用 - 聊天 API 服务"""

from __future__ import annotations

import json
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from agent import agent, messages_for_api
from config import config
from session_store import SessionStore

app = FastAPI(title="Agent Chat API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

store = SessionStore(config.SESSION_DATA_DIR)


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str


class ChatResponse(BaseModel):
    session_id: str
    content: str


@app.get("/api/health")
async def health():
    return {"status": "ok", "agent": True}


@app.get("/api/sessions")
async def list_sessions():
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
    """非流式：走完整 Agent loop（可含工具）。"""
    session = store.get_or_create(req.session_id)
    session_id = session["id"]
    messages = session["messages"]

    messages.append({"role": "user", "content": req.message})
    store.save(session)

    # Work on a copy for the API; merge back after success
    working = messages_for_api(messages)
    pre_len = len(working)

    try:
        content = await agent.run(working, use_tools=True)
        # Append only new messages produced by the agent
        messages.extend(working[pre_len:])
        store.save(session)
        return ChatResponse(session_id=session_id, content=content)
    except Exception as e:
        if messages and messages[-1].get("role") == "user":
            messages.pop()
            store.save(session)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """流式：Agent loop；工具轮次发 status/tool JSON，最终答案发 token。"""
    session = store.get_or_create(req.session_id)
    session_id = session["id"]
    messages = session["messages"]

    messages.append({"role": "user", "content": req.message})
    store.save(session)

    working = messages_for_api(messages)
    pre_len = len(working)

    async def event_generator() -> AsyncGenerator[dict, None]:
        try:
            yield {"data": json.dumps({"session_id": session_id})}

            async for event in agent.run_stream(working, use_tools=True):
                etype = event.get("type")
                if etype == "token":
                    # Plain text keeps compatibility with existing frontend
                    yield {"data": event.get("text") or ""}
                elif etype == "error":
                    if len(working) > pre_len:
                        messages.extend(working[pre_len:])
                        store.save(session)
                    elif messages and messages[-1].get("role") == "user":
                        messages.pop()
                        store.save(session)
                    yield {
                        "event": "error",
                        "data": event.get("message") or "unknown error",
                    }
                    return
                else:
                    # status / tool / tool_result — structured JSON for UI
                    yield {"data": json.dumps(event, ensure_ascii=False)}

            messages.extend(working[pre_len:])
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
