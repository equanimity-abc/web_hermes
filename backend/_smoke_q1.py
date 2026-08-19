"""Q1 smoke: BGM mix at assemble only; license gate; clip hashes unchanged."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess

os.environ["IMAGE_GEN_PROVIDER"] = "none"

import agent.loop  # noqa: F401

from config import config
from tools.drama_audio import catalog_rel
from tools.drama_shots import load_doc, save_doc, shot_assets
from tools.drama_studio import (
    DramaBadRequest,
    export_episode,
    mix_episode,
    patch_mix_episode,
    save_script,
    upload_episode_bgm,
)
from tools.workspace import resolve_safe

config.IMAGE_GEN_PROVIDER = "none"

SLUG = "q1-smoke"
MD = """# Q1 验收
- 时长: 8s
- 钩子: 开场
- 悬念: 结尾

## 分镜
### Shot 1 (0-4s)
- 画面: 镜一
- 对白: 你好
- 字幕:

### Shot 2 (4-8s)
- 画面: 镜二
- 对白: 换曲
- 字幕:
"""


def _ffmpeg_ok() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _write_clip(path, *, color: str, duration: float = 4.0) -> None:
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


def _write_bgm(path, *, freq: int, duration: float = 10.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={freq}:duration={duration}",
            "-c:a",
            "pcm_s16le",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or "ffmpeg bgm failed")


def _sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if not _ffmpeg_ok():
        print("skip Q1 smoke: ffmpeg/ffprobe not in PATH")
        return

    root = resolve_safe(f"dramas/{SLUG}")
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    (root / "project.json").write_text(
        json.dumps({"slug": SLUG, "title": "Q1 验收", "logline": "音频分轨", "episodes": []}, ensure_ascii=False),
        encoding="utf-8",
    )

    save_script(SLUG, 1, MD)
    colors = ["red", "green"]
    clip_paths = []
    for n, color in enumerate(colors, start=1):
        assets = shot_assets(SLUG, 1, n)
        path = resolve_safe(assets["clip"])
        _write_clip(path, color=color, duration=4.0)
        clip_paths.append(path)

    doc = load_doc(SLUG, 1)
    for shot in doc["shots"]:
        shot["dirty"] = []
        shot["status"] = "rendered"
    save_doc(doc)

    hashes0 = [_sha(p) for p in clip_paths]
    ep_mp4 = resolve_safe(f"dramas/{SLUG}/videos/ep01.mp4")
    stem = resolve_safe(f"dramas/{SLUG}/videos/ep01_vo.mp4")

    out0 = export_episode(SLUG, 1)
    assert ep_mp4.is_file() and ep_mp4.stat().st_size > 1000, out0
    assert stem.is_file(), "VO stem missing after assemble"
    hash_ep0 = _sha(ep_mp4)
    assert [_sha(p) for p in clip_paths] == hashes0

    bgm_a = resolve_safe(f"dramas/{SLUG}/audio/tmp_a.wav")
    _write_bgm(bgm_a, freq=220)
    upload_episode_bgm(SLUG, 1, bgm_a.read_bytes(), filename="tmp_a.wav", license_ok=False, title="unlicensed")
    try:
        export_episode(SLUG, 1)
        raise AssertionError("expected unlicensed BGM to refuse export")
    except DramaBadRequest as exc:
        assert "商用权" in str(exc) or "license" in str(exc).lower(), exc
    assert [_sha(p) for p in clip_paths] == hashes0
    assert _sha(ep_mp4) == hash_ep0, "failed export must not overwrite episode mp4"

    upload_episode_bgm(SLUG, 1, bgm_a.read_bytes(), filename="tmp_a.wav", license_ok=True, title="licensed-a")
    out1 = mix_episode(SLUG, 1)
    assert out1.get("mix", {}).get("license", {}).get("ok") is True, out1
    assert ep_mp4.is_file()
    hash_ep1 = _sha(ep_mp4)
    assert hash_ep1 != hash_ep0, "licensed mix should rewrite episode mp4"
    assert [_sha(p) for p in clip_paths] == hashes0

    bgm_b = resolve_safe(f"dramas/{SLUG}/audio/catalog_loop.wav")
    _write_bgm(bgm_b, freq=330)
    catalog_path = resolve_safe(catalog_rel(SLUG))
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(
        json.dumps(
            {
                "tracks": [
                    {
                        "id": "loop1",
                        "title": "免费商用循环",
                        "path": f"dramas/{SLUG}/audio/catalog_loop.wav",
                        "license": "catalog:loop1",
                    }
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    patch_mix_episode(SLUG, 1, {"catalog_id": "loop1"})
    mix_episode(SLUG, 1)
    hash_ep2 = _sha(ep_mp4)
    assert hash_ep2 != hash_ep1, "swap catalog BGM should rewrite episode mp4"
    assert [_sha(p) for p in clip_paths] == hashes0

    print("Q1 smoke ok: license gate, duck mix, clip hashes unchanged")


if __name__ == "__main__":
    try:
        main()
    finally:
        root = resolve_safe(f"dramas/{SLUG}")
        if root.exists():
            shutil.rmtree(root)
