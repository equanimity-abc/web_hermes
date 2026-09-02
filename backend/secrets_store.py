"""Local secrets overlay for API keys (UI-editable).

Precedence at runtime: data/secrets.json overrides empty/.env values after apply.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from config import _BACKEND_DIR, config

SECRETS_PATH = Path(
    os.getenv("SECRETS_PATH", str(_BACKEND_DIR / "data" / "secrets.json"))
)

SECRET_FIELDS: tuple[str, ...] = (
    "DEEPSEEK_API_KEY",
    "KIMI_API_KEY",
    "ARK_API_KEY",
    "DASHSCOPE_API_KEY",
)


def secrets_path() -> Path:
    return SECRETS_PATH.expanduser().resolve()


def load_secrets_file() -> dict[str, str]:
    path = secrets_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, val in raw.items():
        if key in SECRET_FIELDS and str(val or "").strip():
            out[key] = str(val).strip()
    return out


def apply_secrets_to_config(data: dict[str, str] | None = None) -> None:
    payload = data if data is not None else load_secrets_file()
    for key, val in payload.items():
        if key not in SECRET_FIELDS:
            continue
        text = str(val or "").strip()
        if not text:
            continue
        os.environ[key] = text
        if hasattr(config, key):
            setattr(config, key, text)


def save_secrets(patch: dict[str, Any]) -> dict[str, Any]:
    current = load_secrets_file()
    for key in SECRET_FIELDS:
        if key not in patch:
            continue
        raw = patch.get(key)
        if raw is None:
            continue
        text = str(raw).strip()
        if not text:
            current.pop(key, None)
            continue
        current[key] = text
    path = secrets_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    apply_secrets_to_config(current)
    return public_secrets_status()


def _mask(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= 8:
        return "*" * len(text)
    return text[:4] + "…" + text[-4:]


def public_secrets_status() -> dict[str, Any]:
    file_vals = load_secrets_file()
    items = []
    labels = {
        "DEEPSEEK_API_KEY": "DeepSeek",
        "KIMI_API_KEY": "Kimi（月之暗面）",
        "ARK_API_KEY": "火山方舟",
        "DASHSCOPE_API_KEY": "阿里云百炼",
    }
    for key in SECRET_FIELDS:
        live = str(getattr(config, key, "") or os.getenv(key, "") or "").strip()
        file_val = file_vals.get(key, "")
        source = "secrets" if file_val else ("env" if live else "empty")
        items.append(
            {
                "key": key,
                "label": labels.get(key, key),
                "configured": bool(live),
                "source": source,
                "masked": _mask(live),
            }
        )
    return {
        "path": str(secrets_path()),
        "keys": items,
        "providers": {
            "deepseek": {
                "base_url": getattr(config, "DEEPSEEK_BASE_URL", ""),
                "model": getattr(config, "DEEPSEEK_MODEL", ""),
            },
            "kimi": {
                "base_url": getattr(config, "KIMI_BASE_URL", ""),
                "model": getattr(config, "KIMI_MODEL", ""),
            },
            "ark": {
                "base_url": getattr(config, "ARK_BASE_URL", ""),
                "text_models": [
                    getattr(config, "ARK_TEXT_MODEL", ""),
                    getattr(config, "ARK_TEXT_MODEL_ALT", ""),
                ],
                "image_model": getattr(config, "ARK_IMAGE_MODEL", ""),
                "video_model": getattr(config, "ARK_VIDEO_MODEL", ""),
                "audio_model": getattr(config, "ARK_AUDIO_MODEL", ""),
            },
        },
        "script_alternatives": [
            {"provider": "deepseek", "model": getattr(config, "DEEPSEEK_MODEL", "deepseek-v4-pro")},
            {"provider": "kimi", "model": getattr(config, "KIMI_MODEL", "kimi-k3")},
        ],
    }
