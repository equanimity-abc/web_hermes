"""Q4 smoke: identity cosine; fail dirties scene/motion not voice; skipped is not pass."""

from __future__ import annotations

import json
import os
import shutil
from io import BytesIO

os.environ["IMAGE_GEN_PROVIDER"] = "none"

import agent.loop  # noqa: F401

from PIL import Image

from tools.drama_i2v import _motion_prompt
from tools.drama_qc import qc_passed, qc_shot_identity
from tools.drama_shots import load_doc, save_doc, shot_assets
from tools.drama_studio import (
    lock_character_ref,
    qc_shot,
    save_character,
    save_script,
    upload_character_ref,
)
from tools.workspace import resolve_safe

SLUG = "q4-smoke"
MD = """# Q4 验收
- 时长: 8s
- 钩子: 开场
- 悬念: 结尾

## 分镜
### Shot 1 (0-4s)
- 画面: 主角特写
- 对白: 站住
- 字幕:
- 角色: hero

### Shot 2 (4-8s)
- 画面: 主角再特写
- 对白: 别走
- 字幕:
- 角色: hero
"""

SAME = (192, 160, 96)
DIFF = (16, 32, 180)


def _shot(doc: dict, n: int) -> dict:
    return next(s for s in doc["shots"] if int(s["n"]) == n)


def _png_bytes(color: tuple[int, int, int]) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, "PNG")
    return buf.getvalue()


def _png(path, color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), color).save(path, "PNG")


def main() -> None:
    root = resolve_safe(f"dramas/{SLUG}")
    try:
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True)
        (root / "project.json").write_text(
            json.dumps({"slug": SLUG, "title": "Q4", "logline": "identity", "episodes": []}, ensure_ascii=False),
            encoding="utf-8",
        )
        save_character(SLUG, {"id": "hero", "name": "主角", "look": "黑发短须", "voice": "zh-CN-YunxiNeural"})
        upload_character_ref(SLUG, "hero", _png_bytes(SAME))
        lock_character_ref(SLUG, "hero", True)
        save_script(SLUG, 1, MD)

        doc = load_doc(SLUG, 1)
        for n in (1, 2):
            assets = shot_assets(SLUG, 1, n)
            _png(resolve_safe(assets["scene"]), SAME)
            shot = _shot(doc, n)
            shot.setdefault("assets", {})["scene"] = assets["scene"]
            shot["speaker"] = "hero"
            shot["kind"] = "dialogue"
            shot["size"] = "CU"
            shot["dirty"] = []
            shot["status"] = "rendered"
        save_doc(doc)

        # 1) locked ref + consecutive same-ish images → pass, do not dirty voice
        doc = load_doc(SLUG, 1)
        s2 = _shot(doc, 2)
        result = qc_shot_identity(SLUG, 1, s2, apply=True)
        save_doc(doc)
        assert result["status"] == "ok", result
        assert result["pass"] is True, result
        assert qc_passed(result) is True
        assert float(result["cosine"]) >= 0.65, result
        assert "voice" not in (s2.get("dirty") or [])
        assert "voice" not in (result.get("dirtied") or [])
        reloaded = _shot(load_doc(SLUG, 1), 2)
        assert isinstance(reloaded.get("identity"), dict), reloaded.get("identity")
        assert reloaded["identity"].get("pass") is True

        # 4) motion prompt still eats character look / locked-ref wording
        s2["_slug"] = SLUG
        prompt = _motion_prompt(s2)
        assert "黑发短须" in prompt or "locked character reference" in prompt, prompt
        assert "same face as locked character reference" in prompt

        # 2) scene very different from locked ref → fail, dirty scene/motion, never voice
        doc = load_doc(SLUG, 1)
        s2 = _shot(doc, 2)
        _png(resolve_safe((s2.get("assets") or {})["scene"]), DIFF)
        s2["dirty"] = []
        fail = qc_shot_identity(SLUG, 1, s2, apply=True)
        save_doc(doc)
        assert fail["status"] == "ok", fail
        assert fail["pass"] is False, fail
        assert qc_passed(fail) is False
        assert float(fail["cosine"]) < 0.65, fail
        dirty = s2.get("dirty") or []
        assert "scene" in dirty and "motion" in dirty, dirty
        assert "voice" not in dirty
        assert "voice" not in (fail.get("dirtied") or [])
        assert "重抽首帧" in str(fail.get("hint") or "")
        assert "不重配音" in str(fail.get("hint") or s2.get("identity_hint") or "")

        # 3) no locked ref, first shot → skipped, never a pass
        lock_character_ref(SLUG, "hero", False)
        skipped = qc_shot(SLUG, 1, 1)
        assert skipped["identity"]["status"] == "skipped", skipped
        assert skipped["passed"] is False
        assert qc_passed(skipped["identity"]) is False
        skip_dirty = (skipped.get("shot") or {}).get("dirty") or []
        assert "voice" not in skip_dirty or "voice" not in (skipped["identity"].get("dirtied") or [])

        print("Q4 smoke ok")
    finally:
        if root.exists():
            shutil.rmtree(root)


if __name__ == "__main__":
    main()
