"""Q6 smoke: solo action 3 keys; pose change dirties motion not voice; multi-role refused."""

from __future__ import annotations

import json
import os
import shutil

os.environ["IMAGE_GEN_PROVIDER"] = "none"
os.environ["I2V_PROVIDER"] = "mock"

import agent.loop  # noqa: F401

from PIL import Image

from tools.drama_i2v import generate_shot_i2v
from tools.drama_keys import (
    MIN_KEYS,
    choose_key_pose,
    generate_shot_keys,
    keys_ready,
    lock_key_pose,
)
from tools.drama_models import effective_motion_ladder
from tools.drama_shots import load_doc, save_doc, shot_assets
from tools.drama_studio import DramaBadRequest, generate_keys_shot, save_character, save_script
from tools.workspace import resolve_safe

SLUG = "q6-smoke"
MD = """# Q6 验收
- 时长: 12s
- 钩子: 开场
- 悬念: 结尾

## 分镜
### Shot 1 (0-4s)
- 画面: 宫殿远景
- 对白:
- 字幕:

### Shot 2 (4-8s)
- 画面: 对白特写
- 对白: 站住
- 字幕:
- 角色: hero

### Shot 3 (8-12s)
- 画面: 出剑
- 对白:
- 字幕:
- 角色: hero
"""


def _shot(doc: dict, n: int) -> dict:
    return next(s for s in doc["shots"] if int(s["n"]) == n)


def _png(path, color=(80, 90, 120)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 96), color).save(path, "PNG")


def _voice(path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"ID3fake-voice")


def main() -> None:
    root = resolve_safe(f"dramas/{SLUG}")
    try:
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True)
        (root / "project.json").write_text(
            json.dumps({"slug": SLUG, "title": "Q6", "logline": "keys", "episodes": []}, ensure_ascii=False),
            encoding="utf-8",
        )
        save_character(SLUG, {"id": "hero", "name": "主角", "look": "黑发", "voice": "zh-CN-YunxiNeural"})
        save_character(SLUG, {"id": "villain", "name": "反派", "look": "白发", "voice": "zh-CN-YunxiNeural"})
        save_script(SLUG, 1, MD)
        doc = load_doc(SLUG, 1)
        _shot(doc, 1)["kind"] = "establishing"
        _shot(doc, 2)["kind"] = "dialogue"
        _shot(doc, 2)["size"] = "CU"
        s3 = _shot(doc, 3)
        s3["kind"] = "action"
        s3["size"] = "MS"
        s3["speaker"] = "hero"
        s3["角色"] = ["hero"]
        s3["dirty"] = []
        for n, color in ((1, (40, 50, 70)), (2, (190, 160, 90)), (3, (70, 110, 80))):
            assets = shot_assets(SLUG, 1, n)
            _png(resolve_safe(assets["scene"]), color)
            shot = _shot(doc, n)
            shot.setdefault("assets", {}).update({"scene": assets["scene"], "voice": assets["voice"], "motion": assets["motion"]})
        voice_path = resolve_safe(shot_assets(SLUG, 1, 3)["voice"])
        _voice(voice_path)
        voice_hash = voice_path.read_bytes()
        save_doc(doc)

        try:
            generate_keys_shot(SLUG, 1, 2)
            raise AssertionError("dialogue must refuse keys")
        except DramaBadRequest:
            pass

        duo = dict(_shot(load_doc(SLUG, 1), 3))
        duo["角色"] = ["hero", "villain"]
        try:
            generate_shot_keys(SLUG, 1, duo, count=3)
            raise AssertionError("multi-character action must refuse keys")
        except ValueError as e:
            assert "多角色" in str(e)

        doc = load_doc(SLUG, 1)
        s3 = _shot(doc, 3)
        assert effective_motion_ladder(s3, slug=SLUG) == "L3", "action without keys stays L3"
        info = generate_shot_keys(SLUG, 1, s3, count=3)
        save_doc(doc)
        assert info["count"] >= MIN_KEYS, info
        assert info["voice_rebuilt"] is False
        assert "voice" not in (s3.get("dirty") or []), s3.get("dirty")
        assert "motion" in (s3.get("dirty") or [])
        assert keys_ready(s3)
        assert effective_motion_ladder(s3, slug=SLUG) == "L4", s3
        for key in s3["keys"]:
            assert resolve_safe(key["file"]).is_file(), key
        assert voice_path.read_bytes() == voice_hash

        kid = s3["keys"][1]["id"]
        cid = s3["keys"][1]["candidates"][1]["id"]
        s3["dirty"] = [x for x in (s3.get("dirty") or []) if x != "voice"]
        choose_key_pose(s3, kid, cid)
        save_doc(doc)
        assert "voice" not in (s3.get("dirty") or [])
        assert "motion" in (s3.get("dirty") or [])
        assert voice_path.read_bytes() == voice_hash

        first = s3["keys"][0]
        before = resolve_safe(first["file"]).read_bytes()
        lock_key_pose(s3, first["id"], True)
        generate_shot_keys(SLUG, 1, s3, count=3)
        assert resolve_safe(first["file"]).read_bytes() == before

        s3["i2v"] = "on"
        motion = generate_shot_i2v(SLUG, 1, s3, force=True)
        if motion.get("i2v_source") == "keys":
            assert motion.get("ladder") == "L4"
            assert voice_path.read_bytes() == voice_hash
        save_doc(doc)

        print("Q6 smoke ok")
    finally:
        if root.exists():
            shutil.rmtree(root)


if __name__ == "__main__":
    main()
