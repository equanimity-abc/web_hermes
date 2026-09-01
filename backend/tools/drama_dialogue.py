"""DialogueTrack: N-speaker dialogue pipeline for one shot (2, 3, …).

Contract
--------
剧本角色 / 具名台词
  → 自动匹配角色卡（canonical name + voice + face_ref）
  → DialogueTrack.turns（每人一段，可复用）
  → per-turn TTS → master voice.mp3 + 时间轴
  → lip_strategy=per_turn：每段用该角色定妆脸锁定口型，再拼接

Single-speaker is the same object with ``mode="single"``.
Never invent voices: each turn uses the bound character card voice.
Face matching uses character ref images when present.

Does not touch agent/loop.py.
"""

from __future__ import annotations

import re
from typing import Any

from tools.drama_characters import match_character_token, public_voices

_NAMED_QUOTE = re.compile(
    r"(?P<name>[^:：\s「『“\"（(【\[]{1,16})"
    r"(?:\s*[（(][^）)]{0,40}[）)])?"
    r"\s*[:：]\s*[「『“\"](?P<text>[^」』”\"]+)[」』”\"]"
)
_NAMED_LINE = re.compile(
    r"^(?P<name>[^:：\s「『“\"（(【\[]{1,16})"
    r"(?:\s*[（(][^）)]{0,40}[）)])?"
    r"\s*[:：]\s*(?P<text>.+?)\s*$"
)
_NAMED_BULLET = re.compile(
    r"^[-*·•]\s*(?P<name>[^:：\s「『“\"（(【\[]{1,16})"
    r"(?:\s*[（(][^）)]{0,40}[）)])?"
    r"\s*[:：]\s*(?P<text>.+?)\s*$"
)
_SPEAKER_PREFIX = re.compile(
    r"^(?:【[^】]{1,12}】|\[[^\]]{1,12}\])?"
    r"[^:：\s「『“\"]{1,16}"
    r"(?:\s*[（(][^）)]{0,40}[）)])?"
    r"\s*[:：]\s*"
)
_STAGE_PAREN = re.compile(r"[（(][^）)]{0,24}[）)]")
_QUOTE = re.compile(r"[「『“\"]([^」』”\"]+)[」』”\"]")
_PLAIN_TURN_SPLIT = re.compile(r"(?:……+|…{2,}|——+|--+)")

TRACK_VERSION = 1


def speaker_key(name: str) -> str:
    return re.sub(r"[\s【】\[\]]+", "", str(name or "").strip())


def speakers_match(a: str, b: str) -> bool:
    x, y = speaker_key(a), speaker_key(b)
    if not x or not y:
        return False
    if x == y:
        return True
    return x.startswith(y) or y.startswith(x)


def _plain_spoken(dialogue: str) -> str:
    text = (dialogue or "").strip()
    if not text:
        return ""
    quotes = [q.strip() for q in _QUOTE.findall(text) if q.strip()]
    if quotes:
        out = quotes[0]
        for q in quotes[1:]:
            if out[-1] not in "。！？!?…":
                out += "。"
            out += q
        return out
    cleaned = _SPEAKER_PREFIX.sub("", text).strip()
    cleaned = _STAGE_PAREN.sub("", cleaned).strip()
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ：:，,")
    return cleaned or text


def parse_dialogue_segments(dialogue: str) -> list[tuple[str, str]]:
    """Return [(speaker_name, spoken_line), ...] from script-style 字幕 (N speakers)."""
    text = (dialogue or "").strip()
    if not text:
        return []
    segs = [(m.group("name").strip(), m.group("text").strip()) for m in _NAMED_QUOTE.finditer(text)]
    segs = [(n, t) for n, t in segs if n and t]
    if segs:
        return segs
    line_segs: list[tuple[str, str]] = []
    for raw_line in re.split(r"[\n\r]+", text):
        line = raw_line.strip()
        if not line:
            continue
        m = _NAMED_BULLET.match(line) or _NAMED_LINE.match(line)
        if not m:
            continue
        name = m.group("name").strip()
        spoken = m.group("text").strip().strip("「『“”」』\"'")
        spoken = _STAGE_PAREN.sub("", spoken).strip()
        if name and spoken:
            line_segs.append((name, spoken))
    if line_segs:
        return line_segs
    plain = _plain_spoken(text)
    return [("", plain)] if plain else []


def _join_spoken(parts: list[str]) -> str:
    out = ""
    for p in parts:
        p = (p or "").strip()
        if not p:
            continue
        if not out:
            out = p
            continue
        if out[-1] not in "。！？!?…":
            out += "。"
        out += p
    return out


def _character_face_ref(slug: str | None, char: dict[str, Any] | None) -> tuple[str, bool]:
    """Return (face_ref_rel, face_ready) from character card 定妆图."""
    if not slug or not char:
        return "", False
    try:
        from tools.drama_characters import ref_exists, ref_rel
    except Exception:
        return "", False
    cid = str(char.get("id") or "").strip()
    if not cid:
        return "", False
    rel = str(char.get("ref") or ref_rel(slug, cid)).replace("\\", "/")
    ready = bool(ref_exists(slug, char))
    return rel, ready


def resolve_speaker_binding(
    speaker: str,
    cast: list[dict[str, Any]],
    *,
    slug: str | None = None,
    fallback_voice: str = "",
) -> dict[str, Any]:
    """Map a script token → character card: name + voice + face_ref (N-speaker safe)."""
    raw = str(speaker or "").strip()
    labels = {row["id"]: row["label"] for row in public_voices(slug)}
    char = match_character_token(raw, cast) if raw else None
    if char is None and raw:
        for c in cast:
            if speakers_match(raw, str(c.get("name") or "")) or speakers_match(
                raw, str(c.get("id") or "")
            ):
                char = c
                break
            aliases = c.get("aliases") or []
            if isinstance(aliases, list) and any(speakers_match(raw, str(a)) for a in aliases):
                char = c
                break
    voice = ""
    cid = ""
    cname = ""
    if char:
        cid = str(char.get("id") or "")
        cname = str(char.get("name") or "").strip() or cid
        voice = str(char.get("voice") or "").strip()
    if not cname:
        cname = raw or "（未命名）"
    if not voice:
        voice = str(fallback_voice or "").strip()
    try:
        from tools.drama_characters import safe_tts_voice

        voice = safe_tts_voice(voice)
    except Exception:
        pass
    face_ref, face_ready = _character_face_ref(slug, char)
    return {
        "speaker": cname,
        "script_speaker": raw,
        "character_id": cid,
        "character_name": cname,
        "voice": voice,
        "voice_label": labels.get(voice) or voice or "—",
        "face_ref": face_ref,
        "face_ready": face_ready,
    }


def _shot_role_tokens(shot: dict[str, Any]) -> list[str]:
    roles = shot.get("角色") or []
    if isinstance(roles, str):
        roles = [r.strip() for r in re.split(r"[,，、/|]", roles) if r.strip()]
    if not isinstance(roles, list):
        return []
    return [str(r).strip() for r in roles if str(r).strip()]


def _char_mention_pos(text: str, char: dict[str, Any]) -> int:
    names = [str(char.get("name") or "")]
    aliases = char.get("aliases") or []
    if isinstance(aliases, list):
        names.extend(str(a) for a in aliases)
    cid = str(char.get("id") or "")
    if cid:
        names.append(cid)
    best = 10**9
    for n in names:
        n = str(n or "").strip()
        if not n:
            continue
        i = text.find(n)
        if i >= 0:
            best = min(best, i)
    return best


def _resolve_char_list(
    tokens: list[str],
    cast: list[dict[str, Any]],
    *,
    slug: str | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tok in tokens:
        bind = resolve_speaker_binding(tok, cast, slug=slug)
        cid = bind.get("character_id") or speaker_key(bind.get("character_name") or tok)
        if not cid or cid in seen:
            continue
        seen.add(cid)
        char = next((c for c in cast if str(c.get("id") or "") == bind.get("character_id")), None)
        if char is None:
            char = {
                "id": bind.get("character_id") or "",
                "name": bind.get("character_name") or tok,
                "voice": bind.get("voice") or "",
                "aliases": [tok],
                "ref": bind.get("face_ref") or "",
            }
        out.append(char)
    return out


def speaking_cast_for_shot(
    shot: dict[str, Any],
    cast: list[dict[str, Any]],
    *,
    slug: str | None = None,
) -> list[dict[str, Any]]:
    """Characters in this shot, ordered for turn assignment (any N).

    Order priority:
      1) first *named speaker* in 字幕 (A: "…") — not kinship words inside lines
      2) first mention in 画面
      3) 角色 list order

    Plain 字幕 must NOT scan aliases like「姐姐」inside spoken text — that wrongly
    puts 白若曦 before 白若琳 on lines like「对不起姐姐」.
    """
    dialogue = str(shot.get("字幕") or shot.get("对白") or "")
    scene = str(shot.get("画面") or "")
    named = [n for n, t in parse_dialogue_segments(dialogue) if n and t]
    role_tokens = _shot_role_tokens(shot)
    tokens: list[str] = []
    for t in named + role_tokens:
        if t and t not in tokens:
            tokens.append(t)
    resolved = _resolve_char_list(tokens, cast, slug=slug)
    if not resolved:
        return []

    # Map character_id → first named-speaker index in 字幕
    named_rank: dict[str, int] = {}
    for i, tok in enumerate(named):
        bind = resolve_speaker_binding(tok, cast, slug=slug)
        cid = bind.get("character_id") or speaker_key(bind.get("character_name") or tok)
        if cid and cid not in named_rank:
            named_rank[cid] = i

    def sort_key(char: dict[str, Any], idx: int) -> tuple[int, int, int]:
        cid = str(char.get("id") or "") or speaker_key(str(char.get("name") or ""))
        if named_rank:
            return (named_rank.get(cid, 10**9), 0, idx)
        spos = _char_mention_pos(scene, char)
        return (
            spos if spos < 10**9 else 10**9,
            idx,
            0,
        )

    indexed = list(enumerate(resolved))
    indexed.sort(key=lambda pair: sort_key(pair[1], pair[0]))
    return [c for _, c in indexed]


def _fallback_voice(shot: dict[str, Any], cast: list[dict[str, Any]], slug: str | None) -> str:
    explicit = str(shot.get("voice") or "").strip()
    if explicit:
        return explicit
    speaker = str(shot.get("speaker") or "").strip()
    if speaker:
        return resolve_speaker_binding(speaker, cast, slug=slug).get("voice") or ""
    for char in cast:
        if str(char.get("category") or "character") not in ("", "character"):
            continue
        voice = str(char.get("voice") or "").strip()
        if voice:
            return voice
    from tools.drama_characters import DEFAULT_VOICE

    return DEFAULT_VOICE


def match_cast_bindings(
    shot: dict[str, Any],
    cast: list[dict[str, Any]],
    *,
    slug: str | None = None,
) -> list[dict[str, Any]]:
    """Auto-match script roles → character card voice + face (for UI / lip / TTS)."""
    fallback = _fallback_voice(shot, cast, slug)
    out: list[dict[str, Any]] = []
    for char in speaking_cast_for_shot(shot, cast, slug=slug):
        bind = resolve_speaker_binding(
            str(char.get("name") or char.get("id") or ""),
            cast,
            slug=slug,
            fallback_voice=fallback,
        )
        if not bind.get("character_id"):
            continue
        out.append(bind)
    return out


def _split_plain_parts(text: str) -> list[str]:
    """Split unnamed 字幕 into ordered beats (supports 2+ turns)."""
    text = (text or "").strip()
    if not text:
        return []
    parts = [p.strip() for p in _PLAIN_TURN_SPLIT.split(text) if p.strip()]
    if len(parts) >= 2:
        return parts
    lines = [ln.strip() for ln in re.split(r"[\n\r]+", text) if ln.strip()]
    if len(lines) >= 2:
        return lines
    sents = re.findall(r"[^。！？!?]+[。！？!?]?", text)
    sents = [s.strip() for s in sents if s.strip()]
    if len(sents) >= 2:
        return sents
    return [text]


def infer_plain_multi_segments(
    shot: dict[str, Any],
    cast: list[dict[str, Any]],
    plain: str,
    *,
    slug: str | None = None,
) -> list[tuple[str, str]]:
    """Assign plain beats to N cast members (round-robin when parts > cast)."""
    text = (plain or "").strip()
    if not text:
        return []
    order = speaking_cast_for_shot(shot, cast, slug=slug)
    if len(order) < 2:
        return []
    parts = _split_plain_parts(text)
    if len(parts) < 2:
        return []
    out: list[tuple[str, str]] = []
    for i, part in enumerate(parts):
        char = order[i % len(order)]
        out.append((str(char.get("name") or ""), part))
    names = {n for n, _ in out if n}
    if len(names) < 2:
        return []
    return [(n, t) for n, t in out if n and t]


def empty_dialogue_track() -> dict[str, Any]:
    return {
        "version": TRACK_VERSION,
        "mode": "single",
        "turns": [],
        "bindings": [],
        "primary_speaker": "",
        "total_duration": 0.0,
        "lip_strategy": "master",
        "cast_matched": 0,
    }


def _turn_row(i: int, bind: dict[str, Any], text: str) -> dict[str, Any]:
    return {
        "index": i,
        "speaker": bind.get("character_name") or bind.get("speaker") or "",
        "script_speaker": bind.get("script_speaker") or "",
        "character_id": bind.get("character_id") or "",
        "character_name": bind.get("character_name") or "",
        "text": text,
        "voice": bind.get("voice") or "",
        "voice_label": bind.get("voice_label") or "",
        "face_ref": bind.get("face_ref") or "",
        "face_ready": bool(bind.get("face_ready")),
        "start": 0.0,
        "end": 0.0,
    }


def _binding_row(bind: dict[str, Any]) -> dict[str, Any]:
    cname = str(bind.get("character_name") or bind.get("speaker") or "")
    return {
        "speaker": cname,
        "character_id": str(bind.get("character_id") or ""),
        "character_name": cname,
        "voice": str(bind.get("voice") or ""),
        "voice_label": str(bind.get("voice_label") or ""),
        "face_ref": str(bind.get("face_ref") or ""),
        "face_ready": bool(bind.get("face_ready")),
    }


def build_dialogue_track(
    shot: dict[str, Any],
    cast: list[dict[str, Any]],
    *,
    slug: str | None = None,
) -> dict[str, Any]:
    """
    Build DialogueTrack: auto-match every script speaker to a character card.

    Pass **full project characters** as ``cast`` so aliases resolve for any N.
    """
    track = empty_dialogue_track()
    dialogue = str(shot.get("字幕") or shot.get("对白") or "")
    segs = parse_dialogue_segments(dialogue)
    if not segs:
        matched = match_cast_bindings(shot, cast, slug=slug)
        track["bindings"] = [_binding_row(b) for b in matched]
        track["cast_matched"] = len(matched)
        return track

    named = [(n, t) for n, t in segs if n and t]
    distinct_cids: list[str] = []
    seen_cid: set[str] = set()
    for n, _ in named:
        bind = resolve_speaker_binding(n, cast, slug=slug)
        key = bind.get("character_id") or speaker_key(bind.get("character_name") or n)
        if key in seen_cid:
            continue
        seen_cid.add(key)
        distinct_cids.append(key)

    fallback = _fallback_voice(shot, cast, slug)
    turns: list[dict[str, Any]] = []

    if len(distinct_cids) >= 2:
        track["mode"] = "multi"
        track["lip_strategy"] = "per_turn"
        for i, (name, text) in enumerate(named):
            bind = resolve_speaker_binding(name, cast, slug=slug, fallback_voice=fallback)
            turns.append(_turn_row(i, bind, text))
        primary_raw = str(shot.get("speaker") or "").strip()
        primary = resolve_speaker_binding(primary_raw, cast, slug=slug) if primary_raw else None
        track["primary_speaker"] = (
            (primary or {}).get("character_name")
            or turns[0]["character_name"]
            or turns[0]["speaker"]
        )
    else:
        plain = segs[0][1] if segs and not segs[0][0] else ""
        inferred = infer_plain_multi_segments(shot, cast, plain, slug=slug) if plain else []
        if len(inferred) >= 2:
            track["mode"] = "multi"
            track["lip_strategy"] = "per_turn"
            for i, (name, text) in enumerate(inferred):
                bind = resolve_speaker_binding(name, cast, slug=slug, fallback_voice=fallback)
                turns.append(_turn_row(i, bind, text))
            primary_raw = str(shot.get("speaker") or "").strip()
            primary = resolve_speaker_binding(primary_raw, cast, slug=slug) if primary_raw else None
            track["primary_speaker"] = (
                (primary or {}).get("character_name")
                or turns[-1]["character_name"]
                or turns[0]["character_name"]
            )
        else:
            track["mode"] = "single"
            track["lip_strategy"] = "master"
            if named:
                text = _join_spoken([t for _, t in named])
                speaker = str(shot.get("speaker") or "").strip() or named[0][0]
            else:
                text = segs[0][1]
                speaker = str(shot.get("speaker") or "").strip()
            if not text:
                matched = match_cast_bindings(shot, cast, slug=slug)
                track["bindings"] = [_binding_row(b) for b in matched]
                track["cast_matched"] = len(matched)
                return track
            bind = resolve_speaker_binding(speaker, cast, slug=slug, fallback_voice=fallback)
            if not bind["voice"]:
                bind["voice"] = fallback
                labels = {row["id"]: row["label"] for row in public_voices(slug)}
                bind["voice_label"] = labels.get(fallback) or fallback or "—"
            turns.append(_turn_row(0, bind, text))
            track["primary_speaker"] = turns[0]["character_name"] or turns[0]["speaker"]

    track["turns"] = turns
    bindings: list[dict[str, Any]] = []
    seen_bind: set[str] = set()
    for turn in turns:
        key = turn.get("character_id") or speaker_key(
            str(turn.get("character_name") or turn.get("speaker") or "")
        )
        if not key or key in seen_bind:
            continue
        seen_bind.add(key)
        bindings.append(
            {
                "speaker": str(turn.get("character_name") or turn.get("speaker") or ""),
                "character_id": str(turn.get("character_id") or ""),
                "character_name": str(turn.get("character_name") or ""),
                "voice": str(turn.get("voice") or ""),
                "voice_label": str(turn.get("voice_label") or ""),
                "face_ref": str(turn.get("face_ref") or ""),
                "face_ready": bool(turn.get("face_ready")),
            }
        )
    for bind in match_cast_bindings(shot, cast, slug=slug):
        key = bind.get("character_id") or speaker_key(bind.get("character_name") or "")
        if not key or key in seen_bind:
            continue
        seen_bind.add(key)
        bindings.append(_binding_row(bind))
    track["bindings"] = bindings
    track["cast_matched"] = sum(1 for b in bindings if b.get("character_id"))
    return track


def apply_turn_timings(track: dict[str, Any], timed: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge TTS timing (start/end) into track turns; set total_duration."""
    out = dict(track or empty_dialogue_track())
    turns = [dict(t) for t in (out.get("turns") or [])]
    by_index = {int(t.get("index") or i): t for i, t in enumerate(turns)}
    cursor_end = 0.0
    for i, row in enumerate(timed or []):
        turn = by_index.get(i)
        if turn is None and i < len(turns):
            turn = turns[i]
        if turn is None:
            continue
        start = float(row.get("start") or 0)
        end = float(row.get("end") or start)
        turn["start"] = round(start, 3)
        turn["end"] = round(end, 3)
        if row.get("voice"):
            turn["voice"] = str(row.get("voice") or turn.get("voice") or "")
        cursor_end = max(cursor_end, end)
    out["turns"] = [by_index[k] for k in sorted(by_index)] if by_index else turns
    out["total_duration"] = round(cursor_end, 3)
    return out


def infer_turn_timings_from_voice(track: dict[str, Any], voice_duration: float) -> dict[str, Any]:
    """When turn timings were lost on disk, split master VO by text weight per turn."""
    turns = list((track or {}).get("turns") or [])
    if len(turns) < 2 or voice_duration <= 0:
        return track or empty_dialogue_track()
    weights = [max(len(str(t.get("text") or "")), 1) for t in turns]
    total_w = float(sum(weights)) or 1.0
    cursor = 0.0
    timed: list[dict[str, Any]] = []
    for turn, w in zip(turns, weights):
        seg = voice_duration * (w / total_w)
        timed.append(
            {
                "start": round(cursor, 3),
                "end": round(cursor + max(seg, 0.05), 3),
                "voice": turn.get("voice") or "",
            }
        )
        cursor += max(seg, 0.05)
    return apply_turn_timings(track, timed)


def normalize_dialogue_track(raw: Any) -> dict[str, Any]:
    base = empty_dialogue_track()
    if not isinstance(raw, dict):
        return base
    mode = str(raw.get("mode") or "single").strip().lower()
    base["mode"] = "multi" if mode == "multi" else "single"
    base["primary_speaker"] = str(raw.get("primary_speaker") or "")
    base["lip_strategy"] = str(raw.get("lip_strategy") or "master")
    try:
        base["total_duration"] = float(raw.get("total_duration") or 0)
    except (TypeError, ValueError):
        base["total_duration"] = 0.0
    try:
        base["cast_matched"] = int(raw.get("cast_matched") or 0)
    except (TypeError, ValueError):
        base["cast_matched"] = 0
    turns: list[dict[str, Any]] = []
    for i, row in enumerate(raw.get("turns") or []):
        if not isinstance(row, dict):
            continue
        try:
            start = float(row.get("start") or 0)
            end = float(row.get("end") or 0)
        except (TypeError, ValueError):
            start, end = 0.0, 0.0
        cname = str(row.get("character_name") or row.get("speaker") or "")
        turns.append(
            {
                "index": int(row.get("index") if row.get("index") is not None else i),
                "speaker": cname,
                "script_speaker": str(row.get("script_speaker") or ""),
                "character_id": str(row.get("character_id") or ""),
                "character_name": cname,
                "text": str(row.get("text") or ""),
                "voice": str(row.get("voice") or ""),
                "voice_label": str(row.get("voice_label") or ""),
                "face_ref": str(row.get("face_ref") or ""),
                "face_ready": bool(row.get("face_ready")),
                "start": round(start, 3),
                "end": round(end, 3),
            }
        )
    base["turns"] = turns
    bindings: list[dict[str, Any]] = []
    for row in raw.get("bindings") or []:
        if not isinstance(row, dict):
            continue
        cname = str(row.get("character_name") or row.get("speaker") or "")
        bindings.append(
            {
                "speaker": cname,
                "character_id": str(row.get("character_id") or ""),
                "character_name": cname,
                "voice": str(row.get("voice") or ""),
                "voice_label": str(row.get("voice_label") or ""),
                "face_ref": str(row.get("face_ref") or ""),
                "face_ready": bool(row.get("face_ready")),
            }
        )
    if not bindings and turns:
        seen: set[str] = set()
        for t in turns:
            key = t.get("character_id") or speaker_key(t["speaker"])
            if key in seen:
                continue
            seen.add(key)
            bindings.append(
                {
                    "speaker": t["speaker"],
                    "character_id": t["character_id"],
                    "character_name": t["character_name"],
                    "voice": t["voice"],
                    "voice_label": t["voice_label"],
                    "face_ref": t.get("face_ref") or "",
                    "face_ready": bool(t.get("face_ready")),
                }
            )
    base["bindings"] = bindings
    if not base["cast_matched"]:
        base["cast_matched"] = sum(1 for b in bindings if b.get("character_id"))
    base["version"] = TRACK_VERSION
    return base


def track_to_voice_turns(track: dict[str, Any]) -> list[dict[str, Any]]:
    """Back-compat shape for older UI fields (voice_turns)."""
    out: list[dict[str, Any]] = []
    for t in (track or {}).get("turns") or []:
        out.append(
            {
                "speaker": t.get("speaker") or "",
                "text": t.get("text") or "",
                "voice": t.get("voice") or "",
                "voice_label": t.get("voice_label") or "",
                "character_id": t.get("character_id") or "",
                "character_name": t.get("character_name") or "",
                "face_ref": t.get("face_ref") or "",
                "face_ready": bool(t.get("face_ready")),
                "start": t.get("start") or 0,
                "end": t.get("end") or 0,
            }
        )
    return out


def spoken_text_from_track(track: dict[str, Any]) -> str:
    return _join_spoken([str(t.get("text") or "") for t in (track or {}).get("turns") or []])


def active_speaker_at(track: dict[str, Any], t: float) -> str:
    """Which speaker owns the dialogue clock at time t (seconds)."""
    turns = (track or {}).get("turns") or []
    if not turns:
        return ""
    for turn in turns:
        start = float(turn.get("start") or 0)
        end = float(turn.get("end") or 0)
        if end <= start:
            continue
        if start <= t < end or (turn is turns[-1] and start <= t <= end + 0.05):
            return str(turn.get("speaker") or "")
    prev = ""
    for turn in turns:
        if float(turn.get("start") or 0) <= t:
            prev = str(turn.get("speaker") or "")
    return prev or str(turns[0].get("speaker") or "")
