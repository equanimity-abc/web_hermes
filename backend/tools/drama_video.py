"""Local 9:16 episode renderer: shot cards + TTS + ffmpeg.

Used by tiktok_drama action=render_episode. Does not touch agent/loop.py.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import threading
import urllib.parse
from pathlib import Path
from typing import Any, Callable

from config import config
from tools.drama_characters import (
    character_prompt_clause,
    character_seed,
    load_characters,
    normalize_roles,
    primary_voice,
    public_voices,
    resolve_shot_characters,
)
from tools.drama_shots import (
    CANDIDATE_COUNT,
    LAYERS,
    apply_patch,
    candidate_rel,
    clip_list,
    find_candidate,
    find_shot,
    json_rel,
    layers_for_patch,
    load_doc,
    merge_from_parsed,
    next_candidate_ids,
    output_rel,
    parse_layers,
    prune_candidates,
    public_shot,
    save_doc,
    script_rel,
    work_rel,
)
from tools.workspace import resolve_safe

WIDTH = 1080
HEIGHT = 1920
FPS = 25
# Oversized still so pan/zoom has travel — Ken Burns needs extra pixels.
ZOOM_W = 1620
ZOOM_H = 2880
XFADE_SEC = 0.32

_SHOT_HEAD = re.compile(
    r"^###\s*Shot\s+(\d+)\s*(?:\(([^)]*)\))?\s*$",
    re.IGNORECASE,
)
_FIELD = re.compile(r"^-\s*\*{0,2}(画面|字幕|旁白|对白|角色)\*{0,2}\s*[:：]\s*(.*)\s*$")
_POSTPRODUCTION_CUES = (
    "画面切黑",
    "切黑",
    "黑屏",
    "画面淡出",
    "淡出",
    "淡入",
    "转场",
    "硬切",
    "叠化",
    "切至",
    "切到",
    "切回",
)
_CANDIDATE_VARIATIONS = (
    "主分镜构图，画面均衡",
    "备用机位角度，人物站位略有变化",
    "构图略宽，环境细节更多",
    "构图略紧，突出面部与手部",
)


def _candidate_index(cid: str, fallback: int = 0) -> int:
    m = re.match(r"c(\d+)$", str(cid or "").strip())
    if not m:
        return max(0, int(fallback))
    try:
        return max(0, int(m.group(1)))
    except ValueError:
        return max(0, int(fallback))


def _candidate_seed(base_seed: int, cid: str, batch_index: int = 0) -> int:
    cand_idx = _candidate_index(cid, batch_index + 1)
    return (int(base_seed) + cand_idx * 9973 + int(batch_index) * 97) & 0x7FFFFFFF


def _candidate_prompt(prompt: str, cid: str, batch_index: int = 0) -> str:
    cand_idx = _candidate_index(cid, batch_index + 1)
    variation = _CANDIDATE_VARIATIONS[(cand_idx - 1) % len(_CANDIDATE_VARIATIONS)]
    return f"{prompt}，{variation}，候选方案{cand_idx}"


def _scene_text_for_prompt(raw: str) -> str:
    """Strip post-production / editing directions that are not drawable keyframes."""
    scene = str(raw or "").strip()
    if not scene:
        return "现代都市电影感场景"
    for phrase in _POSTPRODUCTION_CUES:
        scene = scene.replace(phrase, "")
    scene = re.sub(r"[，。；;]+$", "", scene.strip())
    return scene or "现代都市电影感场景"
_RANGE = re.compile(r"(\d+(?:\.\d+)?)\s*[-–~]\s*(\d+(?:\.\d+)?)")
_QUOTE = re.compile(r"[「『“\"]([^」』”\"]+)[」』”\"]")
# 林薇薇（夸张地）: / 林晚: / 【旁白】：
_SPEAKER_PREFIX = re.compile(
    r"^(?:【[^】]{1,12}】|\[[^\]]{1,12}\])?"
    r"[^:：\s「『“\"]{1,16}"
    r"(?:\s*[（(][^）)]{0,40}[）)])?"
    r"\s*[:：]\s*"
)
_STAGE_PAREN = re.compile(r"[（(][^）)]{0,24}[）)]")
# 林晚（低声）: “……”
_NAMED_QUOTE = re.compile(
    r"(?P<name>[^:：\s「『“\"（(【\[]{1,16})"
    r"(?:\s*[（(][^）)]{0,40}[）)])?"
    r"\s*[:：]\s*[「『“\"](?P<text>[^」』”\"]+)[」』”\"]"
)
# 林晚: 没关系。 / 林晚（低声）: 没关系。
_NAMED_LINE = re.compile(
    r"^(?P<name>[^:：\s「『“\"（(【\[]{1,16})"
    r"(?:\s*[（(][^）)]{0,40}[）)])?"
    r"\s*[:：]\s*(?P<text>.+?)\s*$"
)

_FONT_CANDIDATES = [
    Path(r"C:\Windows\Fonts\msyh.ttc"),
    Path(r"C:\Windows\Fonts\msyhbd.ttc"),
    Path(r"C:\Windows\Fonts\simhei.ttf"),
    Path(r"C:\Windows\Fonts\Deng.ttf"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    Path("/System/Library/Fonts/PingFang.ttc"),
]


def _ffmpeg_bin() -> str:
    return os.getenv("FFMPEG_BIN", "ffmpeg")


def _tts_voice() -> str:
    return os.getenv("TTS_VOICE", "zh-CN-YunxiNeural")


def ffmpeg_available() -> bool:
    return shutil.which(_ffmpeg_bin()) is not None


def parse_episode_markdown(text: str) -> dict[str, Any]:
    """Parse save_episode markdown into title / hook / shots."""
    lines = str(text or "").replace("\r\n", "\n").split("\n")
    title = ""
    meta: dict[str, str] = {}
    shots: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for raw in lines:
        line = raw.rstrip()
        if line.startswith("# ") and not title:
            title = line[2:].strip()
            continue
        m_meta = re.match(r"^-\s*\*{0,2}(时长|钩子|悬念)\*{0,2}\s*[:：]\s*(.*)$", line)
        if m_meta and current is None:
            meta[m_meta.group(1)] = m_meta.group(2).strip()
            continue
        m_shot = _SHOT_HEAD.match(line)
        if m_shot:
            if current:
                shots.append(current)
            idx = int(m_shot.group(1))
            timing = (m_shot.group(2) or "").strip()
            start, end, duration = _parse_timing(timing)
            current = {
                "n": idx,
                "timing": timing,
                "start": start,
                "end": end,
                "duration": duration,
                "画面": "",
                "字幕": "",
                "旁白": "",
                "角色": "",
            }
            continue
        if current is None:
            continue
        m_field = _FIELD.match(line)
        if m_field:
            key = m_field.group(1)
            val = m_field.group(2).strip()
            # keep legacy 对白 on the dict so migrate_shot_script_fields can remap
            current[key] = val

    if current:
        shots.append(current)

    from tools.drama_shots import migrate_shot_script_fields

    shots = [migrate_shot_script_fields(s) for s in shots]
    shots.sort(key=lambda s: int(s["n"]))
    return {"title": title, "meta": meta, "shots": shots, "count": len(shots)}


def patch_shot_in_markdown(text: str, shot_n: int, patch: dict[str, Any]) -> str:
    """Write 画面/字幕/旁白/角色 and Shot timing header back into episode markdown."""
    keys = ("画面", "字幕", "旁白", "角色")
    fields: dict[str, str] = {}
    patch = dict(patch or {})
    # legacy alias
    if "对白" in patch and "字幕" not in patch:
        patch["字幕"] = patch.pop("对白")
    for key, value in patch.items():
        if key not in keys or value is None:
            continue
        if key == "角色":
            fields[key] = "、".join(normalize_roles(value))
        else:
            fields[key] = str(value)

    timing_label = ""
    if patch.get("timing") is not None and str(patch.get("timing") or "").strip():
        timing_label = str(patch.get("timing") or "").strip()
        if not timing_label.endswith("s"):
            timing_label = f"{timing_label}s"
    elif any(patch.get(k) is not None for k in ("duration", "start", "end")):
        try:
            start = float(patch["start"]) if patch.get("start") is not None else None
            end = float(patch["end"]) if patch.get("end") is not None else None
            duration = float(patch["duration"]) if patch.get("duration") is not None else None
        except (TypeError, ValueError):
            start = end = duration = None
        if start is not None and end is not None:
            from tools.drama_shots import format_timing_range

            timing_label = format_timing_range(start, end)
        elif start is not None and duration is not None:
            from tools.drama_shots import format_timing_range

            timing_label = format_timing_range(start, start + duration)

    if not fields and not timing_label:
        return text

    lines = str(text or "").replace("\r\n", "\n").split("\n")
    in_target = False
    pending = dict(fields)
    out: list[str] = []

    def flush_pending() -> None:
        for key in keys:
            if key in pending:
                out.append(f"- {key}: {pending.pop(key)}")

    for line in lines:
        stripped = line.rstrip()
        m_shot = _SHOT_HEAD.match(stripped)
        if m_shot:
            if in_target:
                flush_pending()
            in_target = int(m_shot.group(1)) == int(shot_n)
            if in_target and timing_label:
                out.append(f"### Shot {int(shot_n)} ({timing_label})")
            else:
                out.append(line)
            continue
        if in_target:
            m_field = _FIELD.match(stripped)
            if m_field:
                key = m_field.group(1)
                # rewrite legacy 对白 line as 字幕 when patching 字幕
                if key == "对白" and "字幕" in fields:
                    out.append(f"- 字幕: {fields['字幕']}")
                    pending.pop("字幕", None)
                    continue
                if key in fields:
                    out.append(f"- {key}: {fields[key]}")
                    pending.pop(key, None)
                    continue
        out.append(line)
    if in_target:
        flush_pending()
    return "\n".join(out)


def patch_episode_meta_duration(text: str, total_seconds: float) -> str:
    """Update top-level `- 时长: NNs` to match the cascaded timeline."""
    from tools.drama_shots import TIMING_DECIMALS, round_timing

    try:
        total = round_timing(total_seconds or 0)
    except (TypeError, ValueError):
        return text
    if total <= 0:
        return text
    label = (
        f"{int(total)}s"
        if abs(total - round(total)) < 10 ** (-(TIMING_DECIMALS + 1))
        else f"{total:.{TIMING_DECIMALS}f}".rstrip("0").rstrip(".") + "s"
    )
    lines = str(text or "").replace("\r\n", "\n").split("\n")
    out: list[str] = []
    replaced = False
    for line in lines:
        m = re.match(r"^(-\s*\*{0,2}时长\*{0,2}\s*[:：]\s*).*$", line)
        if m and not replaced:
            out.append(f"{m.group(1)}{label}")
            replaced = True
        else:
            out.append(line)
    return "\n".join(out)


def restore_frozen_shots_markdown(markdown: str, doc: dict[str, Any]) -> str:
    """Write frozen shot fields back so the script matches shots.json."""
    text = str(markdown or "")
    for shot in doc.get("shots") or []:
        if "shot" not in (shot.get("locked") or []):
            continue
        text = patch_shot_in_markdown(
            text,
            int(shot["n"]),
            {
                "画面": shot.get("画面") or "",
                "字幕": shot.get("字幕") or "",
                "旁白": shot.get("旁白") or "",
                "角色": shot.get("角色") or [],
            },
        )
    return text


def _parse_timing(timing: str) -> tuple[float, float, float]:
    from tools.drama_shots import round_timing

    m = _RANGE.search(timing or "")
    if not m:
        return 0.0, 5.0, 5.0
    start = round_timing(m.group(1))
    end = round_timing(m.group(2))
    if end <= start:
        end = round_timing(start + 3.0)
    return start, end, round_timing(end - start)


def spoken_text(dialogue: str, subtitle: str = "") -> str:
    """Strip script stagecraft; keep spoken lines for TTS.

    字幕（台词）→ 配音；旁白是画外说明，默认不拿来念。
    """
    text = (dialogue or "").strip()
    if text:
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
        if cleaned:
            return cleaned
    return ""


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


def _speaker_names_match(a: str, b: str) -> bool:
    x = re.sub(r"[\s【】\[\]]+", "", str(a or "").strip())
    y = re.sub(r"[\s【】\[\]]+", "", str(b or "").strip())
    if not x or not y:
        return False
    if x == y:
        return True
    # 林薇 ↔ 林薇薇
    return x.startswith(y) or y.startswith(x)


def parse_dialogue_segments(dialogue: str) -> list[tuple[str, str]]:
    """Return [(speaker_name, spoken_line), ...] from script-style 对白."""
    text = (dialogue or "").strip()
    if not text:
        return []
    segs = [(m.group("name").strip(), m.group("text").strip()) for m in _NAMED_QUOTE.finditer(text)]
    segs = [(n, t) for n, t in segs if n and t]
    if segs:
        return segs
    # Line-based: 林若曦: 你好。\n林慧兰: 你是谁？
    line_segs: list[tuple[str, str]] = []
    for raw_line in re.split(r"[\n\r]+", text):
        line = raw_line.strip()
        if not line:
            continue
        m = _NAMED_LINE.match(line)
        if not m:
            continue
        name = m.group("name").strip()
        spoken = m.group("text").strip().strip("「『“”」』\"'")
        spoken = _STAGE_PAREN.sub("", spoken).strip()
        if name and spoken:
            line_segs.append((name, spoken))
    if line_segs:
        return line_segs
    plain = spoken_text(text)
    return [("", plain)] if plain else []


def voice_id_for_speaker(
    speaker: str,
    cast: list[dict[str, Any]],
    *,
    slug: str | None = None,
    fallback: str | None = None,
) -> str:
    """Resolve TTS voice from a speaker name against character cards."""
    name = str(speaker or "").strip()
    if name and cast:
        for char in cast:
            cname = str(char.get("name") or "")
            cid = str(char.get("id") or "")
            aliases = char.get("aliases") or []
            if not isinstance(aliases, list):
                aliases = []
            if (
                _speaker_names_match(name, cname)
                or _speaker_names_match(name, cid)
                or any(_speaker_names_match(name, a) for a in aliases)
            ):
                voice = str(char.get("voice") or "").strip()
                if voice:
                    return voice
    if fallback:
        return fallback
    return primary_voice(cast, slug=slug) if cast else _tts_voice()


def spoken_text_for_shot(shot: dict[str, Any]) -> str:
    """TTS / caption text. Multi-named dialogue: join all lines; else prefer speaker."""
    dialogue = str(shot.get("字幕") or shot.get("对白") or "")
    speaker = str(shot.get("speaker") or "").strip()
    segs = parse_dialogue_segments(dialogue)
    if not segs:
        return ""
    named = [(n, t) for n, t in segs if n]
    # Two+ named speakers in one shot → speak every turn (各自音色由 turns 处理)
    if len({n for n, _ in named}) >= 2:
        return _join_spoken([t for _, t in named])
    if speaker:
        matched = [t for n, t in segs if n and _speaker_names_match(n, speaker)]
        if matched:
            return _join_spoken(matched)
    if len(segs) == 1:
        return segs[0][1]
    if segs[0][0]:
        first = segs[0][0]
        return _join_spoken([t for n, t in segs if n == first])
    return _join_spoken([t for _, t in segs])


def voice_id_for_shot(shot: dict[str, Any], cast: list[dict[str, Any]], *, slug: str | None = None) -> str:
    """Resolve TTS voice: shot.voice → speaker's character card → cast primary."""
    explicit = str(shot.get("voice") or "").strip()
    if explicit:
        return explicit
    speaker = str(shot.get("speaker") or "").strip()
    if speaker:
        return voice_id_for_speaker(speaker, cast, slug=slug)
    return primary_voice(cast, slug=slug) if cast else _tts_voice()


def dialogue_turns_for_shot(
    shot: dict[str, Any],
    cast: list[dict[str, Any]],
    *,
    slug: str | None = None,
) -> list[dict[str, str]]:
    """
    Build ordered TTS turns for a shot.

    Multi-speaker 字幕 (two+ named lines) → one turn per line with that role's voice.
    Otherwise → single turn using spoken_text_for_shot + voice_id_for_shot.
    """
    dialogue = str(shot.get("字幕") or shot.get("对白") or "")
    segs = parse_dialogue_segments(dialogue)
    named = [(n, t) for n, t in segs if n and t]
    distinct = []
    seen_names: set[str] = set()
    for n, _ in named:
        key = re.sub(r"[\s【】\[\]]+", "", n)
        if key in seen_names:
            continue
        seen_names.add(key)
        distinct.append(n)

    fallback = voice_id_for_shot(shot, cast, slug=slug)
    if len(distinct) >= 2:
        turns: list[dict[str, str]] = []
        for name, text in named:
            turns.append(
                {
                    "speaker": name,
                    "text": text,
                    "voice": voice_id_for_speaker(name, cast, slug=slug, fallback=fallback),
                }
            )
        return turns

    speech = spoken_text_for_shot(shot)
    if not speech:
        return []
    speaker = str(shot.get("speaker") or "").strip()
    if not speaker and named:
        speaker = named[0][0]
    return [{"speaker": speaker, "text": speech, "voice": fallback}]


def shot_voice_speakers(
    shot: dict[str, Any],
    cast: list[dict[str, Any]],
    *,
    slug: str | None = None,
) -> list[dict[str, str]]:
    """Unique speakers in this shot with bound voice ids (for UI display)."""
    turns = dialogue_turns_for_shot(shot, cast, slug=slug)
    labels = {row["id"]: row["label"] for row in public_voices(slug)}
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for turn in turns:
        name = str(turn.get("speaker") or "").strip() or "（未命名）"
        key = re.sub(r"[\s【】\[\]]+", "", name)
        if key in seen:
            continue
        seen.add(key)
        vid = str(turn.get("voice") or "").strip()
        out.append(
            {
                "name": name,
                "voice": vid,
                "voice_label": labels.get(vid) or vid or "—",
            }
        )
    return out


def clean_subtitle(subtitle: str) -> str:
    """Strip speaker tags / stage parens from subtitle; keep narrative lines."""
    text = (subtitle or "").strip()
    if not text:
        return ""
    cleaned = _SPEAKER_PREFIX.sub("", text).strip()
    cleaned = _STAGE_PAREN.sub("", cleaned).strip()
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ：:，,")
    return cleaned or text


_MONOLOGUE_TAG = re.compile(r"(?:【\s*)?(内心独白|心声|OS)(?:\s*】)?\s*[:：]?", re.IGNORECASE)


def subtitle_display_text(subtitle: str) -> str:
    """旁白文案：清洗后去掉【内心独白】等标签。"""
    text = clean_subtitle(subtitle)
    text = _MONOLOGUE_TAG.sub("", text).strip(" ：:，,")
    return text.strip()


def dialogue_caption_text(shot: dict[str, Any]) -> str:
    """底部台词字幕：与配音同源的清洗文案。"""
    return spoken_text_for_shot(shot) or clean_subtitle(str(shot.get("字幕") or ""))


def _find_font() -> Path:
    for path in _FONT_CANDIDATES:
        if path.is_file():
            return path
    raise FileNotFoundError("未找到中文字体（需要微软雅黑 / 黑体等）")


def _load_font(size: int):
    from PIL import ImageFont

    font_path = _find_font()
    try:
        return ImageFont.truetype(str(font_path), size=size, index=0)
    except OSError:
        return ImageFont.truetype(str(font_path), size=size)


def _wrap(draw, text: str, font, max_width: int) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    lines: list[str] = []
    for para in text.split("\n"):
        line = ""
        for ch in para:
            trial = line + ch
            if draw.textlength(trial, font=font) <= max_width:
                line = trial
            else:
                if line:
                    lines.append(line)
                line = ch
        lines.append(line)
    return lines


def _scene_prompt(
    title: str,
    shot: dict[str, Any],
    characters: list[dict[str, Any]] | None = None,
    *,
    slug: str = "",
) -> str:
    scene = _scene_text_for_prompt(shot.get("画面") or "")
    style = _camera_style(shot)
    kinetic = {
        "punch_in": "动态姿态，隐含运动感，衣摆飘动",
        "punch_shake": "激烈动作，飞溅碎片，冲击瞬间，戏剧性角度",
        "pan_right": "宽幅移动场景，人物行进中，拖影动感",
        "pan_left": "宽幅追逐场景，尘土与速度线",
        "rise": "低角度仰拍，高耸建筑，云层涌动",
        "fall": "高角度俯冲，地面急速靠近",
        "pull_out": "宏大定场镜头，开阔景致，渺小人影",
    }.get(style, "电影感调度，鲜明剪影")
    slug = slug or str(shot.get("slug") or "")
    episode = int(shot.get("_episode") or 0) or None
    char_clause = character_prompt_clause(characters or [], slug=slug)
    style_clause = ""
    if slug:
        from tools.drama_styles import style_prompt_clause

        style_clause = style_prompt_clause(slug, shot, episode=episode)
    bits = [
        "竖屏9:16竖屏短剧关键帧",
        title or "短剧",
        scene,
        char_clause,
        kinetic,
    ]
    if style_clause:
        bits.append(style_clause)
    bits.append(
        "现代都市条漫插画，戏剧性轮廓光，细节丰富，"
        "画面中人物清晰可见，非空镜非黑屏，无文字、无字幕、无水印、无界面"
    )
    return ", ".join(b for b in bits if b)


def _camera_style(shot: dict[str, Any]) -> str:
    """Pick a visible camera move from shot text — not a tiny Ken Burns."""
    scene = shot.get("画面") or ""
    n = int(shot.get("n") or 1)
    # Avoid false positives: 打来/打算/打扮/打开 等日常用语不应触发打斗运镜。
    scene_for_action = scene
    for phrase in ("打来", "打算", "打扮", "打开", "打电话", "打招呼", "拍打", "打字", "打印"):
        scene_for_action = scene_for_action.replace(phrase, "")
    if re.search(r"(打架|打斗|殴打|棒|怒|砸|爆炸|劈|战场|挥拳|一脚|一拳)", scene_for_action):
        return "punch_shake"
    if any(k in scene for k in ("冲", "追", "跑", "逃", "飞", "射")):
        return "pan_right" if n % 2 else "pan_left"
    if any(k in scene for k in ("天", "宫", "云", "升", "凌空")):
        return "rise"
    if any(k in scene for k in ("坠", "落", "俯冲", "砸向")):
        return "fall"
    if any(k in scene for k in ("远", "全景", "俯瞰", "建立")):
        return "pull_out"
    if any(k in scene for k in ("近", "特写", "脸", "眼")):
        return "punch_in"
    return ("punch_in", "pan_right", "rise", "pull_out", "pan_left")[(n - 1) % 5]


def _transition_name(style: str, index: int) -> str:
    if style == "punch_shake":
        return "wipeleft"
    if style in ("pan_right", "pan_left"):
        return "slideleft" if style == "pan_right" else "slideright"
    if style == "rise":
        return "slidedown"
    if style == "fall":
        return "slideup"
    if index % 3 == 0:
        return "fadeblack"
    return "fade"


def _fit_cover(img, width: int, height: int):
    from PIL import Image

    src_w, src_h = img.size
    target_ratio = width / height
    src_ratio = src_w / max(src_h, 1)
    if src_ratio > target_ratio:
        new_w = max(int(src_h * target_ratio), 1)
        left = max((src_w - new_w) // 2, 0)
        img = img.crop((left, 0, left + new_w, src_h))
    else:
        new_h = max(int(src_w / target_ratio), 1)
        top = max((src_h - new_h) // 2, 0)
        img = img.crop((0, top, src_w, top + new_h))
    return img.resize((width, height), Image.Resampling.LANCZOS)


def _trim_letterbox(img, *, tolerance: int = 22, min_strip: int = 3):
    """Crop uniform black/white/gray margins from AI-generated images."""
    rgb = img.convert("RGB")
    w, h = rgb.size
    if w < 16 or h < 16:
        return rgb

    px = rgb.load()
    corners = (px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1])
    bg = tuple(sum(c[i] for c in corners) // 4 for i in range(3))

    def is_bg(x: int, y: int) -> bool:
        p = px[x, y]
        return all(abs(int(p[i]) - int(bg[i])) <= tolerance for i in range(3))

    def row_is_bg(y: int) -> bool:
        step = max(1, w // 48)
        return all(is_bg(x, y) for x in range(0, w, step))

    def col_is_bg(x: int) -> bool:
        step = max(1, h // 48)
        return all(is_bg(x, y) for y in range(0, h, step))

    top = 0
    while top < h - min_strip and row_is_bg(top):
        top += 1
    bottom = h
    while bottom > top + min_strip and row_is_bg(bottom - 1):
        bottom -= 1
    left = 0
    while left < w - min_strip and col_is_bg(left):
        left += 1
    right = w
    while right > left + min_strip and col_is_bg(right - 1):
        right -= 1

    if right <= left or bottom <= top:
        return rgb
    if (right - left) >= int(w * 0.98) and (bottom - top) >= int(h * 0.98):
        return rgb
    return rgb.crop((left, top, right, bottom))


def _prepare_frame(img, width: int, height: int):
    return _fit_cover(_trim_letterbox(img), width, height)


def _draw_fallback_scene(
    shot: dict[str, Any],
    dest: Path,
    characters: list[dict[str, Any]] | None = None,
    *,
    seed: int = 0,
) -> None:
    """Atmospheric still if image gen fails — not a subtitle document."""
    from PIL import Image, ImageDraw, ImageFilter

    img = Image.new("RGB", (ZOOM_W, ZOOM_H), "#12080c")
    mood = shot.get("画面") or ""
    if any(k in mood for k in ("怒", "打", "棒", "翻", "战")):
        colors = [(48, 8, 8), (160, 40, 18), (220, 140, 40)]
    elif any(k in mood for k in ("天", "宫", "云", "宴", "桃")):
        colors = [(18, 22, 64), (80, 50, 140), (220, 170, 70)]
    else:
        colors = [(10, 12, 28), (40, 28, 70), (180, 120, 50)]
    shift = (int(seed) % 11 - 5) * 12
    colors = [
        tuple(max(0, min(255, c + shift + i * 8)) for c in rgb)
        for i, rgb in enumerate(colors)
    ]

    for i, color in enumerate(colors):
        layer = Image.new("RGB", (ZOOM_W, ZOOM_H), color)
        mask = Image.new("L", (ZOOM_W, ZOOM_H), 0)
        md = ImageDraw.Draw(mask)
        cy = int(ZOOM_H * (0.22 + ((seed + i * 3) % 5) * 0.08 + i * 0.18))
        md.ellipse((-400, cy - 500, ZOOM_W + 400, cy + 500), fill=180 - i * 40)
        mask = mask.filter(ImageFilter.GaussianBlur(80))
        img = Image.composite(layer, img, mask)

    draw = ImageDraw.Draw(img)
    ox = (int(seed) % 7 - 3) * 30
    draw.ellipse((ZOOM_W // 2 - 90 + ox, 520, ZOOM_W // 2 + 90 + ox, 980), outline="#d4a017", width=8)
    _paste_character_refs(img, characters or [])
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "PNG")


def _paste_character_refs(img, characters: list[dict[str, Any]]) -> None:
    """Stamp locked/available 定妆图 onto fallback stills so consecutive shots share a face."""
    from PIL import Image

    refs: list[Path] = []
    for char in characters[:2]:
        rel = str(char.get("ref") or "")
        if not rel:
            continue
        try:
            path = resolve_safe(rel)
        except ValueError:
            continue
        if path.is_file() and path.stat().st_size > 0:
            refs.append(path)
    if not refs:
        return
    slot_w = 720 if len(refs) == 1 else 540
    slot_h = 960
    gap = 40
    total_w = len(refs) * slot_w + (len(refs) - 1) * gap
    x0 = max((ZOOM_W - total_w) // 2, 40)
    y0 = ZOOM_H - slot_h - 280
    for i, path in enumerate(refs):
        try:
            portrait = Image.open(path).convert("RGB")
        except OSError:
            continue
        portrait = _fit_cover(portrait, slot_w, slot_h)
        img.paste(portrait, (x0 + i * (slot_w + gap), y0))


def _image_provider_chain(
    primary: str,
    shot: dict[str, Any] | None,
    *,
    refs: tuple[str, ...] = (),
) -> list[str]:
    """Ordered image providers to try; character_ref gets DashScope/Kling fallbacks."""
    from tools.providers import registry

    skip = frozenset({"", "none", "off", "mock"})
    chain: list[str] = []

    def add(pid: str) -> None:
        p = str(pid or "").strip().lower()
        if not p or p in skip or p in chain:
            return
        if registry.has("image", p):
            chain.append(p)

    if refs:
        # Locked character refs need img2img-capable providers (Kling uploads ref PNGs).
        add("kling-image")
        add("kling")
        add("jimeng")
    add(primary)
    if str((shot or {}).get("kind") or "") == "character_ref":
        from tools.drama_styles import default_character_ref_image_route

        for key in ("provider",):
            add(str(default_character_ref_image_route().get(key) or ""))
        add("kling-image")
        add("kling")
        add("wanx")
        add("dashscope")
    else:
        fb = (config.IMAGE_GEN_PROVIDER or "pollinations").strip().lower()
        if not refs:
            add(fb)
            if fb != "pollinations":
                add("pollinations")
    return chain


def _generate_scene_image(
    prompt: str,
    dest: Path,
    *,
    seed: int,
    refs: tuple[str, ...] = (),
    slug: str = "",
    shot: dict[str, Any] | None = None,
    episode: int | None = None,
    width: int | None = None,
    height: int | None = None,
) -> bool:
    """Generate one scene via the image route table (P0-1).

    The provider comes from image_route(slug, shot) — the same source the
    workbench estimate reads. Unregistered provider ids (e.g. jimeng until a
    real adapter lands) degrade to the global default instead of failing.
    """
    provider = (config.IMAGE_GEN_PROVIDER or "pollinations").strip().lower()
    if slug:
        from tools.drama_styles import image_route

        route = image_route(slug, shot or {}, episode=episode)
        route_provider = str(route.get("provider") or "").strip().lower()
        if route_provider:
            provider = route_provider
    if provider in ("", "none", "off"):
        return False

    from tools.providers import registry

    gen_w = int(width or ZOOM_W)
    gen_h = int(height or ZOOM_H)
    for pid in _image_provider_chain(provider, shot, refs=refs):
        ok = registry.dispatch(
            "image",
            pid,
            prompt,
            dest,
            seed=seed,
            width=gen_w,
            height=gen_h,
            refs=tuple(refs),
            slug=slug,
            shot=shot,
        )
        if ok:
            return True
    return False


def generate_character_portrait(slug: str, char: dict[str, Any], *, dest_rel: str | None = None) -> str | None:
    """文生图出定妆图（角色三视图 / 物品 / 场景参考）。返回新的 ref 相对路径，失败返回 None."""
    import zlib

    from tools.drama_characters import build_asset_ref_prompt, character_ref_shot, ref_canvas_size, ref_rel

    cid = str(char.get("id") or "")
    prompt = build_asset_ref_prompt(char)
    out_rel = str(dest_rel or ref_rel(slug, cid)).replace("\\", "/")
    dest = resolve_safe(out_rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    seed = zlib.crc32(f"{slug}:{cid}:{out_rel}".encode()) & 0x7FFFFFFF
    gen_w, gen_h = ref_canvas_size(char)
    ok = _generate_scene_image(
        prompt, dest, seed=seed, slug=slug, shot=character_ref_shot(char), width=gen_w, height=gen_h
    )
    if not ok or not (dest.is_file() and dest.stat().st_size > 1000):
        return None
    return out_rel


def _write_scene_png(data: bytes, dest: Path) -> None:
    from io import BytesIO

    from PIL import Image

    img = Image.open(BytesIO(data)).convert("RGB")
    img = _prepare_frame(img, ZOOM_W, ZOOM_H)
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "PNG")


def apply_candidate_to_scene(shot: dict[str, Any], cand: dict[str, Any]) -> None:
    src = resolve_safe(str(cand.get("path") or ""))
    dest = _path_for(shot, "scene")
    if not src.is_file():
        raise FileNotFoundError(f"候选图不存在：{cand.get('path')}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    shot["chosen"] = str(cand.get("id") or "")
    shot["scene_source"] = str(cand.get("source") or shot.get("scene_source") or "ai")
    dirty = [layer for layer in (shot.get("dirty") or []) if layer != "scene"]
    if "clip" not in dirty and "clip" not in (shot.get("locked") or []):
        dirty.append("clip")
    shot["dirty"] = dirty
    shot["status"] = "dirty" if dirty else shot.get("status") or "rendered"


def generate_shot_candidates(
    slug: str,
    episode: int,
    shot: dict[str, Any],
    *,
    title: str = "",
    count: int = CANDIDATE_COUNT,
) -> list[dict[str, Any]]:
    """Fill the candidate wall. Does not overwrite a locked scene.png."""
    count = max(1, min(int(count or CANDIDATE_COUNT), 4))
    locked = set(shot.get("locked") or [])
    cards = load_characters(slug)
    cast = resolve_shot_characters(shot, cards)
    shot["camera"] = shot.get("camera") or _camera_style(shot)
    shot["_episode"] = episode
    prompt = _scene_prompt(title, shot, cast, slug=slug)
    shot.pop("_episode", None)
    shot["prompt"] = prompt
    base_seed = character_seed(slug, cast, int(shot.get("n") or 1))
    ids = next_candidate_ids(shot, count)
    created: list[dict[str, Any]] = []
    used_ai = False
    n = int(shot.get("n") or 0)

    # R4: feed locked character reference sheets into the image provider.
    from tools.drama_qc import locked_refs_for_shot

    refs = tuple(locked_refs_for_shot(slug, shot))

    from tools.drama_retry import retry_call

    def _render_one(i: int, cid: str) -> dict[str, Any]:
        """Generate one candidate (thread-safe; writes its own dest file)."""
        seed = _candidate_seed(base_seed, cid, i)
        varied_prompt = _candidate_prompt(prompt, cid, i)
        rel = candidate_rel(slug, episode, n, cid)
        dest = resolve_safe(rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        ai_ok = bool(
            retry_call(
                _generate_scene_image,
                varied_prompt,
                dest,
                seed=seed,
                refs=refs,
                slug=slug,
                shot=shot,
                episode=episode,
            )
        )
        if not ai_ok:
            _draw_fallback_scene(shot, dest, cast, seed=seed)
        return {"id": cid, "path": rel, "source": "ai" if ai_ok else "fallback", "seed": seed, "ai": ai_ok}

    # S4: 候选墙并发出图，受 DRAMA_MAX_WORKERS 约束（保留 ids 顺序）。
    from concurrent.futures import ThreadPoolExecutor

    workers = max(1, min(int(getattr(config, "DRAMA_MAX_WORKERS", 2) or 2), count))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        rendered = list(executor.map(_render_one, range(len(ids)), ids))
    for rec in rendered:
        created.append({"id": rec["id"], "path": rec["path"], "source": rec["source"], "seed": rec["seed"]})
        used_ai = used_ai or rec["ai"]
    shot["candidates"] = list(shot.get("candidates") or []) + created
    prune_candidates(shot)
    if "shot" not in locked and "scene" not in locked and created:
        apply_candidate_to_scene(shot, created[0])
        if used_ai:
            shot["scene_source"] = "ai"
        shot["dirty"] = [layer for layer in (shot.get("dirty") or []) if layer != "scene"]
        if "clip" not in (shot.get("dirty") or []) and "clip" not in locked:
            shot.setdefault("dirty", []).append("clip")
            shot["status"] = "dirty"
    return created


def choose_shot_candidate(shot: dict[str, Any], cid: str) -> dict[str, Any]:
    if "shot" in (shot.get("locked") or []):
        raise ValueError("整镜已锁定，不能换图")
    cand = find_candidate(shot, cid)
    if cand is None:
        raise ValueError(f"找不到候选 {cid}")
    apply_candidate_to_scene(shot, cand)
    return cand


def upload_shot_candidate(slug: str, episode: int, shot: dict[str, Any], data: bytes) -> dict[str, Any]:
    if "shot" in (shot.get("locked") or []):
        raise ValueError("整镜已锁定，不能换图")
    if not data:
        raise ValueError("图片不能为空")
    cid = next_candidate_ids(shot, 1)[0]
    rel = candidate_rel(slug, episode, int(shot.get("n") or 0), cid)
    dest = resolve_safe(rel)
    try:
        _write_scene_png(data, dest)
    except Exception as e:
        raise ValueError("无法读取图片") from e
    rec = {"id": cid, "path": rel, "source": "upload", "seed": 0}
    shot["candidates"] = list(shot.get("candidates") or []) + [rec]
    prune_candidates(shot)
    apply_candidate_to_scene(shot, rec)
    return rec


def _draw_subtitle_overlay(shot: dict[str, Any], dest: Path) -> None:
    """Burn-in 文案：旁白左上角竖排；字幕（台词）底部横排。"""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # 旁白 = 画外说明
    _draw_narration_vertical(draw, subtitle_display_text(shot.get("旁白") or ""))
    # 字幕 = 台词
    _draw_dialogue_caption(draw, dialogue_caption_text(shot))
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "PNG")


# 样式单一入口：改这里全部镜头同步
_DIALOGUE_FONT = 58
_NARRATION_FONT = max(24, int(round(_DIALOGUE_FONT * 2 / 3)))  # ≈39


def _draw_dialogue_caption(draw, text: str) -> None:
    """底部横排台词字幕。"""
    if not (text or "").strip():
        return
    font_sub = _load_font(_DIALOGUE_FONT)
    max_w = WIDTH - 120
    y = HEIGHT - 280
    for line in _wrap(draw, text, font_sub, max_w)[:3]:
        w = draw.textlength(line, font=font_sub)
        x = (WIDTH - w) / 2
        draw.text((x + 3, y + 3), line, font=font_sub, fill=(0, 0, 0, 200))
        draw.text((x, y), line, font=font_sub, fill=(255, 229, 102, 255))
        y += 72


def _draw_narration_vertical(draw, text: str) -> None:
    """左上角竖排旁白：一字一行，严格落在 9:16 安全区内。"""
    chars = [c for c in (text or "").replace("\n", "").replace(" ", "") if c]
    if not chars:
        return
    font = _load_font(_NARRATION_FONT)
    step = max(int(_NARRATION_FONT * 1.18), _NARRATION_FONT + 6)
    margin_x = 56
    margin_top = 72
    margin_bottom = 220
    max_x = int(WIDTH * 0.28)
    max_y = HEIGHT - margin_bottom

    col_w = _NARRATION_FONT + 16
    x = margin_x
    y = margin_top
    for ch in chars:
        if y + step > max_y:
            x += col_w
            y = margin_top
            if x + col_w > max_x:
                break
        try:
            draw.text((x + 2, y + 2), ch, font=font, fill=(0, 0, 0, 200), anchor="lt")
            draw.text((x, y), ch, font=font, fill=(255, 229, 102, 255), anchor="lt")
        except TypeError:
            draw.text((x + 2, y + 2), ch, font=font, fill=(0, 0, 0, 200))
            draw.text((x, y), ch, font=font, fill=(255, 229, 102, 255))
        y += step


def _motion_expr(shot: dict[str, Any], frames: int) -> str:
    """Large travel zoom/pan — must be obvious on a phone screen."""
    style = _camera_style(shot)
    n = max(frames - 1, 1)
    # zoompan x/y must stay inside [0, iw-iw/zoom]
    z_in = f"min(1.05+0.75*on/{n},1.80)"
    z_out = f"max(1.80-0.75*on/{n},1.05)"
    z_hold = "1.45"
    x_ctr = "iw/2-(iw/zoom/2)"
    y_ctr = "ih/2-(ih/zoom/2)"
    x_max = f"max(0,(iw-iw/zoom)*on/{n})"
    x_min = f"max(0,(iw-iw/zoom)*(1-on/{n}))"
    y_up = f"max(0,(ih-ih/zoom)*(1-on/{n}))"
    y_down = f"max(0,(ih-ih/zoom)*on/{n})"
    if style == "pull_out":
        z, x, y = z_out, x_ctr, y_ctr
    elif style == "pan_right":
        z, x, y = z_hold, x_max, f"(ih-ih/zoom)*0.28"
    elif style == "pan_left":
        z, x, y = z_hold, x_min, f"(ih-ih/zoom)*0.35"
    elif style == "rise":
        z, x, y = z_hold, x_ctr, y_up
    elif style == "fall":
        z, x, y = z_hold, x_ctr, y_down
    else:
        # punch_in / punch_shake — strong push-in
        z, x, y = z_in, x_ctr, f"{y_ctr}-0.18*(ih-ih/zoom)*on/{n}"
    return (
        f"zoompan=z='{z}':x='{x}':y='{y}':"
        f"d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS}"
    )


def _look_filters(shot: dict[str, Any], *, remux_clean: bool = False) -> str:
    """Grade + grain + vignette so it doesn't look like a PNG slideshow.

    remux_clean=True: compositing an already-rendered motion/lip video into clip.
    Skip punch_shake + temporal noise so voice/lip assembly does not re-jitter
    the performance master.
    """
    if remux_clean:
        return "setsar=1"
    style = _camera_style(shot)
    shake = ""
    if style == "punch_shake":
        shake = (
            f"crop=iw-64:ih-64:'32+30*sin(n*2.3)':'32+24*cos(n*2.9)',"
            f"scale={WIDTH}:{HEIGHT},"
        )
    return (
        f"{shake}"
        "eq=contrast=1.12:saturation=1.22:gamma=0.98:brightness=0.02,"
        "vignette=PI/3.4:mode=forward,"
        "noise=alls=8:allf=t+u,"
        "unsharp=5:5:0.75:5:5:0.0"
    )


def _run_ffmpeg(args: list[str], *, cwd: Path | None = None, timeout: int = 240) -> None:
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(
        [_ffmpeg_bin(), "-hide_banner", "-loglevel", "error", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=creationflags,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "ffmpeg failed").strip()
        raise RuntimeError(err[:800] or f"ffmpeg exit {proc.returncode}")


_tts_loop: Any = None
_tts_loop_lock = threading.Lock()


def _get_tts_loop() -> Any:
    """S4: reuse one background event loop for all edge-tts synthesis.

    Creating asyncio.run() per sentence spawns a new loop + thread each time.
    A single daemon thread hosting one loop serializes TTS without the churn.
    """
    global _tts_loop
    with _tts_loop_lock:
        if _tts_loop is not None and not _tts_loop.is_closed():
            return _tts_loop
        loop = asyncio.new_event_loop()
        _tts_loop = loop
        t = threading.Thread(target=loop.run_forever, daemon=True, name="drama-tts")
        t.start()
        return loop


def _tts_to_file(text: str, dest: Path, *, voice: str | None = None) -> bool:
    """Synthesize speech. Returns False if skipped / failed."""
    spoken = (text or "").strip()
    if not spoken:
        return False
    try:
        import edge_tts  # type: ignore
    except ImportError:
        return False

    try:
        if dest.exists():
            dest.unlink()
    except OSError:
        return False

    async def _go() -> None:
        communicate = edge_tts.Communicate(spoken, voice or _tts_voice())
        await communicate.save(str(dest))

    try:
        fut = asyncio.run_coroutine_threadsafe(_go(), _get_tts_loop())
        fut.result(timeout=90)
    except Exception:
        return False
    return dest.is_file() and dest.stat().st_size > 0


def _concat_audio_files(parts: list[Path], dest: Path) -> bool:
    """Concatenate audio clips (mp3/wav) into one file via ffmpeg."""
    existing = [p for p in parts if p.is_file() and p.stat().st_size > 0]
    if not existing:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    if len(existing) == 1:
        if existing[0].resolve() != dest.resolve():
            shutil.copyfile(existing[0], dest)
        return dest.is_file() and dest.stat().st_size > 0
    if not ffmpeg_available():
        return False
    try:
        if dest.exists():
            dest.unlink()
    except OSError:
        return False
    args: list[str] = []
    for p in existing:
        args.extend(["-i", str(p)])
    n = len(existing)
    filt = "".join(f"[{i}:a]" for i in range(n)) + f"concat=n={n}:v=0:a=1[aout]"
    try:
        _run_ffmpeg(
            [*args, "-filter_complex", filt, "-map", "[aout]", "-y", str(dest)],
            timeout=120,
        )
    except RuntimeError:
        return False
    return dest.is_file() and dest.stat().st_size > 0


def _synthesize_shot_voice(
    shot: dict[str, Any],
    cast: list[dict[str, Any]],
    voice_path: Path,
    *,
    slug: str,
) -> tuple[bool, str, list[dict[str, Any]]]:
    """
    TTS for a shot. Multi-speaker dialogue → each turn with its own voice, then concat.
    Returns (ok, primary_voice_id, timed_turns).
    """
    from tools.drama_models import load_models
    from tools.drama_retry import retry_call
    from tools.providers import registry

    turns = dialogue_turns_for_shot(shot, cast, slug=slug)
    if not turns:
        return False, "", []

    tts_cfg = (load_models(slug) or {}).get("tts") or {}
    tts_provider = str(tts_cfg.get("provider") or "edge-tts").strip() or "edge-tts"
    primary = str(turns[0].get("voice") or voice_id_for_shot(shot, cast, slug=slug))
    timed: list[dict[str, Any]] = []

    if len(turns) == 1:
        ok = bool(
            retry_call(
                registry.dispatch,
                "tts",
                tts_provider,
                turns[0]["text"],
                voice_path,
                voice=turns[0]["voice"] or primary,
            )
        )
        dur = float(_probe_duration(voice_path) or 0) if ok else 0.0
        timed = [
            {
                "speaker": turns[0].get("speaker") or "",
                "text": turns[0].get("text") or "",
                "voice": turns[0].get("voice") or primary,
                "start": 0.0,
                "end": round(dur, 3),
            }
        ]
        return ok, primary, timed

    tmp_dir = voice_path.parent / f"_tts_turns_{shot.get('n') or 0}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    try:
        cursor = 0.0
        for i, turn in enumerate(turns):
            part = tmp_dir / f"t{i:02d}.mp3"
            ok = bool(
                retry_call(
                    registry.dispatch,
                    "tts",
                    tts_provider,
                    turn["text"],
                    part,
                    voice=turn.get("voice") or primary,
                )
            )
            if not ok:
                return False, primary, []
            parts.append(part)
            seg = float(_probe_duration(part) or 0)
            timed.append(
                {
                    "speaker": turn.get("speaker") or "",
                    "text": turn.get("text") or "",
                    "voice": turn.get("voice") or primary,
                    "start": round(cursor, 3),
                    "end": round(cursor + max(seg, 0.0), 3),
                }
            )
            cursor += max(seg, 0.0)
        if not _concat_audio_files(parts, voice_path):
            return False, primary, []
        return True, primary, timed
    finally:
        for p in parts:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            tmp_dir.rmdir()
        except OSError:
            pass


def _probe_duration(path: Path) -> float:
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    ffprobe = shutil.which("ffprobe") or "ffprobe"
    try:
        proc = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nk=1:nw=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=creationflags,
        )
        return max(0.5, float((proc.stdout or "0").strip() or 0))
    except (ValueError, OSError, subprocess.SubprocessError):
        return 0.0


def _encode_clip(
    scene: Path,
    overlay: Path,
    clip: Path,
    duration: float,
    audio: Path | None,
    shot: dict[str, Any],
) -> None:
    """Assemble clip = previous visual master + voice + overlay.

    Chain: motion (video page) → optional lip(motion) → clip.
    Never prefer a lip built from lip_base when motion exists (would drop 运镜).
    """
    lip_rel = (shot.get("assets") or {}).get("lip") or ""
    lip_path = resolve_safe(lip_rel) if lip_rel else None
    from tools.providers.lip_providers import REAL_LIP_SOURCES

    lip_ok = (
        str(shot.get("lip_source") or "") in REAL_LIP_SOURCES
        and lip_path is not None
        and lip_path.is_file()
        and lip_path.stat().st_size > 500
    )
    # Divergent lip_base must not replace video-page motion in the final picture.
    lip_divergent = bool(shot.get("lip_base_used"))

    motion_rel = (shot.get("assets") or {}).get("motion") or ""
    motion_path = resolve_safe(motion_rel) if motion_rel else None
    src = str(shot.get("i2v_source") or "")
    has_motion = bool(
        motion_path and motion_path.is_file() and src in ("ai", "keys", "fallback")
    )

    if lip_ok and not (lip_divergent and has_motion):
        _encode_clip_from_motion(lip_path, overlay, clip, duration, audio, shot, remux_clean=True)
        return

    # Clip is assemble-only: reuse existing motion; never call generate_shot_i2v here.
    if has_motion and motion_path:
        _encode_clip_from_motion(
            motion_path,
            overlay,
            clip,
            duration,
            audio,
            shot,
            remux_clean=True,
        )
        return
    _encode_clip_from_still(scene, overlay, clip, duration, audio, shot)


def _encode_clip_from_still(
    scene: Path,
    overlay: Path,
    clip: Path,
    duration: float,
    audio: Path | None,
    shot: dict[str, Any],
) -> None:
    """Ken Burns on PNG still. Length follows script/voice target; audio is padded to match."""
    target = max(float(duration or 0), 0.5)
    frames = max(int(round(target * FPS)), FPS)
    motion = _motion_expr(shot, frames)
    look = _look_filters(shot)
    vf = (
        f"[0:v]scale={ZOOM_W}:{ZOOM_H}:force_original_aspect_ratio=increase,"
        f"crop={ZOOM_W}:{ZOOM_H},{motion},{look},fps={FPS}[v];"
        f"[v][1:v]overlay=0:0:format=auto,format=yuv420p[vout]"
    )
    # Input framerate is required or zoompan often emits a single still.
    args = [
        "-y",
        "-framerate",
        str(FPS),
        "-loop",
        "1",
        "-i",
        str(scene),
        "-framerate",
        str(FPS),
        "-loop",
        "1",
        "-i",
        str(overlay),
    ]
    if audio is not None:
        args += ["-i", str(audio)]
        af = (
            f"[2:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,"
            f"apad=whole_dur={target:.3f},atrim=0:{target:.3f},asetpts=PTS-STARTPTS[aout]"
        )
    else:
        args += [
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
        ]
        af = (
            f"[2:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,"
            f"atrim=0:{target:.3f},asetpts=PTS-STARTPTS[aout]"
        )
    args += [
        "-filter_complex",
        f"{vf};{af}",
        "-map",
        "[vout]",
        "-map",
        "[aout]",
        "-frames:v",
        str(frames),
        "-t",
        f"{target:.2f}",
        "-r",
        str(FPS),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "44100",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        str(clip),
    ]
    _run_ffmpeg(args, timeout=240)


def _encode_clip_from_motion(
    motion: Path,
    overlay: Path,
    clip: Path,
    duration: float,
    audio: Path | None,
    shot: dict[str, Any],
    *,
    remux_clean: bool = True,
) -> None:
    """Composite pre-rendered motion/lip with subtitles and voice.

    Clip length follows max(script, voice). Short video is extended by freezing
    the last frame (not looping), so performance timing is not polluted.
    """
    look = _look_filters(shot, remux_clean=remux_clean)
    target = max(float(duration or 0), 0.5)
    frames = max(int(round(target * FPS)), 1)
    motion_dur = _probe_duration(motion) if motion.is_file() else 0.0
    hold = max(0.0, target - motion_dur) if motion_dur > 0.05 else 0.0
    if hold > 0.05:
        vchain = (
            f"[0:v]tpad=stop_mode=clone:stop_duration={hold:.3f},"
            f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
            f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,{look},fps={FPS}[v]"
        )
    else:
        vchain = (
            f"[0:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
            f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,{look},fps={FPS}[v]"
        )
    vf = f"{vchain};[v][1:v]overlay=0:0:format=auto,format=yuv420p[vout]"
    args = ["-y", "-i", str(motion), "-framerate", str(FPS), "-loop", "1", "-i", str(overlay)]
    if audio is not None:
        args += ["-i", str(audio)]
        af = (
            f"[2:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,"
            f"apad=whole_dur={target:.3f},atrim=0:{target:.3f},asetpts=PTS-STARTPTS[aout]"
        )
    else:
        args += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
        af = (
            f"[2:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,"
            f"atrim=0:{target:.3f},asetpts=PTS-STARTPTS[aout]"
        )
    args += [
        "-filter_complex",
        f"{vf};{af}",
        "-map",
        "[vout]",
        "-map",
        "[aout]",
        "-frames:v",
        str(frames),
        "-t",
        f"{target:.2f}",
        "-r",
        str(FPS),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "44100",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        str(clip),
    ]
    _run_ffmpeg(args, timeout=240)


def _assemble_clips(
    specs: list[dict[str, Any]],
    out_path: Path,
    *,
    fade_sec: float = XFADE_SEC,
) -> str:
    """Hard-concat trimmed clips. Timeline edits never rewrite per-shot source files.

    Soft xfade was removed as the default because overlaps shorten the episode by
    ~(N-1)*fade_sec and desync from the script total duration.
    """
    if not specs:
        raise ValueError("没有可拼接的镜头")
    if len(specs) == 1:
        spec = specs[0]
        path = spec["path"]
        trim_in = float(spec.get("trim_in") or 0)
        trim_out = float(spec.get("trim_out") or 0)
        vol = float(spec.get("volume") or 1.0)
        probe = _probe_duration(path)
        end = max(trim_in + 0.25, probe - trim_out)
        if trim_in > 0.01 or trim_out > 0.01 or abs(vol - 1.0) > 0.01:
            _run_ffmpeg(
                [
                    "-y",
                    "-i",
                    str(path),
                    "-filter_complex",
                    (
                        f"[0:v]trim=start={trim_in:.3f}:end={end:.3f},setpts=PTS-STARTPTS[v];"
                        f"[0:a]atrim=start={trim_in:.3f}:end={end:.3f},asetpts=PTS-STARTPTS,volume={vol:.2f}[a]"
                    ),
                    "-map",
                    "[v]",
                    "-map",
                    "[a]",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-movflags",
                    "+faststart",
                    str(out_path),
                ],
                timeout=120,
            )
            return "trim"
        _run_ffmpeg(
            ["-y", "-i", str(path), "-c", "copy", "-movflags", "+faststart", str(out_path)],
            timeout=60,
        )
        return "copy"

    inputs: list[str] = []
    parts: list[str] = []
    n_clips = len(specs)
    for i, spec in enumerate(specs):
        path = spec["path"]
        trim_in = float(spec.get("trim_in") or 0)
        trim_out = float(spec.get("trim_out") or 0)
        vol = float(spec.get("volume") or 1.0)
        target_play = max(0.25, float(spec.get("play_duration") or 0.25))
        probe = float(spec.get("file_duration") or 0) or _probe_duration(path)
        # 先尽量取文件可用区间，再按剧本目标时长补齐（短则 pad，长则裁到目标）
        avail_end = max(trim_in + 0.05, probe - trim_out) if probe > trim_in + 0.05 else trim_in + min(0.25, target_play)
        avail_play = max(0.05, avail_end - trim_in)
        use_end = avail_end
        if avail_play > target_play + 0.04:
            use_end = trim_in + target_play
            avail_play = target_play
        pad = max(0.0, target_play - avail_play)
        inputs += ["-i", str(path)]
        v_chain = (
            f"[{i}:v]trim=start={trim_in:.3f}:end={use_end:.3f},setpts=PTS-STARTPTS,"
            f"fps={FPS},format=yuv420p"
        )
        if pad > 0.04:
            v_chain += f",tpad=stop_mode=clone:stop_duration={pad:.3f}"
        parts.append(f"{v_chain}[v{i}]")
        parts.append(
            f"[{i}:a]atrim=start={trim_in:.3f}:end={use_end:.3f},asetpts=PTS-STARTPTS,"
            f"aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"volume={vol:.2f},"
            f"apad=whole_dur={target_play:.3f},atrim=0:{target_play:.3f},asetpts=PTS-STARTPTS[a{i}]"
        )

    concat_in = "".join(f"[v{i}][a{i}]" for i in range(n_clips))
    parts.append(f"{concat_in}concat=n={n_clips}:v=1:a=1[vout][aout]")

    args = [
        "-y",
        *inputs,
        "-filter_complex",
        ";".join(parts),
        "-map",
        "[vout]",
        "-map",
        "[aout]",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "44100",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        str(out_path),
    ]
    try:
        _run_ffmpeg(args, timeout=400)
        return "concat"
    except RuntimeError:
        list_file = out_path.parent / "concat.txt"
        list_file.write_text(
            "\n".join(f"file '{spec['path'].name}'" for spec in specs) + "\n",
            encoding="utf-8",
        )
        _run_ffmpeg(
            [
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file.name),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(out_path),
            ],
            cwd=out_path.parent,
        )
        return "concat-fallback"


def sync_shots_doc(
    slug: str,
    episode: int,
    markdown: str,
    *,
    title: str = "",
) -> dict[str, Any]:
    parsed = parse_episode_markdown(markdown)
    if not parsed.get("shots"):
        raise ValueError("剧本里没有分镜（需要 ### Shot N (0-3s) 格式）")
    doc = merge_from_parsed(
        slug,
        episode,
        parsed,
        title=title,
        existing=load_doc(slug, episode),
    )
    resolve_safe(work_rel(slug, episode)).mkdir(parents=True, exist_ok=True)
    save_doc(doc)
    rel = str(doc.get("script_path") or script_rel(slug, episode))
    path = resolve_safe(rel)
    if path.is_file():
        original = path.read_text(encoding="utf-8")
        restored = restore_frozen_shots_markdown(original, doc)
        if restored != original:
            path.write_text(restored.rstrip() + "\n", encoding="utf-8")
    return doc


def _path_for(shot: dict[str, Any], layer: str) -> Path:
    """Resolve a shot asset path with a readable error on missing/illegal value."""
    rel = (shot.get("assets") or {}).get(layer)
    if not rel:
        raise ValueError(f"镜头 {shot.get('n')} 缺少 {layer} 资产路径，请先生成该层")
    try:
        path = resolve_safe(rel)
    except ValueError as e:
        raise ValueError(f"镜头 {shot.get('n')} 的 {layer} 路径非法：{rel}") from e
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def render_shot_layers(
    slug: str,
    episode: int,
    shot: dict[str, Any],
    layers: list[str],
    *,
    title: str,
) -> dict[str, Any]:
    """Rebuild selected layers for one shot. Unspecified layers are reused on disk."""
    if not ffmpeg_available():
        raise RuntimeError("未找到 ffmpeg，请先安装并加入 PATH")

    wanted = [layer for layer in LAYERS if layer in layers]
    locked = set(shot.get("locked") or [])
    if "shot" in locked:
        locked = set(LAYERS) | locked
    wanted = [layer for layer in wanted if layer not in locked]
    do_lip = "lip" in layers and "lip" not in locked
    if not wanted and not do_lip:
        return {"n": shot.get("n"), "rebuilt": [], "skipped": "locked_or_empty"}

    assets = shot.setdefault("assets", {})
    scene = _path_for(shot, "scene")
    overlay = _path_for(shot, "overlay")
    voice = _path_for(shot, "voice")
    clip = _path_for(shot, "clip")

    rebuilt: list[str] = []
    degrades: list[dict[str, Any]] = []
    used_tts = False
    used_ai = False
    cards = load_characters(slug)
    cast = resolve_shot_characters(shot, cards)

    if "scene" in wanted:
        generated = generate_shot_candidates(slug, episode, shot, title=title)
        used_ai = any(item.get("source") == "ai" for item in generated)
        if not used_ai:
            degrades.append({"shot": int(shot.get("n") or 0), "layer": "scene", "reason": "AI 出图失败，使用降级静图"})
        if not _path_for(shot, "scene").is_file() and generated:
            apply_candidate_to_scene(shot, generated[0])
        rebuilt.append("scene")
        # R4: auto identity hard gate. Failed identity marks scene/motion/clip
        # dirty so retry (重抽) is the natural next step.
        if used_ai:
            from tools.drama_qc import qc_shot_identity

            identity = qc_shot_identity(slug, episode, shot, apply=True)
            if str(identity.get("status") or "") == "ok" and not identity.get("pass"):
                degrades.append(
                    {
                        "shot": int(shot.get("n") or 0),
                        "layer": "identity",
                        "reason": f"身份余弦 {identity.get('cosine')} 低于阈值，已标脏可重抽",
                    }
                )

    if "overlay" in wanted:
        _draw_subtitle_overlay(shot, overlay)
        rebuilt.append("overlay")

    duration = float(shot.get("duration") or 5)
    if "voice" in wanted:
        turns = dialogue_turns_for_shot(shot, cast, slug=slug)
        speech = " ".join(t.get("text") or "" for t in turns).strip()
        if turns:
            has_audio, voice_sel, timed_turns = _synthesize_shot_voice(shot, cast, voice, slug=slug)
        else:
            has_audio, voice_sel, timed_turns = False, "", []
        if has_audio:
            used_tts = True
            shot["voice_turns"] = timed_turns
            if len(turns) == 1 and not str(shot.get("voice") or "").strip():
                shot["voice"] = voice_sel
            elif len(turns) >= 2:
                # Multi-speaker: keep per-character voices; don't pin one shot.voice
                shot["voice"] = ""
        elif voice.exists():
            try:
                voice.unlink()
            except OSError:
                pass
            shot["voice_turns"] = []
        if speech and not has_audio:
            degrades.append({"shot": int(shot.get("n") or 0), "layer": "voice", "reason": "TTS 失败，本镜无声"})
        rebuilt.append("voice")

    if do_lip:
        from tools.drama_lip import generate_shot_lip

        lip_info = generate_shot_lip(slug, episode, shot)
        if lip_info.get("tried") and str(lip_info.get("lip_source") or "") == "fallback":
            degrades.append(
                {
                    "shot": int(shot.get("n") or 0),
                    "layer": "lip",
                    "reason": str(lip_info.get("reason") or shot.get("lip_error") or "口型失败，回退闭口静图"),
                }
            )
        rebuilt.append("lip")
        assets["lip"] = (shot.get("assets") or {}).get("lip") or assets.get("lip")
        if "clip" not in wanted and "clip" not in locked:
            wanted = [*wanted, "clip"]

    if "clip" in wanted:
        if not scene.is_file():
            raise RuntimeError(f"镜头 {shot.get('n')} 没有画面，请先生成 scene")
        # 成片前按当前旁白/字幕重画叠层，避免声音页 CSS 预览正确、clip 仍是旧烧录
        _draw_subtitle_overlay(shot, overlay)
        if "overlay" not in rebuilt:
            rebuilt.append("overlay")
        shot["camera"] = shot.get("camera") or _camera_style(shot)
        audio = voice if voice.is_file() and voice.stat().st_size > 0 else None
        if audio is not None:
            voice_dur = _probe_duration(audio)
            # 配音更长时拉长本镜，保证成片听得完、总时长与修改后一致
            if voice_dur > duration + 0.05:
                duration = voice_dur
                shot["duration"] = round(float(duration), 1)
        shot["_slug"] = slug
        shot["_episode"] = episode
        _encode_clip(scene, overlay, clip, duration, audio, shot)
        shot.pop("_slug", None)
        shot.pop("_episode", None)
        rebuilt.append("clip")
        assets["clip"] = assets.get("clip") or str(clip)

    remaining = [layer for layer in (shot.get("dirty") or []) if layer not in rebuilt]
    shot["dirty"] = remaining
    shot["status"] = "rendered" if not remaining and clip.is_file() else "dirty"

    # P1-9: record the actual spend for the providers that really ran this pass.
    costs: list[dict[str, Any]] = []
    n = int(shot.get("n") or 0)
    if "scene" in rebuilt and used_ai:
        from tools.drama_models import cost_entry
        from tools.drama_styles import estimate_image

        img = estimate_image(slug, shot, episode=episode)
        if float(img.get("cost_per_shot") or 0) > 0:
            costs.append(
                cost_entry(
                    provider=str(img.get("provider") or ""),
                    layer="scene",
                    cost=float(img.get("cost_per_shot") or 0),
                    shot=n,
                )
            )
    if "lip" in rebuilt:
        from tools.drama_lip import estimate_lip

        lip_est = estimate_lip(slug, shot)
        if lip_est.get("will_run") and float(lip_est.get("cost_per_shot") or 0) > 0:
            from tools.drama_models import cost_entry

            costs.append(
                cost_entry(
                    provider=str(lip_est.get("provider") or ""),
                    layer="lip",
                    cost=float(lip_est.get("cost_per_shot") or 0),
                    shot=n,
                )
            )
    if "clip" in rebuilt:
        from tools.drama_models import cost_entry, estimate_i2v

        i2v_est = estimate_i2v(slug, shot)
        if i2v_est.get("will_run") and float(i2v_est.get("cost_per_shot") or 0) > 0:
            costs.append(
                cost_entry(
                    provider=str(i2v_est.get("provider") or ""),
                    layer="motion",
                    cost=float(i2v_est.get("cost_per_shot") or 0),
                    shot=n,
                )
            )

    return {
        "n": shot.get("n"),
        "rebuilt": rebuilt,
        "degrades": degrades,
        "costs": costs,
        "duration": shot.get("duration"),
        "camera": shot.get("camera"),
        "scene_source": shot.get("scene_source"),
        "ai": used_ai,
        "tts": used_tts,
        "clip": assets.get("clip"),
    }


def assemble_episode(doc: dict[str, Any]) -> str:
    from tools.drama_audio import mix_assembled, vo_stem_rel
    from tools.drama_shots import cascade_shot_timings, script_rel
    from tools.drama_timeline import build_assemble_specs

    slug = str(doc["slug"])
    episode = int(doc["episode"])
    cascade_shot_timings(doc)
    out_rel = doc.get("output") or output_rel(slug, episode)
    out_path = resolve_safe(out_rel)
    stem_path = resolve_safe(vo_stem_rel(slug, episode))
    specs, fade_sec = build_assemble_specs(doc, probe_duration=_probe_duration)
    ready = [s for s in specs if not s.get("missing")]
    if not ready:
        raise FileNotFoundError("没有可拼接的镜头成片")
    assemble = _assemble_clips(ready, stem_path, fade_sec=fade_sec)
    mix_mode = mix_assembled(slug, episode, stem=stem_path, dest=out_path)
    doc["assemble"] = assemble
    doc["mix"] = mix_mode
    # 用分镜时长之和回写剧本「时长」，与成片对齐
    total = sum(float(s.get("play_duration") or 0) for s in ready)
    try:
        sp = resolve_safe(script_rel(slug, episode))
        if sp.is_file():
            text = sp.read_text(encoding="utf-8")
            updated = patch_episode_meta_duration(text, total)
            if updated != text:
                sp.write_text(updated, encoding="utf-8")
    except Exception:
        pass
    save_doc(doc)
    return assemble


def _voice_file_exists(shot: dict[str, Any]) -> bool:
    rel = (shot.get("assets") or {}).get("voice")
    if not rel:
        return False
    path = resolve_safe(rel)
    return path.is_file() and path.stat().st_size > 0


def _episode_result(doc: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    out_rel = str(doc.get("output") or output_rel(str(doc["slug"]), int(doc["episode"])))
    out_path = resolve_safe(out_rel)
    shots = doc.get("shots") or []
    payload = {
        "slug": doc.get("slug"),
        "episode": doc.get("episode"),
        "title": doc.get("title"),
        "path": out_rel,
        "play_url": f"/api/workspace/file?path={out_rel}",
        "bytes": out_path.stat().st_size if out_path.is_file() else 0,
        "shots": len(shots),
        "shots_json": json_rel(str(doc["slug"]), int(doc["episode"])),
        "ai_scenes": sum(1 for s in shots if s.get("scene_source") == "ai"),
        "tts": any(
            _voice_file_exists(s) for s in shots
        ),
        "assemble": doc.get("assemble"),
        "workspace": str(config.WORKSPACE_DIR),
        "shot_list": [public_shot(s) for s in shots],
    }
    if extra:
        payload.update(extra)
    return payload


def render_episode_video(
    slug: str,
    episode: int,
    markdown: str,
    *,
    title: str = "",
    force: bool = False,
    cancel_check: Callable[[], None] | None = None,
    on_progress: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """Render dirty (or all) shots independently. Does not assemble epNN.mp4.

    Call export_episode (or layers including assemble) to build the full episode.
    """
    doc = sync_shots_doc(slug, episode, markdown, title=title)
    ep_title = str(title or doc.get("title") or f"第{episode}集")
    rebuilt: list[int] = []
    skipped: list[int] = []
    degraded: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for shot in doc.get("shots") or []:
        if "shot" in (shot.get("locked") or []):
            skipped.append(int(shot["n"]))
            continue
        layers = list(LAYERS) if force else list(shot.get("dirty") or [])
        if not layers:
            clip_rel = (shot.get("assets") or {}).get("clip")
            if clip_rel and resolve_safe(clip_rel).is_file():
                skipped.append(int(shot["n"]))
                continue
            layers = list(LAYERS)
        pending.append(shot)

    # Even skipped shots that already exist can carry stale degrade markers;
    # collect degrade info from doc regardless of rebuild.
    for shot in doc.get("shots") or []:
        for mark in shot.get("degrades") or []:
            if isinstance(mark, dict):
                degraded.append(
                    {
                        "shot": int(shot.get("n") or 0),
                        "layer": mark.get("layer"),
                        "reason": mark.get("reason"),
                    }
                )

    total = len(pending)
    if on_progress:
        on_progress(current=0, total=total, message="准备重渲…")

    from tools.drama_models import append_cost

    for index, shot in enumerate(pending):
        if cancel_check:
            cancel_check()
        n = int(shot["n"])
        if on_progress:
            on_progress(
                current=index,
                total=total,
                shot=n,
                message=f"Shot {n} ({index + 1}/{total})",
            )
        layers = list(LAYERS) if force else list(shot.get("dirty") or []) or list(LAYERS)
        info = render_shot_layers(slug, episode, shot, layers, title=ep_title)
        info_degrades = info.get("degrades") or []
        if info_degrades:
            # merge this shot's fresh degrade marks (drop stale ones for this shot)
            degraded = [d for d in degraded if int(d.get("shot") or 0) != n]
            degraded.extend(info_degrades)
            shot["degrades"] = info_degrades
        for cost in info.get("costs") or []:
            if not isinstance(cost, dict):
                continue
            append_cost(
                doc,
                provider=str(cost.get("provider") or "") or "unknown",
                layer=str(cost.get("layer") or ""),
                cost=float(cost.get("cost") or 0),
                shot=cost.get("shot"),
            )
        if info.get("rebuilt"):
            rebuilt.append(n)
        else:
            skipped.append(n)
        shot["status"] = "rendered" if not shot.get("dirty") else shot.get("status")
        save_doc(doc)
        if cancel_check:
            cancel_check()

    if on_progress:
        on_progress(current=total, total=total, message="单镜渲染完成")
    if cancel_check:
        cancel_check()
    # 整集拼接仅由「导出整集」触发，单镜/批量重渲不再自动 assemble
    assemble = str(doc.get("assemble") or "pending_export")
    save_doc(doc)
    from tools.drama_models import actual_episode_cost

    return _episode_result(
        doc,
        {
            "rebuilt_shots": rebuilt,
            "skipped_shots": skipped,
            "assemble": assemble,
            "degraded": degraded,
            "actual_spent": actual_episode_cost(slug, episode),
        },
    )


def rerender_shot(
    slug: str,
    episode: int,
    shot_n: int,
    *,
    markdown: str | None = None,
    title: str = "",
    patch: dict[str, Any] | None = None,
    layers: list[str] | None = None,
) -> dict[str, Any]:
    """Patch one shot, rebuild only requested layers. Does not assemble the episode.

    Full-episode mp4 is produced only by export_episode / layers=['assemble'].
    """
    doc = load_doc(slug, episode)
    if doc is None:
        if not markdown:
            raise ValueError("没有 shots.json，请先 parse_shots 或 render_episode")
        doc = sync_shots_doc(slug, episode, markdown, title=title)

    shot = find_shot(doc, shot_n)
    if shot is None:
        raise ValueError(f"找不到 Shot {shot_n}")

    patch = {k: v for k, v in (patch or {}).items() if v is not None}
    if patch:
        apply_patch(shot, patch)

    locked = set(shot.get("locked") or [])
    if "shot" in locked:
        return _episode_result(
            doc,
            {
                "rebuilt_shots": [],
                "skipped_shots": [int(s["n"]) for s in doc.get("shots") or []],
                "shot": public_shot(shot),
                "rebuilt_layers": [],
                "skipped_layers": ["shot"],
                "assemble": str(doc.get("assemble") or "unchanged"),
            },
        )

    requested = parse_layers(layers, extra=("assemble", "motion", "lip")) if layers else []
    wanted = [layer for layer in requested if layer in LAYERS or layer in ("lip", "motion")]
    assemble_only = bool(requested) and not wanted and "assemble" in requested
    if assemble_only:
        assemble = assemble_episode(doc)
        return _episode_result(
            doc,
            {
                "rebuilt_shots": [],
                "skipped_shots": [int(s["n"]) for s in doc.get("shots") or []],
                "shot": public_shot(shot),
                "rebuilt_layers": ["assemble"],
                "skipped_layers": list(locked),
                "assemble": assemble,
            },
        )

    if not wanted:
        wanted = list(shot.get("dirty") or []) or layers_for_patch(patch, shot.get("locked")) or ["clip"]
    if "clip" not in wanted and any(layer in wanted for layer in ("scene", "overlay", "voice", "lip", "motion")):
        if "clip" not in locked:
            wanted = [*wanted, "clip"]
    wanted = [layer for layer in wanted if layer not in locked]

    ep_title = str(title or doc.get("title") or f"第{episode}集")
    info = render_shot_layers(slug, episode, shot, wanted, title=ep_title)

    # P1-10: single-shot rerender must keep the degrade list visible (and the
    # cost recorded), matching the bulk render_episode result.
    shot["degrades"] = info.get("degrades") or []
    from tools.drama_models import actual_episode_cost
    from tools.drama_shots import merge_save_shot

    # Merge this shot + costs under episode lock so parallel batch jobs don't clobber.
    doc = merge_save_shot(
        slug,
        episode,
        shot,
        costs=list(info.get("costs") or []),
        cascade_from=shot_n,
    )

    # 需要整集时请显式传 layers 含 assemble，或走 export_episode
    do_assemble = "assemble" in requested
    assemble = assemble_episode(doc) if do_assemble else str(doc.get("assemble") or "pending_export")
    return _episode_result(
        doc,
        {
            "rebuilt_shots": [shot_n] if info.get("rebuilt") else [],
            "skipped_shots": [
                int(s["n"]) for s in doc.get("shots") or [] if int(s["n"]) != shot_n
            ],
            "shot": public_shot(shot),
            "rebuilt_layers": info.get("rebuilt") or [],
            "skipped_layers": [layer for layer in (requested or wanted) if layer in locked],
            "assemble": assemble,
            "degraded": info.get("degrades") or [],
            "actual_spent": actual_episode_cost(slug, episode),
        },
    )
