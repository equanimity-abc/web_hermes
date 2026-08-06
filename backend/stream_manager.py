"""In-memory stream registry for start / reconnect / cancel / approval.

Process-local only — fine for personal single-process use. Events are buffered
so a client can reconnect with GET /api/chat/stream/{stream_id} and replay.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator


TERMINAL = frozenset({"done", "error", "cancelled"})
APPROVAL_DECISIONS = frozenset({"approved", "denied"})


@dataclass
class StreamState:
    stream_id: str
    session_id: str
    status: str = "pending"  # pending | running | done | error | cancelled
    events: list[dict[str, Any]] = field(default_factory=list)
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    waiters: list[asyncio.Event] = field(default_factory=list)
    error_message: str | None = None
    task: asyncio.Task | None = None
    created_at: float = field(default_factory=time.time)
    # Pending human approval (at most one at a time per stream)
    pending_approval_id: str | None = None
    approval_future: asyncio.Future | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL

    @property
    def is_active(self) -> bool:
        return self.status in ("pending", "running")


class StreamManager:
    def __init__(self, *, ttl_seconds: float = 600.0):
        self._streams: dict[str, StreamState] = {}
        self._session_active: dict[str, str] = {}  # session_id → stream_id
        self._ttl = ttl_seconds

    def create(self, session_id: str) -> StreamState:
        """Reserve a stream for a session. Raises BusyError if session is active."""
        self.cleanup_expired()
        existing = self._session_active.get(session_id)
        if existing:
            st = self._streams.get(existing)
            if st and st.is_active:
                raise BusyError(session_id, existing)
            self._session_active.pop(session_id, None)

        stream_id = uuid.uuid4().hex
        state = StreamState(stream_id=stream_id, session_id=session_id)
        self._streams[stream_id] = state
        self._session_active[session_id] = stream_id
        return state

    def get(self, stream_id: str) -> StreamState | None:
        return self._streams.get(stream_id)

    def active_for_session(self, session_id: str) -> StreamState | None:
        sid = self._session_active.get(session_id)
        if not sid:
            return None
        st = self._streams.get(sid)
        if st and st.is_active:
            return st
        return None

    def publish(self, stream_id: str, event: dict[str, Any]) -> None:
        state = self._streams.get(stream_id)
        if not state:
            return
        state.events.append(event)
        etype = event.get("type")
        if etype in TERMINAL:
            state.status = etype  # type: ignore[assignment]
            if etype == "error":
                state.error_message = event.get("message")
            self._session_active.pop(state.session_id, None)
            self._reject_pending_approval(state, "cancelled")
        for waiter in list(state.waiters):
            waiter.set()

    def mark_running(self, stream_id: str) -> None:
        state = self._streams.get(stream_id)
        if state and state.status == "pending":
            state.status = "running"

    def request_cancel(self, stream_id: str) -> bool:
        state = self._streams.get(stream_id)
        if not state or state.is_terminal:
            return False
        state.cancel_event.set()
        self._reject_pending_approval(state, "cancelled")
        return True

    def attach_task(self, stream_id: str, task: asyncio.Task) -> None:
        state = self._streams.get(stream_id)
        if state:
            state.task = task

    def begin_approval(self, stream_id: str, approval_id: str) -> asyncio.Future:
        """Register a pending approval Future. Replaces any prior pending one."""
        state = self._streams.get(stream_id)
        if not state:
            fut: asyncio.Future = asyncio.get_running_loop().create_future()
            fut.set_result("cancelled")
            return fut
        self._reject_pending_approval(state, "cancelled")
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        state.pending_approval_id = approval_id
        state.approval_future = fut
        return fut

    def respond_approval(
        self, stream_id: str, approval_id: str, decision: str
    ) -> dict[str, Any]:
        """Resolve a pending approval. decision must be approved|denied."""
        if decision not in APPROVAL_DECISIONS:
            raise ValueError("decision must be 'approved' or 'denied'")
        state = self._streams.get(stream_id)
        if not state:
            raise KeyError("stream not found")
        if state.is_terminal:
            return {"ok": False, "reason": "stream_finished", "status": state.status}
        if state.pending_approval_id != approval_id or state.approval_future is None:
            return {"ok": False, "reason": "no_matching_approval"}
        fut = state.approval_future
        state.pending_approval_id = None
        state.approval_future = None
        if not fut.done():
            fut.set_result(decision)
        return {"ok": True, "decision": decision, "approval_id": approval_id}

    def _reject_pending_approval(self, state: StreamState, decision: str) -> None:
        fut = state.approval_future
        state.pending_approval_id = None
        state.approval_future = None
        if fut is not None and not fut.done():
            fut.set_result(decision)

    async def await_approval(
        self,
        stream_id: str,
        approval_id: str,
        *,
        cancel_event: asyncio.Event | None = None,
    ) -> str:
        """Await a Future previously created by begin_approval."""
        state = self._streams.get(stream_id)
        if not state or state.pending_approval_id != approval_id:
            return "cancelled"
        fut = state.approval_future
        if fut is None:
            return "cancelled"

        cancel_wait: asyncio.Task | None = None
        try:
            if cancel_event is not None:
                cancel_wait = asyncio.create_task(cancel_event.wait())
                done, pending = await asyncio.wait(
                    {fut, cancel_wait},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
                if cancel_event.is_set():
                    if not fut.done():
                        fut.set_result("cancelled")
                    state.pending_approval_id = None
                    state.approval_future = None
                    return "cancelled"
            result = await fut
            return result
        finally:
            if cancel_wait is not None and not cancel_wait.done():
                cancel_wait.cancel()

    async def iter_events(
        self, stream_id: str, *, from_index: int = 0
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield buffered then live events until a terminal event is seen."""
        state = self._streams.get(stream_id)
        if not state:
            yield {"type": "error", "message": "stream not found"}
            return

        index = from_index
        while True:
            while index < len(state.events):
                event = state.events[index]
                index += 1
                yield event
                if event.get("type") in TERMINAL:
                    return

            if state.is_terminal:
                return

            waiter = asyncio.Event()
            state.waiters.append(waiter)
            try:
                await waiter.wait()
            finally:
                if waiter in state.waiters:
                    state.waiters.remove(waiter)

    def cleanup_expired(self) -> None:
        now = time.time()
        dead = [
            sid
            for sid, st in self._streams.items()
            if st.is_terminal and (now - st.created_at) > self._ttl
        ]
        for sid in dead:
            st = self._streams.pop(sid, None)
            if st and self._session_active.get(st.session_id) == sid:
                self._session_active.pop(st.session_id, None)


class BusyError(Exception):
    def __init__(self, session_id: str, stream_id: str):
        self.session_id = session_id
        self.stream_id = stream_id
        super().__init__(f"session {session_id} is busy on stream {stream_id}")


streams = StreamManager()
