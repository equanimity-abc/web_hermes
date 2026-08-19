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
from typing import Any

from config import config
from tools.drama_characters import (
    character_prompt_clause,
    character_seed,
    load_characters,
    normalize_roles,
    primary_voice,
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
_FIELD = re.compile(r"^-\s*(画面|对白|字幕|角色)\s*[:：]\s*(.*)\s*$")
_RANGE = re.compile(r"(\d+(?:\.\d+)?)\s*[-–~]\s*(\d+(?:\.\d+)?)")
_QUOTE = re.compile(r"[「『“\"]([^」』”\"]+)[」』”\"]")

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
        m_meta = re.match(r"^-\s*(时长|钩子|悬念)\s*[:：]\s*(.*)$", line)
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
                "对白": "",
                "字幕": "",
                "角色": "",
            }
            continue
        if current is None:
            continue
        m_field = _FIELD.match(line)
        if m_field:
            current[m_field.group(1)] = m_field.group(2).strip()

    if current:
        shots.append(current)

    shots.sort(key=lambda s: int(s["n"]))
    return {"title": title, "meta": meta, "shots": shots, "count": len(shots)}


def patch_shot_in_markdown(text: str, shot_n: int, patch: dict[str, Any]) -> str:
    """Write 画面/对白/字幕/角色 back into the episode markdown for one shot."""
    keys = ("画面", "对白", "字幕", "角色")
    fields: dict[str, str] = {}
    for key, value in (patch or {}).items():
        if key not in keys or value is None:
            continue
        if key == "角色":
            fields[key] = "、".join(normalize_roles(value))
        else:
            fields[key] = str(value)
    if not fields:
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
            out.append(line)
            continue
        if in_target:
            m_field = _FIELD.match(stripped)
            if m_field and m_field.group(1) in fields:
                key = m_field.group(1)
                out.append(f"- {key}: {fields[key]}")
                pending.pop(key, None)
                continue
        out.append(line)
    if in_target:
        flush_pending()
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
                "对白": shot.get("对白") or "",
                "字幕": shot.get("字幕") or "",
                "角色": shot.get("角色") or [],
            },
        )
    return text


def _parse_timing(timing: str) -> tuple[float, float, float]:
    m = _RANGE.search(timing or "")
    if not m:
        return 0.0, 5.0, 5.0
    start = float(m.group(1))
    end = float(m.group(2))
    if end <= start:
        end = start + 3.0
    return start, end, round(end - start, 2)


def spoken_text(dialogue: str, subtitle: str = "") -> str:
    text = (dialogue or "").strip()
    quotes = _QUOTE.findall(text)
    if quotes:
        return "。".join(q.strip() for q in quotes if q.strip())
    stripped = re.sub(r"^[^:：]{1,16}[:：]\s*", "", text).strip()
    if stripped:
        return stripped
    return (subtitle or "").strip()


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
    scene = (shot.get("画面") or "").strip() or "cinematic Chinese myth scene"
    style = _camera_style(shot)
    kinetic = {
        "punch_in": "dynamic action pose, motion implied, wind-blown cloth, sparks",
        "punch_shake": "explosive action, flying debris, impact freeze, dramatic angle",
        "pan_right": "wide moving scene, characters mid-stride, trailing motion",
        "pan_left": "wide chasing scene, dust and speed lines implied",
        "rise": "low angle looking up, towering architecture, clouds rushing",
        "fall": "high angle descending, ground rushing closer",
        "pull_out": "epic establishing shot, vast landscape, tiny figure",
    }.get(style, "cinematic staging, strong silhouette")
    slug = slug or str(shot.get("slug") or "")
    char_clause = character_prompt_clause(characters or [], slug=slug)
    return (
        "vertical 9:16 cinematic Chinese animation keyframe, "
        f"{title or 'short drama'}, {scene}, {char_clause}, {kinetic}, "
        "classic manhua / anime illustration, dramatic rim lighting, highly detailed, "
        "no text, no letters, no subtitles, no watermark, no UI"
    )


def _camera_style(shot: dict[str, Any]) -> str:
    """Pick a visible camera move from shot text — not a tiny Ken Burns."""
    scene = shot.get("画面") or ""
    n = int(shot.get("n") or 1)
    if any(k in scene for k in ("打", "战", "棒", "怒", "砸", "翻", "炸", "劈")):
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


def _generate_scene_image(prompt: str, dest: Path, *, seed: int) -> bool:
    provider = (config.IMAGE_GEN_PROVIDER or "pollinations").strip().lower()
    if provider in ("", "none", "off"):
        return False
    quoted = urllib.parse.quote(prompt)
    model = config.IMAGE_GEN_MODEL or "flux"
    url = (
        f"https://image.pollinations.ai/prompt/{quoted}"
        f"?width=1024&height=1792&model={urllib.parse.quote(model)}"
        f"&nologo=true&enhance=true&seed={seed}"
    )
    try:
        from io import BytesIO

        import httpx
        from PIL import Image

        with httpx.Client(timeout=90.0, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": "my-tiktok-video-agent/0.8"})
            resp.raise_for_status()
            img = Image.open(BytesIO(resp.content)).convert("RGB")
        img = _fit_cover(img, ZOOM_W, ZOOM_H)
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest, "PNG")
        return dest.is_file() and dest.stat().st_size > 1000
    except Exception:
        return False


def _write_scene_png(data: bytes, dest: Path) -> None:
    from io import BytesIO

    from PIL import Image

    img = Image.open(BytesIO(data)).convert("RGB")
    img = _fit_cover(img, ZOOM_W, ZOOM_H)
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
    count = max(2, min(int(count or CANDIDATE_COUNT), 4))
    locked = set(shot.get("locked") or [])
    cards = load_characters(slug)
    cast = resolve_shot_characters(shot, cards)
    shot["camera"] = shot.get("camera") or _camera_style(shot)
    prompt = _scene_prompt(title, shot, cast, slug=slug)
    shot["prompt"] = prompt
    base_seed = character_seed(slug, cast, int(shot.get("n") or 1))
    ids = next_candidate_ids(shot, count)
    created: list[dict[str, Any]] = []
    used_ai = False
    n = int(shot.get("n") or 0)
    for i, cid in enumerate(ids):
        seed = (base_seed + i * 97) & 0x7FFFFFFF
        rel = candidate_rel(slug, episode, n, cid)
        dest = resolve_safe(rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        ai_ok = _generate_scene_image(prompt, dest, seed=seed)
        if not ai_ok:
            _draw_fallback_scene(shot, dest, cast, seed=seed)
        source = "ai" if ai_ok else "fallback"
        used_ai = used_ai or ai_ok
        rec = {"id": cid, "path": rel, "source": source, "seed": seed}
        created.append(rec)
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
    from PIL import Image, ImageDraw, ImageFilter

    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    shade = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    sd.rectangle((0, HEIGHT - 520, WIDTH, HEIGHT), fill=(12, 8, 6, 200))
    img = Image.alpha_composite(img, shade.filter(ImageFilter.GaussianBlur(8)))
    draw = ImageDraw.Draw(img)
    draw.rectangle((80, HEIGHT - 522, WIDTH - 80, HEIGHT - 516), fill=(212, 160, 23, 230))

    font_sub = _load_font(58)
    font_dlg = _load_font(36)
    max_w = WIDTH - 120
    y = HEIGHT - 470
    dialogue = (shot.get("对白") or "").strip()
    if dialogue:
        for line in _wrap(draw, dialogue, font_dlg, max_w)[:2]:
            w = draw.textlength(line, font=font_dlg)
            x = (WIDTH - w) / 2
            draw.text((x + 2, y + 2), line, font=font_dlg, fill=(0, 0, 0, 180))
            draw.text((x, y), line, font=font_dlg, fill=(255, 244, 220, 230))
            y += 48
        y += 10

    sub = (shot.get("字幕") or "").strip()
    for line in _wrap(draw, sub, font_sub, max_w)[:3]:
        w = draw.textlength(line, font=font_sub)
        x = (WIDTH - w) / 2
        draw.text((x + 3, y + 3), line, font=font_sub, fill=(0, 0, 0, 200))
        draw.text((x, y), line, font=font_sub, fill=(255, 229, 102, 255))
        y += 72

    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "PNG")


def _motion_expr(shot: dict[str, Any], frames: int) -> str:
    """Large travel zoom/pan. Tiny 1.0→1.16 zoom reads as a still."""
    style = _camera_style(shot)
    n = max(frames - 1, 1)
    # zoompan x/y must stay inside [0, iw-iw/zoom]
    z_in = f"min(1.10+0.42*on/{n},1.52)"
    z_out = f"max(1.52-0.42*on/{n},1.10)"
    z_hold = "1.34"
    x_ctr = "iw/2-(iw/zoom/2)"
    y_ctr = "ih/2-(ih/zoom/2)"
    x_max = f"max(0,min({x_ctr}*2,(iw-iw/zoom)*on/{n}))"
    x_min = f"max(0,(iw-iw/zoom)*(1-on/{n}))"
    y_up = f"max(0,(ih-ih/zoom)*(1-on/{n}))"
    y_down = f"max(0,min(ih-ih/zoom,(ih-ih/zoom)*on/{n}))"
    if style == "pull_out":
        z, x, y = z_out, x_ctr, y_ctr
    elif style == "pan_right":
        z, x, y = z_hold, x_max, f"(ih-ih/zoom)*0.32"
    elif style == "pan_left":
        z, x, y = z_hold, x_min, f"(ih-ih/zoom)*0.38"
    elif style == "rise":
        z, x, y = z_hold, x_ctr, y_up
    elif style == "fall":
        z, x, y = z_hold, x_ctr, y_down
    else:
        # punch_in / punch_shake
        z, x, y = z_in, x_ctr, f"{y_ctr}-0.12*(ih-ih/zoom)*on/{n}"
    return (
        f"zoompan=z='{z}':x='{x}':y='{y}':"
        f"d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS}"
    )


def _look_filters(shot: dict[str, Any]) -> str:
    """Grade + grain + vignette so it doesn't look like a PNG slideshow."""
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

    error: list[BaseException] = []

    async def _go() -> None:
        communicate = edge_tts.Communicate(spoken, voice or _tts_voice())
        await communicate.save(str(dest))

    def _thread() -> None:
        try:
            asyncio.run(_go())
        except BaseException as e:  # noqa: BLE001 — surface TTS failures as silent clip
            error.append(e)

    worker = threading.Thread(target=_thread, daemon=True)
    worker.start()
    worker.join(timeout=90)
    if worker.is_alive() or error:
        return False
    return dest.is_file() and dest.stat().st_size > 0


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
    """Camera move on the still, grade it, burn subtitles. Always output AAC."""
    frames = max(int(round(duration * FPS)), FPS)
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
    else:
        args += [
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
        ]
    args += [
        "-filter_complex",
        vf,
        "-map",
        "[vout]",
        "-map",
        "2:a",
        "-t",
        f"{duration:.2f}",
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
        "-shortest",
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
    """Crossfade trimmed clips. Timeline edits never rewrite per-shot source files."""
    from tools.drama_timeline import junction_fade_sec, resolve_transition_name

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
    durations: list[float] = []
    for i, spec in enumerate(specs):
        path = spec["path"]
        trim_in = float(spec.get("trim_in") or 0)
        trim_out = float(spec.get("trim_out") or 0)
        vol = float(spec.get("volume") or 1.0)
        probe = _probe_duration(path)
        end = max(trim_in + 0.25, probe - trim_out)
        play = max(0.25, end - trim_in)
        durations.append(play)
        inputs += ["-i", str(path)]
        parts.append(
            f"[{i}:v]trim=start={trim_in:.3f}:end={end:.3f},setpts=PTS-STARTPTS[v{i}p]"
        )
        parts.append(
            f"[{i}:a]atrim=start={trim_in:.3f}:end={end:.3f},asetpts=PTS-STARTPTS,volume={vol:.2f}[a{i}p]"
        )

    last_v = "[v0p]"
    last_a = "[a0p]"
    fade0 = junction_fade_sec(specs[0], fade_sec)
    offset = durations[0] - fade0
    for i in range(1, len(specs)):
        prev = specs[i - 1]
        fade_i = junction_fade_sec(prev, fade_sec)
        trans = resolve_transition_name(prev, i, auto_fn=_transition_name)
        v_out = f"[v{i}x]"
        a_out = f"[a{i}x]"
        parts.append(
            f"{last_v}[v{i}p]xfade=transition={trans}:duration={fade_i:.2f}:offset={offset:.3f}{v_out}"
        )
        parts.append(f"{last_a}[a{i}p]acrossfade=d={fade_i:.2f}{a_out}")
        last_v, last_a = v_out, a_out
        offset += durations[i] - fade_i

    args = [
        "-y",
        *inputs,
        "-filter_complex",
        ";".join(parts),
        "-map",
        last_v,
        "-map",
        last_a,
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
        return "xfade"
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
    rel = (shot.get("assets") or {}).get(layer)
    if not rel:
        raise ValueError(f"镜头 {shot.get('n')} 缺少 {layer} 路径")
    path = resolve_safe(rel)
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
    if not wanted:
        return {"n": shot.get("n"), "rebuilt": [], "skipped": "locked_or_empty"}

    assets = shot.setdefault("assets", {})
    scene = _path_for(shot, "scene")
    overlay = _path_for(shot, "overlay")
    voice = _path_for(shot, "voice")
    clip = _path_for(shot, "clip")

    rebuilt: list[str] = []
    used_tts = False
    used_ai = False
    cards = load_characters(slug)
    cast = resolve_shot_characters(shot, cards)

    if "scene" in wanted:
        generated = generate_shot_candidates(slug, episode, shot, title=title)
        used_ai = any(item.get("source") == "ai" for item in generated)
        if not _path_for(shot, "scene").is_file() and generated:
            apply_candidate_to_scene(shot, generated[0])
        rebuilt.append("scene")

    if "overlay" in wanted:
        _draw_subtitle_overlay(shot, overlay)
        rebuilt.append("overlay")

    duration = float(shot.get("duration") or 5)
    if "voice" in wanted:
        speech = spoken_text(shot.get("对白") or "", shot.get("字幕") or "")
        has_audio = _tts_to_file(speech, voice, voice=primary_voice(cast)) if speech else False
        if has_audio:
            used_tts = True
            duration = max(duration, _probe_duration(voice) + 0.25)
            shot["duration"] = round(duration, 2)
        elif voice.exists():
            try:
                voice.unlink()
            except OSError:
                pass
        rebuilt.append("voice")
    elif voice.is_file() and voice.stat().st_size > 0:
        duration = max(duration, _probe_duration(voice) + 0.25)
        shot["duration"] = round(duration, 2)

    if "clip" in wanted:
        if not scene.is_file():
            raise RuntimeError(f"镜头 {shot.get('n')} 没有画面，请先生成 scene")
        if not overlay.is_file():
            _draw_subtitle_overlay(shot, overlay)
            if "overlay" not in rebuilt:
                rebuilt.append("overlay")
        shot["camera"] = shot.get("camera") or _camera_style(shot)
        audio = voice if voice.is_file() and voice.stat().st_size > 0 else None
        _encode_clip(scene, overlay, clip, duration, audio, shot)
        rebuilt.append("clip")
        assets["clip"] = assets.get("clip") or str(clip)

    remaining = [layer for layer in (shot.get("dirty") or []) if layer not in rebuilt]
    shot["dirty"] = remaining
    shot["status"] = "rendered" if not remaining and clip.is_file() else "dirty"
    return {
        "n": shot.get("n"),
        "rebuilt": rebuilt,
        "duration": shot.get("duration"),
        "camera": shot.get("camera"),
        "scene_source": shot.get("scene_source"),
        "ai": used_ai,
        "tts": used_tts,
        "clip": assets.get("clip"),
    }


def assemble_episode(doc: dict[str, Any]) -> str:
    from tools.drama_timeline import build_assemble_specs

    out_rel = doc.get("output") or output_rel(str(doc["slug"]), int(doc["episode"]))
    out_path = resolve_safe(out_rel)
    specs, fade_sec = build_assemble_specs(doc, probe_duration=_probe_duration)
    ready = [s for s in specs if not s.get("missing")]
    if not ready:
        raise FileNotFoundError("没有可拼接的镜头成片")
    assemble = _assemble_clips(ready, out_path, fade_sec=fade_sec)
    doc["assemble"] = assemble
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
) -> dict[str, Any]:
    """Render dirty (or all) shots independently, then assemble epNN.mp4."""
    doc = sync_shots_doc(slug, episode, markdown, title=title)
    ep_title = str(title or doc.get("title") or f"第{episode}集")
    rebuilt: list[int] = []
    skipped: list[int] = []
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
        info = render_shot_layers(slug, episode, shot, layers, title=ep_title)
        if info.get("rebuilt"):
            rebuilt.append(int(shot["n"]))
        else:
            skipped.append(int(shot["n"]))
        shot["status"] = "rendered" if not shot.get("dirty") else shot.get("status")
    out_path = resolve_safe(str(doc.get("output") or output_rel(slug, episode)))
    if rebuilt or not out_path.is_file():
        assemble = assemble_episode(doc)
    else:
        assemble = str(doc.get("assemble") or "unchanged")
        save_doc(doc)
    return _episode_result(doc, {"rebuilt_shots": rebuilt, "skipped_shots": skipped, "assemble": assemble})


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
    """Patch one shot, rebuild only requested layers, then reassemble the episode."""
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

    requested = parse_layers(layers, extra=("assemble",)) if layers else []
    wanted = [layer for layer in requested if layer in LAYERS]
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
    if "clip" not in wanted and any(layer in wanted for layer in ("scene", "overlay", "voice")):
        if "clip" not in locked:
            wanted = [*wanted, "clip"]
    wanted = [layer for layer in wanted if layer not in locked]

    ep_title = str(title or doc.get("title") or f"第{episode}集")
    info = render_shot_layers(slug, episode, shot, wanted, title=ep_title)
    assemble = assemble_episode(doc)
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
        },
    )
