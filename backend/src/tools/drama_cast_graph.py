"""Character naming + relationship graph for drama cast.

Names must be short, unique display names (e.g.「小石」), never kinship
compounds like「愚公的小孙女」. Kinship / social links live in
``dramas/{slug}/relationships.json``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from tools.workspace import resolve_safe

_PAREN_NICK_RE = re.compile(r"[（(]([^）)]{1,24})[）)]")
_KINSHIP_COMPOUND_RE = re.compile(
    r".+[的之](小)?(孙|儿|女|爷|奶|爸|妈|哥|姐|弟|妹|侄|甥|妻|夫|友|邻).*"
)
_REL_LINE_RE = re.compile(
    r"^[-*•]?\s*(.+?)\s*(?:→|->|—|–)\s*(.+?)\s*[:：]\s*(.+?)\s*$"
)


def relationships_rel(slug: str) -> str:
    return f"dramas/{slug}/relationships.json"


def load_relationships(slug: str) -> dict[str, Any]:
    rel = relationships_rel(slug)
    path = resolve_safe(rel)
    if not path.is_file():
        return {"slug": slug, "edges": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"slug": slug, "edges": []}
    if not isinstance(data, dict):
        return {"slug": slug, "edges": []}
    edges = data.get("edges") if isinstance(data.get("edges"), list) else []
    return {"slug": slug, "edges": [e for e in edges if isinstance(e, dict)]}


def save_relationships(slug: str, doc: dict[str, Any]) -> str:
    payload = {
        "slug": slug,
        "edges": [e for e in (doc.get("edges") or []) if isinstance(e, dict)],
    }
    rel = relationships_rel(slug)
    path = resolve_safe(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return rel


def extract_parenthetical_nickname(raw: str) -> str:
    m = _PAREN_NICK_RE.search(str(raw or ""))
    return (m.group(1).strip() if m else "")


def is_kinship_compound_name(raw: str) -> bool:
    s = _PAREN_NICK_RE.sub("", str(raw or "")).strip()
    if not s:
        return False
    if _KINSHIP_COMPOUND_RE.match(s):
        return True
    # 「愚公的小孙女」类：含「的/之」且较长
    if ("的" in s or "之" in s) and len(s) >= 4:
        return True
    return False


def preferred_character_name(raw: str) -> tuple[str, list[str]]:
    """Normalize a cast heading into (display_name, aliases).

    「愚公的小孙女（小石）」→ name=小石, aliases=[愚公的小孙女, 愚公的小孙女（小石）]
    「愚公」→ name=愚公
    """
    text = str(raw or "").strip()
    if not text:
        return "", []
    nick = extract_parenthetical_nickname(text)
    base = _PAREN_NICK_RE.sub("", text).strip() or text
    aliases: list[str] = []
    if nick and (is_kinship_compound_name(base) or is_kinship_compound_name(text)):
        for a in (base, text):
            if a and a != nick and a not in aliases:
                aliases.append(a)
        return nick, aliases
    if nick and nick != base:
        # 「小石（愚公孙女）」少见：仍以括号外为主名
        if nick not in aliases and nick != base:
            aliases.append(nick)
        return base, aliases
    return text, aliases


def parse_relationship_section(text: str) -> list[dict[str, str]]:
    """Parse ``## 角色关系`` lines: ``- 小石 → 愚公：孙女``."""
    lines = str(text or "").replace("\r\n", "\n").split("\n")
    in_section = False
    edges: list[dict[str, str]] = []
    for raw in lines:
        line = raw.rstrip()
        if line.startswith("## ") and not line.startswith("### "):
            title = line[3:].strip()
            in_section = title.startswith("角色关系") or title in ("人物关系", "关系图谱")
            continue
        if not in_section:
            continue
        if line.startswith("## ") or line.startswith("### "):
            in_section = False
            continue
        m = _REL_LINE_RE.match(line.strip())
        if not m:
            continue
        src, dst, rel = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
        if src and dst and rel:
            edges.append({"from": src, "to": dst, "rel": rel})
    return edges


def upsert_relationship_edges(slug: str, edges: list[dict[str, str]]) -> dict[str, Any]:
    doc = load_relationships(slug)
    existing = {
        (str(e.get("from") or ""), str(e.get("to") or ""), str(e.get("rel") or "")): e
        for e in doc.get("edges") or []
    }
    for edge in edges:
        key = (str(edge.get("from") or ""), str(edge.get("to") or ""), str(edge.get("rel") or ""))
        if not key[0] or not key[1] or not key[2]:
            continue
        existing[key] = {"from": key[0], "to": key[1], "rel": key[2]}
    doc["edges"] = list(existing.values())
    save_relationships(slug, doc)
    return doc


def bind_relationship_ids(slug: str, characters: list[dict[str, Any]]) -> dict[str, Any]:
    """Attach from_id/to_id using current cast cards."""
    from tools.drama_characters import match_character_token

    doc = load_relationships(slug)
    out_edges: list[dict[str, Any]] = []
    for edge in doc.get("edges") or []:
        row = dict(edge)
        src = match_character_token(str(row.get("from") or ""), characters)
        dst = match_character_token(str(row.get("to") or ""), characters)
        if src:
            row["from_id"] = str(src.get("id") or "")
        if dst:
            row["to_id"] = str(dst.get("id") or "")
        out_edges.append(row)
    doc["edges"] = out_edges
    save_relationships(slug, doc)
    return doc


def relationships_prompt_block(slug: str) -> str:
    doc = load_relationships(slug)
    edges = doc.get("edges") or []
    if not edges:
        return ""
    lines = ["角色关系图谱（姓名须与角色设定一致，禁止用关系称呼代替姓名）："]
    for e in edges:
        lines.append(f"- {e.get('from')} → {e.get('to')}：{e.get('rel')}")
    return "\n".join(lines)


def loose_name_compatible(cand: str, name: str) -> bool:
    """Safe fuzzy equality for cast matching (no「愚公」→「愚公的小孙女」)."""
    a = str(cand or "").strip()
    b = str(name or "").strip()
    if not a or not b:
        return False
    if a == b:
        return True
    # nickname in parentheses
    if extract_parenthetical_nickname(b) == a or extract_parenthetical_nickname(a) == b:
        return True
    # never fuzzy-match kinship compounds
    if is_kinship_compound_name(a) or is_kinship_compound_name(b):
        return False
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) < 2:
        return False
    # allow「后羿」in「后羿（仅影子）」after paren strip
    longer_base = _PAREN_NICK_RE.sub("", longer).strip() or longer
    if shorter == longer_base:
        return True
    # contain only when shorter is a large fraction of longer
    if shorter in longer and len(shorter) / max(len(longer), 1) >= 0.6:
        return True
    return False
