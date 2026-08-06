"""会话持久化：每会话一个 JSON 文件（对齐 hermes-webui 的简洁模型）。"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SAFE_ID = re.compile(r"^[a-zA-Z0-9_-]{8,64}$")

SYSTEM_PROMPT = (
    "你是一个有用的 AI Agent。你可以调用工具完成任务："
    "calculator、get_current_time、list_dir、read_file、write_file、delete_file。"
    "文件工具只能访问 workspace 沙箱内的相对路径；write_file / delete_file 需要用户审批后才会执行。"
    "用中文简洁回答。"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _title_from_messages(messages: list[dict]) -> str:
    for msg in messages:
        if msg.get("role") == "user":
            text = str(msg.get("content") or "").strip().replace("\n", " ")
            if not text:
                continue
            return text[:40] + ("…" if len(text) > 40 else "")
    return "新对话"


def _is_safe_id(session_id: str) -> bool:
    return bool(_SAFE_ID.match(session_id))


class SessionStore:
    """磁盘会话仓库，带进程内缓存。"""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, dict[str, Any]] = {}

    def _path(self, session_id: str) -> Path:
        if not _is_safe_id(session_id):
            raise ValueError(f"非法 session_id: {session_id}")
        return self.root / f"{session_id}.json"

    def _create(self, session_id: str | None = None) -> dict[str, Any]:
        sid = session_id or str(uuid.uuid4())
        if not _is_safe_id(sid):
            raise ValueError(f"非法 session_id: {sid}")
        now = _utc_now()
        session = {
            "id": sid,
            "title": "新对话",
            "created_at": now,
            "updated_at": now,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}],
        }
        self.save(session)
        return session

    def save(self, session: dict[str, Any]) -> None:
        sid = session["id"]
        session["title"] = _title_from_messages(session.get("messages") or [])
        session["updated_at"] = _utc_now()
        path = self._path(sid)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        self._cache[sid] = session

    def get(self, session_id: str) -> dict[str, Any] | None:
        if session_id in self._cache:
            return self._cache[session_id]
        if not _is_safe_id(session_id):
            return None
        path = self._path(session_id)
        if not path.exists():
            return None
        try:
            session = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        self._cache[session_id] = session
        return session

    def get_or_create(self, session_id: str | None) -> dict[str, Any]:
        if session_id:
            existing = self.get(session_id)
            if existing:
                return existing
            if _is_safe_id(session_id):
                return self._create(session_id)
        return self._create()

    def delete(self, session_id: str) -> bool:
        self._cache.pop(session_id, None)
        if not _is_safe_id(session_id):
            return False
        path = self._path(session_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def list_summaries(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for path in self.root.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            sid = data.get("id") or path.stem
            items.append(
                {
                    "id": sid,
                    "title": data.get("title") or "新对话",
                    "created_at": data.get("created_at"),
                    "updated_at": data.get("updated_at"),
                }
            )
        items.sort(key=lambda s: s.get("updated_at") or "", reverse=True)
        return items
