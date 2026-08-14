"""Local 9:16 episode renderer: shot cards + TTS + ffmpeg.

Used by tiktok_drama action=render_episode. Does not touch agent/loop.py.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import threading
import urllib.parse
import zlib
from pathlib import Path
from typing import Any

from config import config
from tools.workspace import resolve_safe

WIDTH = 1080
HEIGHT = 1920
FPS = 25
ZOOM_W = 1350
ZOOM_H = 2400

_SHOT_HEAD = re.compile(
    r"^###\s*Shot\s+(\d+)\s*(?:\(([^)]*)\))?\s*$",
    re.IGNORECASE,
)
_FIELD = re.compile(r"^-\s*(画面|对白|字幕)\s*[:：]\s*(.*)\s*$")
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


def _scene_prompt(title: str, shot: dict[str, Any]) -> str:
    scene = (shot.get("画面") or "").strip() or "cinematic Chinese myth scene"
    return (
        "vertical 9:16 cinematic Chinese animation still frame, "
        f"{title or 'Journey to the West'}, {scene}, "
        "classic 西游记 manhua / anime illustration, Monkey King Sun Wukong "
        "gold headband tiger-skin skirt Ruyi Jingu Bang, heavenly palace clouds, "
        "dramatic lighting, highly detailed, character in frame, "
        "no text, no letters, no subtitles, no watermark, no UI"
    )


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


def _draw_fallback_scene(shot: dict[str, Any], dest: Path) -> None:
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

    for i, color in enumerate(colors):
        layer = Image.new("RGB", (ZOOM_W, ZOOM_H), color)
        mask = Image.new("L", (ZOOM_W, ZOOM_H), 0)
        md = ImageDraw.Draw(mask)
        cy = int(ZOOM_H * (0.25 + i * 0.22))
        md.ellipse((-400, cy - 500, ZOOM_W + 400, cy + 500), fill=180 - i * 40)
        mask = mask.filter(ImageFilter.GaussianBlur(80))
        img = Image.composite(layer, img, mask)

    draw = ImageDraw.Draw(img)
    draw.ellipse((ZOOM_W // 2 - 90, 520, ZOOM_W // 2 + 90, 980), outline="#d4a017", width=8)
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "PNG")


def _generate_scene_image(prompt: str, dest: Path, *, seed: int) -> bool:
    provider = (config.IMAGE_GEN_PROVIDER or "pollinations").strip().lower()
    if provider in ("", "none", "off"):
        return False
    quoted = urllib.parse.quote(prompt)
    model = config.IMAGE_GEN_MODEL or "flux"
    url = (
        f"https://image.pollinations.ai/prompt/{quoted}"
        f"?width=768&height=1344&model={urllib.parse.quote(model)}"
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
    """Ken Burns: zoom / pan so stills feel like camera moves."""
    scene = shot.get("画面") or ""
    z_inc = max(0.0006, 0.14 / max(frames, 1))
    n = int(shot.get("n") or 1)
    if any(k in scene for k in ("天", "宫", "云", "冲")):
        return (
            f"zoompan=z='min(1.0+{z_inc}*on,1.16)':"
            f"x='iw/2-(iw/zoom/2)':"
            f"y='max(0,ih/2-(ih/zoom/2)-on*0.45)':"
            f"d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS}"
        )
    if n % 2 == 0:
        return (
            f"zoompan=z='max(1.16-{z_inc}*on,1.0)':"
            f"x='iw/2-(iw/zoom/2)':"
            f"y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS}"
        )
    return (
        f"zoompan=z='min(1.0+{z_inc}*on,1.16)':"
        f"x='iw/2-(iw/zoom/2)':"
        f"y='ih/2-(ih/zoom/2)':"
        f"d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS}"
    )


def _run_ffmpeg(args: list[str], *, cwd: Path | None = None) -> None:
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(
        [_ffmpeg_bin(), "-hide_banner", "-loglevel", "error", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=180,
        creationflags=creationflags,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "ffmpeg failed").strip()
        raise RuntimeError(err[:800] or f"ffmpeg exit {proc.returncode}")


def _tts_to_file(text: str, dest: Path) -> bool:
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
        communicate = edge_tts.Communicate(spoken, _tts_voice())
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
    """Ken Burns on the scene still, then burn subtitles. Always output AAC."""
    frames = max(int(round(duration * FPS)), FPS)
    fade = min(0.28, max(duration * 0.08, 0.12))
    fade_out_at = max(duration - fade, 0.05)
    motion = _motion_expr(shot, frames)
    vf = (
        f"[0:v]scale={ZOOM_W}:{ZOOM_H}:force_original_aspect_ratio=increase,"
        f"crop={ZOOM_W}:{ZOOM_H},{motion},"
        f"fade=t=in:st=0:d={fade:.2f},"
        f"fade=t=out:st={fade_out_at:.2f}:d={fade:.2f}[v];"
        f"[v][1:v]overlay=0:0:format=auto,format=yuv420p[vout]"
    )
    args = ["-y", "-loop", "1", "-i", str(scene), "-i", str(overlay)]
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
    _run_ffmpeg(args)


def render_episode_video(
    slug: str,
    episode: int,
    markdown: str,
    *,
    title: str = "",
) -> dict[str, Any]:
    if not ffmpeg_available():
        raise RuntimeError("未找到 ffmpeg，请先安装并加入 PATH")

    parsed = parse_episode_markdown(markdown)
    shots = parsed["shots"]
    if not shots:
        raise ValueError("剧本里没有分镜（需要 ### Shot N (0-3s) 格式）")

    ep_title = title or parsed["title"] or f"第{episode}集"
    rel_dir = f"dramas/{slug}/videos/ep{episode:02d}"
    out_rel = f"dramas/{slug}/videos/ep{episode:02d}.mp4"
    work = resolve_safe(rel_dir)
    work.mkdir(parents=True, exist_ok=True)
    out_path = resolve_safe(out_rel)

    clips: list[str] = []
    used_tts = False
    used_ai = 0
    for shot in shots:
        stem = f"shot{int(shot['n']):02d}"
        scene = work / f"{stem}_scene.png"
        overlay = work / f"{stem}_overlay.png"
        mp3 = work / f"{stem}.mp3"
        clip = work / f"{stem}.mp4"
        prompt = _scene_prompt(ep_title, shot)
        seed = zlib.crc32(f"{slug}:{episode}:{shot['n']}:{shot.get('画面')}".encode()) & 0x7FFFFFFF
        ai_ok = _generate_scene_image(prompt, scene, seed=seed)
        if ai_ok:
            used_ai += 1
        else:
            _draw_fallback_scene(shot, scene)
        shot["scene"] = "ai" if ai_ok else "fallback"
        _draw_subtitle_overlay(shot, overlay)

        speech = spoken_text(shot.get("对白") or "", shot.get("字幕") or "")
        has_audio = _tts_to_file(speech, mp3) if speech else False
        duration = float(shot.get("duration") or 5)
        if has_audio:
            used_tts = True
            audio_dur = _probe_duration(mp3)
            duration = max(duration, audio_dur + 0.25)
            _encode_clip(scene, overlay, clip, duration, mp3, shot)
        else:
            _encode_clip(scene, overlay, clip, duration, None, shot)
        clips.append(clip.name)
        shot["clip"] = f"{rel_dir}/{clip.name}"
        shot["duration"] = round(duration, 2)
        shot["scene"] = "ai" if scene.exists() and used_ai else "fallback"

    list_file = work / "concat.txt"
    list_file.write_text(
        "\n".join(f"file '{name}'" for name in clips) + "\n",
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
        cwd=work,
    )

    shots_json = work / "shots.json"
    shots_json.write_text(
        json.dumps(parsed, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    play_url = f"/api/workspace/file?path={out_rel}"
    return {
        "slug": slug,
        "episode": episode,
        "title": ep_title,
        "path": out_rel,
        "play_url": play_url,
        "bytes": out_path.stat().st_size if out_path.is_file() else 0,
        "shots": len(shots),
        "ai_scenes": used_ai,
        "tts": used_tts,
        "workspace": str(config.WORKSPACE_DIR),
    }
