"""D6 smoke: trim shot 4 + change transition, export reassembles without touching source clips."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess

os.environ["IMAGE_GEN_PROVIDER"] = "none"

import agent.loop  # noqa: F401

from config import config
from tools.drama_shots import load_doc, save_doc, shot_assets
from tools.drama_studio import export_episode, patch_shot, patch_timeline, save_script
from tools.workspace import resolve_safe

config.IMAGE_GEN_PROVIDER = "none"

SLUG = "d6-smoke"
MD = """# D6 验收
- 时长: 20s
- 钩子: 开场
- 悬念: 结尾

## 分镜
### Shot 1 (0-3s)
- 画面: 镜一
- 对白:
- 字幕:
### Shot 2 (3-6s)
- 画面: 镜二
- 对白:
- 字幕:
### Shot 3 (6-9s)
- 画面: 镜三
- 对白:
- 字幕:
### Shot 4 (9-12s)
- 画面: 镜四
- 对白:
- 字幕:
"""


def _ffmpeg_ok() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _write_clip(path, *, color: str, duration: float = 3.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=1080x1920:d={duration}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={duration}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or "ffmpeg failed")


def main() -> None:
    if not _ffmpeg_ok():
        print("skip D6 smoke: ffmpeg/ffprobe not in PATH")
        return

    root = resolve_safe(f"dramas/{SLUG}")
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    (root / "project.json").write_text(
        json.dumps({"slug": SLUG, "title": "D6 验收", "logline": "时间线", "episodes": []}, ensure_ascii=False),
        encoding="utf-8",
    )

    save_script(SLUG, 1, MD)
    colors = ["red", "green", "blue", "orange"]
    for n, color in enumerate(colors, start=1):
        assets = shot_assets(SLUG, 1, n)
        _write_clip(resolve_safe(assets["clip"]), color=color, duration=3.0)

    doc = load_doc(SLUG, 1)
    for shot in doc["shots"]:
        shot["dirty"] = []
        shot["status"] = "rendered"
    save_doc(doc)

    clip4 = resolve_safe(shot_assets(SLUG, 1, 4)["clip"])
    clip_hash = hashlib.sha256(clip4.read_bytes()).hexdigest()

    patch_shot(SLUG, 1, 4, {"trim_out": 0.4, "transition": "wipeleft"})
    out1 = export_episode(SLUG, 1)
    ep_mp4 = resolve_safe(f"dramas/{SLUG}/videos/ep01.mp4")
    assert ep_mp4.is_file() and ep_mp4.stat().st_size > 1000, out1
    assert hashlib.sha256(clip4.read_bytes()).hexdigest() == clip_hash

    doc = load_doc(SLUG, 1)
    shot4 = next(s for s in doc["shots"] if int(s["n"]) == 4)
    assert float(shot4.get("trim_out") or 0) == 0.4, shot4
    assert shot4.get("transition") == "wipeleft", shot4

    tl = patch_timeline(SLUG, 1, {"order": [4, 3, 2, 1]})
    assert tl["timeline"]["order"][:4] == [4, 3, 2, 1], tl
    export_episode(SLUG, 1)
    assert hashlib.sha256(clip4.read_bytes()).hexdigest() == clip_hash

    print("D6 smoke ok: trim/transition export, source clip unchanged, reorder saved")


if __name__ == "__main__":
    try:
        main()
    finally:
        root = resolve_safe(f"dramas/{SLUG}")
        if root.exists():
            shutil.rmtree(root)
