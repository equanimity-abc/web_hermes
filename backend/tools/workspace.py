"""Workspace file tools — paths are sandboxed under WORKSPACE_DIR."""

from __future__ import annotations

import json
from pathlib import Path

from config import config
from tools.registry import register

_MAX_READ_CHARS = 80_000
_MAX_WRITE_CHARS = 200_000
_MAX_LIST = 500


def _workspace_root() -> Path:
    root = Path(config.WORKSPACE_DIR).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _resolve_safe(rel_path: str) -> Path:
    root = _workspace_root()
    raw = (rel_path or ".").strip() or "."
    candidate = Path(raw)
    if candidate.is_absolute():
        raise ValueError("禁止使用绝对路径，请使用相对 workspace 的路径")
    target = (root / candidate).resolve()
    try:
        target.relative_to(root)
    except ValueError as e:
        raise ValueError("路径越出 workspace 沙箱") from e
    return target


def _list_dir(args: dict) -> str:
    rel = str(args.get("path") or ".")
    try:
        target = _resolve_safe(rel)
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
                "workspace": str(_workspace_root()),
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
        target = _resolve_safe(rel)
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
        target = _resolve_safe(rel)
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
        description="向 workspace 写入文本文件（UTF-8）。会自动创建缺失的父目录。",
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
    )


register_workspace_tools()
