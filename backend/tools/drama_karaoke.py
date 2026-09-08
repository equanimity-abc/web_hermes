"""Karaoke ASS subtitle generation (Phase C).

Builds a simple ASS with {\\k} per-character timing so ffmpeg can burn
word/char highlights. Static PNG captions remain the fallback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _ass_escape(text: str) -> str:
    return (
        str(text or "")
        .replace("\\", "\\\\")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("\n", "\\N")
    )


def _cs(seconds: float) -> str:
    """ASS timestamp H:MM:SS.cs"""
    total = max(0.0, float(seconds))
    h = int(total // 3600)
    m = int((total % 3600) // 60)
    s = int(total % 60)
    cs = int(round((total - int(total)) * 100))
    if cs >= 100:
        s += 1
        cs = 0
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def karaoke_tokens(text: str) -> list[str]:
    """Prefer CJK char tokens; otherwise whitespace words."""
    raw = str(text or "").strip()
    if not raw:
        return []
    if any("\u4e00" <= c <= "\u9fff" for c in raw):
        return [c for c in raw.replace(" ", "") if c.strip()]
    return [w for w in raw.split() if w]


def build_karaoke_dialogue(text: str, duration: float) -> str:
    tokens = karaoke_tokens(text)
    if not tokens:
        return ""
    dur = max(0.4, float(duration or 1.0))
    # ASS \\k unit = centiseconds
    per = max(1, int(round((dur * 100) / len(tokens))))
    parts = [f"{{\\k{per}}}{_ass_escape(tok)}" for tok in tokens]
    return "".join(parts)


def build_karaoke_from_turns(turns: list[dict[str, Any]]) -> list[tuple[float, float, str]]:
    """Build (start, end, karaoke_body) rows from TTS-timed dialogue turns."""
    rows: list[tuple[float, float, str]] = []
    for turn in turns or []:
        if not isinstance(turn, dict):
            continue
        text = str(turn.get("text") or "").strip()
        if not text:
            continue
        try:
            start = float(turn.get("start") or 0)
            end = float(turn.get("end") or 0)
        except (TypeError, ValueError):
            start, end = 0.0, 0.0
        dur = max(0.05, end - start) if end > start else 1.0
        body = build_karaoke_dialogue(text, dur)
        if body:
            rows.append((start, start + dur if end <= start else end, body))
    return rows


def write_karaoke_ass(
    dest: Path,
    text: str,
    *,
    duration: float,
    play_res_x: int = 1080,
    play_res_y: int = 1920,
    turns: list[dict[str, Any]] | None = None,
) -> Path | None:
    """Write a minimal ASS karaoke file. Prefer TTS turn timings when provided."""
    turn_rows = build_karaoke_from_turns(turns or [])
    if turn_rows:
        bodies = turn_rows
    else:
        body = build_karaoke_dialogue(text, duration)
        if not body:
            return None
        bodies = [(0.0, max(0.4, float(duration or 1.0)), body)]
    dest.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {play_res_x}\n"
        f"PlayResY: {play_res_y}\n"
        "WrapStyle: 2\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        # Primary=highlight yellow, Secondary=dim white fill before karaoke advances
        "Style: Karaoke,Microsoft YaHei,58,&H005CE5FF,&H00FFFFFF,&H00000000,&H80000000,"
        "0,0,0,0,100,100,0,0,1,3,0,2,60,60,220,1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = [
        f"Dialogue: 0,{_cs(start)},{_cs(end)},Karaoke,,0,0,0,,{body}\n"
        for start, end, body in bodies
    ]
    dest.write_text(header + "".join(lines), encoding="utf-8-sig")
    return dest


def shot_wants_karaoke(models: dict[str, Any] | None, shot: dict[str, Any] | None = None) -> bool:
    sub = {}
    if isinstance(models, dict):
        sub = models.get("subtitle") if isinstance(models.get("subtitle"), dict) else {}
    style = str((shot or {}).get("subtitle_style") or sub.get("style") or "static").strip().lower()
    return style in ("karaoke", "kara", "ass", "k")
