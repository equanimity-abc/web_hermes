"""Workspace path sandbox + file tools.

All relative paths must resolve under WORKSPACE_DIR. Absolute paths, escapes,
null bytes, and symlink escapes are rejected (fail closed).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from config import config
from tools.registry import register

_MAX_READ_CHARS = 80_000
_MAX_WRITE_CHARS = 200_000
_MAX_LIST = 500
_MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MiB

# Reject control chars / null; Windows drive-like prefixes in "relative" inputs
_UNSAFE_REL = re.compile(r"[\x00-\x1f]|^[a-zA-Z]:[/\\]|^\\\\")


def workspace_root() -> Path:
    root = Path(config.WORKSPACE_DIR).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def resolve_safe(rel_path: str) -> Path:
    """Resolve a user path strictly inside workspace. Raises ValueError on escape."""
    root = workspace_root()
    raw = (rel_path or ".").strip() or "."
    if _UNSAFE_REL.search(raw):
        raise ValueError("非法路径字符或绝对路径")
    candidate = Path(raw)
    if candidate.is_absolute():
        raise ValueError("禁止使用绝对路径，请使用相对 workspace 的路径")
    # Normalize ".." before resolve so we fail early on obvious escapes
    parts = []
    for part in candidate.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                raise ValueError("路径越出 workspace 沙箱")
            parts.pop()
            continue
        parts.append(part)
    target = (root.joinpath(*parts) if parts else root).resolve()
    try:
        target.relative_to(root)
    except ValueError as e:
        raise ValueError("路径越出 workspace 沙箱") from e
    return target


def save_upload(filename: str, data: bytes, *, subdir: str = "") -> dict:
    """Write uploaded bytes into workspace. Returns metadata dict or raises."""
    if not filename or not str(filename).strip():
        raise ValueError("文件名不能为空")
    name = Path(str(filename)).name  # drop any client-supplied directories
    if not name or name in (".", ".."):
        raise ValueError("非法文件名")
    if len(data) > _MAX_UPLOAD_BYTES:
        raise ValueError(f"文件过大（>{_MAX_UPLOAD_BYTES} 字节）")

    rel_dir = (subdir or "").strip().strip("/\\")
    rel = f"{rel_dir}/{name}" if rel_dir else name
    target = resolve_safe(rel)
    if target.exists() and target.is_dir():
        raise ValueError("目标是目录，无法写入文件")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return {
        "ok": True,
        "path": rel.replace("\\", "/"),
        "bytes": len(data),
        "workspace": str(workspace_root()),
    }


def _list_dir(args: dict) -> str:
    rel = str(args.get("path") or ".")
    try:
        target = resolve_safe(rel)
        if not target.exists():
            return json.dumps({"error": "路径不存在", "path": rel}, ensure_ascii=False)
        if not target.is_dir():
            return json.dumps({"error": "不是目录", "path": rel}, ensure_ascii=False)

        entries = []
        for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if len(entries) >= _MAX_LIST:
                break
            entries.append(
                {
                    "name": child.name,
                    "type": "dir" if child.is_dir() else "file",
                    "size": None if child.is_dir() else child.stat().st_size,
                }
            )
        return json.dumps(
            {
                "path": rel,
                "workspace": str(workspace_root()),
                "count": len(entries),
                "entries": entries,
            },
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps({"error": str(e), "path": rel}, ensure_ascii=False)


def _read_file(args: dict) -> str:
    rel = str(args.get("path") or "")
    try:
        target = resolve_safe(rel)
        if not target.exists():
            return json.dumps({"error": "文件不存在", "path": rel}, ensure_ascii=False)
        if not target.is_file():
            return json.dumps({"error": "不是文件", "path": rel}, ensure_ascii=False)
        text = target.read_text(encoding="utf-8", errors="replace")
        truncated = len(text) > _MAX_READ_CHARS
        if truncated:
            text = text[:_MAX_READ_CHARS]
        return json.dumps(
            {
                "path": rel,
                "truncated": truncated,
                "chars": len(text),
                "content": text,
            },
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps({"error": str(e), "path": rel}, ensure_ascii=False)


def _write_file(args: dict) -> str:
    rel = str(args.get("path") or "")
    content = args.get("content")
    if content is None:
        return json.dumps({"error": "content 不能为空"}, ensure_ascii=False)
    content = str(content)
    if len(content) > _MAX_WRITE_CHARS:
        return json.dumps(
            {"error": f"content 过长（>{_MAX_WRITE_CHARS} 字符）"},
            ensure_ascii=False,
        )
    try:
        target = resolve_safe(rel)
        if target.exists() and target.is_dir():
            return json.dumps({"error": "目标是目录，无法写入", "path": rel}, ensure_ascii=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return json.dumps(
            {"ok": True, "path": rel, "chars": len(content)},
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps({"error": str(e), "path": rel}, ensure_ascii=False)


def _delete_file(args: dict) -> str:
    rel = str(args.get("path") or "")
    try:
        target = resolve_safe(rel)
        if not target.exists():
            return json.dumps({"error": "路径不存在", "path": rel}, ensure_ascii=False)
        if target.is_dir():
            return json.dumps(
                {"error": "拒绝删除目录（仅允许删除文件）", "path": rel},
                ensure_ascii=False,
            )
        target.unlink()
        return json.dumps({"ok": True, "path": rel, "deleted": True}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e), "path": rel}, ensure_ascii=False)


def register_workspace_tools() -> None:
    register(
        "list_dir",
        description="列出 workspace 目录下的文件与子目录。path 为相对路径，默认 '.'。",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "相对 workspace 的目录路径，默认 '.'",
                }
            },
        },
        handler=_list_dir,
    )
    register(
        "read_file",
        description="读取 workspace 内的文本文件内容（UTF-8）。",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "相对 workspace 的文件路径",
                }
            },
            "required": ["path"],
        },
        handler=_read_file,
    )
    register(
        "write_file",
        description="向 workspace 写入文本文件（UTF-8）。会自动创建缺失的父目录。需要用户审批。",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "相对 workspace 的文件路径",
                },
                "content": {
                    "type": "string",
                    "description": "要写入的完整文本内容",
                },
            },
            "required": ["path", "content"],
        },
        handler=_write_file,
        requires_approval=True,
    )
    register(
        "delete_file",
        description="删除 workspace 内的单个文件（不能删目录）。需要用户审批。",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "相对 workspace 的文件路径",
                }
            },
            "required": ["path"],
        },
        handler=_delete_file,
        requires_approval=True,
    )


register_workspace_tools()
