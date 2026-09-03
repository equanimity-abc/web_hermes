"""Series-level consistency hooks (palette, embeddings, dual-speaker notes)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.workspace import resolve_safe

DEFAULT_DUAL_SPEAKER = {
    "strategy": "lock_lr",
    "note": "双人 CU 先锁 L/R 再口型",
}

DEFAULT_SERIES_META: dict[str, Any] = {
    "palette": [],
    "lighting": "",
    "dual_speaker": dict(DEFAULT_DUAL_SPEAKER),
    "version": 1,
}

_SFX_BASIC: dict[str, str] = {
    "action": "whoosh",
    "insert": "click",
}


def series_rel(slug: str) -> str:
    return f"dramas/{slug}/.series"


def series_dir(slug: str) -> Path:
    path = resolve_safe(series_rel(slug))
    path.mkdir(parents=True, exist_ok=True)
    return path


def series_meta_rel(slug: str) -> str:
    return f"{series_rel(slug)}/meta.json"


def load_series_meta(slug: str) -> dict[str, Any]:
    try:
        path = resolve_safe(series_meta_rel(slug))
    except ValueError:
        return dict(DEFAULT_SERIES_META)
    if not path.is_file():
        return {
            "palette": [],
            "lighting": "",
            "dual_speaker": dict(DEFAULT_DUAL_SPEAKER),
            "version": 1,
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "palette": [],
            "lighting": "",
            "dual_speaker": dict(DEFAULT_DUAL_SPEAKER),
            "version": 1,
        }
    if not isinstance(data, dict):
        return {
            "palette": [],
            "lighting": "",
            "dual_speaker": dict(DEFAULT_DUAL_SPEAKER),
            "version": 1,
        }
    out = {
        "palette": list(data.get("palette") or []),
        "lighting": str(data.get("lighting") or ""),
        "dual_speaker": dict(DEFAULT_DUAL_SPEAKER),
        "version": int(data.get("version") or 1),
    }
    dual = data.get("dual_speaker")
    if isinstance(dual, dict) and dual:
        out["dual_speaker"] = {
            "strategy": str(dual.get("strategy") or DEFAULT_DUAL_SPEAKER["strategy"]),
            "note": str(dual.get("note") or DEFAULT_DUAL_SPEAKER["note"]),
        }
    return out


def save_series_meta(slug: str, data: dict[str, Any]) -> dict[str, Any]:
    series_dir(slug)
    payload = {
        "palette": list((data or {}).get("palette") or []),
        "lighting": str((data or {}).get("lighting") or ""),
        "dual_speaker": dict(DEFAULT_DUAL_SPEAKER),
        "version": int((data or {}).get("version") or 1),
    }
    dual = (data or {}).get("dual_speaker")
    if isinstance(dual, dict) and dual:
        payload["dual_speaker"] = {
            "strategy": str(dual.get("strategy") or DEFAULT_DUAL_SPEAKER["strategy"]),
            "note": str(dual.get("note") or DEFAULT_DUAL_SPEAKER["note"]),
        }
    path = resolve_safe(series_meta_rel(slug))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def embedding_rel(slug: str, cid: str) -> str:
    return f"{series_rel(slug)}/embeddings/{cid}.json"


def embedding_path(slug: str, cid: str) -> Path:
    return resolve_safe(embedding_rel(slug, cid))


def load_character_embedding(slug: str, cid: str) -> list[float] | None:
    cid = str(cid or "").strip()
    if not cid:
        return None
    try:
        path = embedding_path(slug, cid)
    except ValueError:
        return None
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    emb = data.get("embedding")
    if not isinstance(emb, list) or not emb:
        return None
    try:
        return [float(x) for x in emb]
    except (TypeError, ValueError):
        return None


def save_character_embedding(
    slug: str,
    cid: str,
    emb: list[float],
    *,
    method: str = "",
    ref_rel: str = "",
) -> Path:
    cid = str(cid or "").strip()
    vec = [float(x) for x in emb]
    path = embedding_path(slug, cid)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "cid": cid,
        "embedding": vec,
        "dims": len(vec),
        "method": str(method or ""),
        "ref_rel": str(ref_rel or "").replace("\\", "/"),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def ensure_character_embedding(slug: str, cid: str) -> dict[str, Any]:
    """Return cached ArcFace embedding or compute from character ref (soft-fail)."""
    cid = str(cid or "").strip()
    empty = {"ok": False, "cid": cid, "dims": 0, "cached": False, "method": ""}
    if not cid:
        return empty

    cached = load_character_embedding(slug, cid)
    if cached is not None:
        method = ""
        try:
            raw = json.loads(embedding_path(slug, cid).read_text(encoding="utf-8"))
            method = str((raw or {}).get("method") or "arcface")
        except Exception:
            method = "arcface"
        return {
            "ok": True,
            "cid": cid,
            "dims": len(cached),
            "cached": True,
            "method": method or "arcface",
        }

    from tools.drama_characters import find_character, load_characters, ref_exists, ref_rel
    from tools.drama_qc import _arcface_embedding

    cards = load_characters(slug)
    char = find_character(cards, cid)
    if char is None or not ref_exists(slug, char):
        return {**empty, "method": "no_ref"}
    rel = str(char.get("ref") or ref_rel(slug, cid)).replace("\\", "/")
    try:
        path = resolve_safe(rel)
    except ValueError:
        return {**empty, "method": "bad_ref"}
    if not path.is_file():
        return {**empty, "method": "no_ref"}

    emb, method = _arcface_embedding(path)
    if emb is None:
        return {**empty, "method": method or "no_face"}

    save_character_embedding(slug, cid, emb, method=method, ref_rel=rel)
    return {
        "ok": True,
        "cid": cid,
        "dims": len(emb),
        "cached": False,
        "method": method or "arcface",
    }


def ensure_cast_embeddings(slug: str) -> list[str]:
    """Ensure embeddings for every character with a ref; return cids cached/created."""
    from tools.drama_characters import load_characters, ref_exists

    done: list[str] = []
    for rec in load_characters(slug):
        if str(rec.get("category") or "character") != "character":
            continue
        cid = str(rec.get("id") or "").strip()
        if not cid or not ref_exists(slug, rec):
            continue
        result = ensure_character_embedding(slug, cid)
        if result.get("ok"):
            done.append(cid)
    return done


def apply_dual_speaker_notes(shot: dict[str, Any]) -> dict[str, Any]:
    """Annotate dual-speaker strategy on multi-role dialogue/reaction shots."""
    from tools.drama_characters import normalize_roles
    from tools.drama_models import infer_kind

    roles = normalize_roles(shot.get("角色"))
    kind = infer_kind(shot)
    if len(roles) >= 2 and kind in ("dialogue", "reaction"):
        if not isinstance(shot.get("dual_speaker"), dict) or not shot.get("dual_speaker"):
            shot["dual_speaker"] = dict(DEFAULT_DUAL_SPEAKER)
    return shot


def apply_dual_speaker_notes_doc(doc: dict[str, Any]) -> int:
    """Apply dual-speaker notes across a shots doc; return count of shots annotated."""
    count = 0
    for shot in doc.get("shots") or []:
        if not isinstance(shot, dict):
            continue
        before = shot.get("dual_speaker")
        apply_dual_speaker_notes(shot)
        after = shot.get("dual_speaker")
        if after and not before:
            count += 1
    return count


def sfx_basic_for_kind(kind: str) -> str | None:
    """Placeholder basic SFX catalog hook."""
    return _SFX_BASIC.get(str(kind or "").strip()) or None
