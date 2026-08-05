"""FastAPI 主应用 - 聊天 API 服务"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from agent import agent, messages_for_api
from config import config
from session_store import SessionStore
from stream_manager import BusyError, streams

app = FastAPI(title="Agent Chat API", version="0.3.0")

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


class CancelRequest(BaseModel):
    stream_id: str


class StartResponse(BaseModel):
    stream_id: str
    session_id: str


def _sse(event: dict[str, Any]) -> dict[str, str]:
    """Unified SSE frame: event name = type, data = JSON body."""
    etype = str(event.get("type") or "message")
    return {"event": etype, "data": json.dumps(event, ensure_ascii=False)}


def _persist_partial(
    session: dict[str, Any],
    messages: list[dict[str, Any]],
    working: list[dict[str, Any]],
    pre_len: int,
    *,
    drop_user_on_empty: bool,
) -> None:
    """Merge agent-produced messages; optionally roll back lonely user turn."""
    produced = working[pre_len:]
    if produced:
        messages.extend(produced)
        store.save(session)
        return
    if drop_user_on_empty and messages and messages[-1].get("role") == "user":
        messages.pop()
        store.save(session)


async def _run_stream_job(
    stream_id: str,
    session_id: str,
    working: list[dict[str, Any]],
    pre_len: int,
) -> None:
    """Background agent run; publishes events to StreamManager."""
    state = streams.get(stream_id)
    if not state:
        return
    streams.mark_running(stream_id)
    session = store.get(session_id)
    if not session:
        streams.publish(
            stream_id, {"type": "error", "message": "session disappeared"}
        )
        return
    messages = session["messages"]

    try:
        async for event in agent.run_stream(
            working,
            use_tools=True,
            cancel_event=state.cancel_event,
        ):
            etype = event.get("type")
            if etype == "error":
                _persist_partial(
                    session,
                    messages,
                    working,
                    pre_len,
                    drop_user_on_empty=True,
                )
                streams.publish(stream_id, event)
                return
            if etype == "cancelled":
                # Keep completed tool turns / partial answer; never claim done.
                _persist_partial(
                    session,
                    messages,
                    working,
                    pre_len,
                    drop_user_on_empty=False,
                )
                streams.publish(
                    stream_id,
                    {
                        "type": "cancelled",
                        "session_id": session_id,
                        "stream_id": stream_id,
                    },
                )
                return
            streams.publish(stream_id, event)

        messages.extend(working[pre_len:])
        store.save(session)
        streams.publish(
            stream_id,
            {
                "type": "done",
                "session_id": session_id,
                "stream_id": stream_id,
            },
        )
    except Exception as e:
        _persist_partial(
            session, messages, working, pre_len, drop_user_on_empty=True
        )
        streams.publish(stream_id, {"type": "error", "message": str(e)})


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
    if streams.active_for_session(session_id):
        raise HTTPException(
            status_code=409,
            detail={"error": "session_busy", "session_id": session_id},
        )

    messages = session["messages"]
    messages.append({"role": "user", "content": req.message})
    store.save(session)

    working = messages_for_api(messages)
    pre_len = len(working)

    try:
        content = await agent.run(working, use_tools=True)
        messages.extend(working[pre_len:])
        store.save(session)
        return ChatResponse(session_id=session_id, content=content)
    except Exception as e:
        if messages and messages[-1].get("role") == "user":
            messages.pop()
            store.save(session)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/chat/start", response_model=StartResponse)
async def chat_start(req: ChatRequest) -> StartResponse:
    """Start a turn; returns stream_id. Client then opens GET .../stream/{id}."""
    if not (req.message or "").strip():
        raise HTTPException(status_code=400, detail="message is required")

    session = store.get_or_create(req.session_id)
    session_id = session["id"]

    try:
        state = streams.create(session_id)
    except BusyError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "session_busy",
                "session_id": e.session_id,
                "stream_id": e.stream_id,
            },
        ) from e

    messages = session["messages"]
    messages.append({"role": "user", "content": req.message})
    store.save(session)

    working = messages_for_api(messages)
    pre_len = len(working)

    streams.publish(
        state.stream_id,
        {
            "type": "meta",
            "session_id": session_id,
            "stream_id": state.stream_id,
        },
    )

    task = asyncio.create_task(
        _run_stream_job(state.stream_id, session_id, working, pre_len)
    )
    streams.attach_task(state.stream_id, task)

    return StartResponse(stream_id=state.stream_id, session_id=session_id)


@app.get("/api/chat/stream/{stream_id}")
async def chat_stream_reconnect(stream_id: str):
    """SSE: replay buffer then live events until done/error/cancelled."""
    state = streams.get(stream_id)
    if not state:
        raise HTTPException(status_code=404, detail="stream not found")

    async def event_generator() -> AsyncGenerator[dict, None]:
        async for event in streams.iter_events(stream_id):
            yield _sse(event)

    return EventSourceResponse(event_generator())


@app.post("/api/chat/cancel")
async def chat_cancel(req: CancelRequest):
    """Request cancel; terminal event is `cancelled`, never `done`."""
    state = streams.get(req.stream_id)
    if not state:
        raise HTTPException(status_code=404, detail="stream not found")
    if state.is_terminal:
        return {
            "status": state.status,
            "stream_id": req.stream_id,
            "already_finished": True,
        }
    ok = streams.request_cancel(req.stream_id)
    return {
        "status": "cancelling" if ok else state.status,
        "stream_id": req.stream_id,
        "already_finished": False,
    }


@app.post("/api/chat/stream")
async def chat_stream_legacy(req: ChatRequest):
    """Legacy one-shot POST SSE — wraps start + reconnect for older clients."""
    started = await chat_start(req)
    return await chat_stream_reconnect(started.stream_id)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=True)
