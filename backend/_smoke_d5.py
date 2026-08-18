"""D5 smoke: 4 candidates, choose swaps scene only, voice file untouched."""

from __future__ import annotations

import hashlib
import json
import os
import shutil

os.environ["IMAGE_GEN_PROVIDER"] = "none"

import agent.loop  # noqa: F401

from config import config
from tools.drama_shots import load_doc, shot_assets
from tools.drama_studio import choose_candidate, generate_candidates, save_script, upload_shot_scene
from tools.workspace import resolve_safe

config.IMAGE_GEN_PROVIDER = "none"

SLUG = "d5-smoke"
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)
UPLOAD = PNG
MD = """# D5 验收
- 时长: 6s
- 钩子: 开场
- 悬念: 结尾

## 分镜
### Shot 1 (0-6s)
- 画面: 候选墙测试
- 对白: 旁白：换图不重配音
- 字幕: 换图不重配音
"""


def _shot(doc: dict) -> dict:
    return doc["shots"][0]


def _write_silent_mp3(path) -> bool:
    import shutil
    import subprocess

    if not shutil.which("ffmpeg"):
        return False
    proc = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono",
            "-t",
            "1",
            "-q:a",
            "9",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0 and path.is_file() and path.stat().st_size > 0


def main() -> None:
    root = resolve_safe(f"dramas/{SLUG}")
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    (root / "project.json").write_text(
        json.dumps({"slug": SLUG, "title": "D5 验收", "logline": "候选墙", "episodes": []}, ensure_ascii=False),
        encoding="utf-8",
    )

    save_script(SLUG, 1, MD)
    doc = load_doc(SLUG, 1)
    assets = shot_assets(SLUG, 1, 1)
    voice_path = resolve_safe(assets["voice"])
    voice_path.parent.mkdir(parents=True, exist_ok=True)
    if not _write_silent_mp3(voice_path):
        voice_path.write_bytes(b"FAKE-VOICE-BYTES-D5")
    voice_hash = hashlib.sha256(voice_path.read_bytes()).hexdigest()

    gen = generate_candidates(SLUG, 1, 1, count=4)
    doc = load_doc(SLUG, 1)
    shot = _shot(doc)
    assert len(gen["created"]) == 4, gen
    assert len(shot["candidates"]) >= 4, shot
    assert shot["chosen"] == "c1", shot
    assert resolve_safe(assets["scene"]).is_file()

    picked = choose_candidate(SLUG, 1, 1, "c3")
    doc = load_doc(SLUG, 1)
    shot = _shot(doc)
    assert picked["chosen"] == "c3", picked
    assert shot["chosen"] == "c3", shot
    assert "scene" in shot["locked"], shot
    assert hashlib.sha256(voice_path.read_bytes()).hexdigest() == voice_hash
    c3 = resolve_safe(f"dramas/{SLUG}/videos/ep01/shot01_cand_c3.png")
    scene = resolve_safe(assets["scene"])
    assert hashlib.sha256(scene.read_bytes()).hexdigest() == hashlib.sha256(c3.read_bytes()).hexdigest()

    up = upload_shot_scene(SLUG, 1, 1, PNG)
    doc = load_doc(SLUG, 1)
    shot = _shot(doc)
    assert up["chosen"], up
    assert hashlib.sha256(voice_path.read_bytes()).hexdigest() == voice_hash
    assert any(c.get("source") == "upload" for c in shot["candidates"]), shot
    print("D5 smoke ok: choose/upload swap scene, voice unchanged, scene locked")


if __name__ == "__main__":
    try:
        main()
    finally:
        root = resolve_safe(f"dramas/{SLUG}")
        if root.exists():
            shutil.rmtree(root)
