"""D8 smoke: locked keyframe → I2V motion (mock) or still fallback (fail)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time

os.environ["IMAGE_GEN_PROVIDER"] = "none"

import agent.loop  # noqa: F401

from config import config
from tools.drama_i2v import generate_shot_i2v
from tools.drama_shots import load_doc, save_doc, shot_assets
from tools.drama_studio import generate_i2v_shot, get_render_job, patch_shot, save_script
from tools.drama_video import rerender_shot
from tools.workspace import resolve_safe

config.IMAGE_GEN_PROVIDER = "none"

SLUG = "d8-smoke"
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)
MD = """# D8 验收
- 时长: 4s
- 钩子: 开场
- 悬念: 结尾

## 分镜
### Shot 1 (0-4s)
- 画面: I2V 测试
- 对白: 测试
- 字幕: I2V
"""


def _ffmpeg_ok() -> bool:
    return shutil.which("ffmpeg") is not None


def _shot(doc: dict) -> dict:
    return doc["shots"][0]


def _wait_job(job_id: str, *, timeout: float = 120.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = get_render_job(job_id)
        if job["status"] in ("done", "error", "cancelled"):
            return job
        time.sleep(0.3)
    raise TimeoutError(job_id)


def _write_silent_mp3(path) -> None:
    proc = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono",
            "-t",
            "1.5",
            "-q:a",
            "9",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or "ffmpeg mp3 failed")


def main() -> None:
    if not _ffmpeg_ok():
        print("skip D8 smoke: ffmpeg not in PATH")
        return

    root = resolve_safe(f"dramas/{SLUG}")
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    (root / "project.json").write_text(
        json.dumps({"slug": SLUG, "title": "D8 验收", "logline": "I2V", "episodes": []}, ensure_ascii=False),
        encoding="utf-8",
    )

    save_script(SLUG, 1, MD)
    doc = load_doc(SLUG, 1)
    shot = _shot(doc)
    assets = shot_assets(SLUG, 1, 1)
    scene = resolve_safe(assets["scene"])
    overlay = resolve_safe(assets["overlay"])
    voice = resolve_safe(assets["voice"])
    scene.parent.mkdir(parents=True, exist_ok=True)
    scene.write_bytes(PNG)
    overlay.write_bytes(PNG)
    _write_silent_mp3(voice)

    patch_shot(SLUG, 1, 1, {"lock": "scene", "i2v": "auto"})
    doc = load_doc(SLUG, 1)
    shot = _shot(doc)

    config.I2V_PROVIDER = "mock"
    info = generate_shot_i2v(SLUG, 1, shot, force=True)
    save_doc(doc)
    motion = resolve_safe(assets["motion"])
    assert info["i2v_source"] == "ai", info
    assert motion.is_file() and motion.stat().st_size > 500, motion

    clip_result = rerender_shot(SLUG, 1, 1, layers=["clip"])
    doc = load_doc(SLUG, 1)
    shot = _shot(doc)
    clip = resolve_safe(assets["clip"])
    assert clip.is_file() and clip.stat().st_size > 1000, clip
    assert shot.get("i2v_source") == "ai", shot
    assert clip_result.get("assemble"), clip_result

    config.I2V_PROVIDER = "fail"
    info_fail = generate_shot_i2v(SLUG, 1, shot, force=True)
    save_doc(doc)
    assert info_fail["i2v_source"] == "none", info_fail
    assert info_fail.get("fallback") == "still_zoompan", info_fail

    clip_result2 = rerender_shot(SLUG, 1, 1, layers=["clip"])
    doc = load_doc(SLUG, 1)
    shot = _shot(doc)
    assert shot.get("i2v_source") == "fallback", shot
    assert clip.is_file() and clip.stat().st_size > 1000, clip
    assert clip_result2.get("assemble"), clip_result2

    config.I2V_PROVIDER = "mock"
    patch_shot(SLUG, 1, 1, {"i2v": "on"})
    queued = generate_i2v_shot(SLUG, 1, 1)
    assert queued.get("job_id"), queued
    done = _wait_job(queued["job_id"], timeout=120.0)
    assert done["status"] == "done", done
    assert done.get("result", {}).get("i2v_source") == "ai", done

    print("D8 smoke ok: mock I2V motion + fail fallback + queued i2v_shot")


if __name__ == "__main__":
    try:
        main()
    finally:
        time.sleep(0.5)
        root = resolve_safe(f"dramas/{SLUG}")
        if root.exists():
            try:
                shutil.rmtree(root)
            except OSError:
                pass
