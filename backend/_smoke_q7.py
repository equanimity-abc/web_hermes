"""Q7 smoke: episode QC four checks; skipped cannot pass; loudness only remixes mix."""

from __future__ import annotations

import json
import os
import shutil
from io import BytesIO

os.environ["IMAGE_GEN_PROVIDER"] = "none"

import agent.loop  # noqa: F401

from PIL import Image

from tools.drama_qc import (
    check_allows_pass,
    qc_passed,
    qc_shot_identity,
    score_ssim_paths,
)
from tools.drama_shots import load_doc, save_doc, shot_assets
from tools.drama_studio import (
    DramaBadRequest,
    lock_character_ref,
    pass_episode_qc,
    qc_episode,
    reject_shot_qc,
    save_character,
    save_script,
    upload_character_ref,
)
from tools.loader import plugin_prompt_hints
from tools.workspace import resolve_safe

SLUG = "q7-smoke"
MD = """# Q7 验收
- 时长: 8s
- 钩子: 开场
- 悬念: 结尾

## 分镜
### Shot 1 (0-4s)
- 画面: 宫殿远景
- 对白:
- 字幕:

### Shot 2 (4-8s)
- 画面: 主角特写
- 对白: 站住
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


def _pass_check(**extra):
    return {"status": "ok", "pass": True, "required": True, **extra}


def main() -> None:
    root = resolve_safe(f"dramas/{SLUG}")
    try:
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True)
        (root / "project.json").write_text(
            json.dumps({"slug": SLUG, "title": "Q7", "logline": "qc", "episodes": []}, ensure_ascii=False),
            encoding="utf-8",
        )
        save_character(SLUG, {"id": "hero", "name": "主角", "look": "黑发", "voice": "zh-CN-YunxiNeural"})
        save_script(SLUG, 1, MD)
        doc = load_doc(SLUG, 1)
        s1 = _shot(doc, 1)
        s1["kind"] = "establishing"
        s1["角色"] = []
        s1["speaker"] = ""
        s1["dirty"] = []
        s2 = _shot(doc, 2)
        s2["kind"] = "dialogue"
        s2["size"] = "CU"
        s2["speaker"] = "hero"
        s2["角色"] = ["hero"]
        s2["dirty"] = []
        assets = shot_assets(SLUG, 1, 2)
        scene = resolve_safe(assets["scene"])
        _png(scene, SAME)
        s2.setdefault("assets", {})["scene"] = assets["scene"]
        clip_rel = assets["clip"]
        clip_path = resolve_safe(clip_rel)
        clip_path.parent.mkdir(parents=True, exist_ok=True)
        clip_path.write_bytes(b"fake-clip-bytes")
        s2["assets"]["clip"] = clip_rel
        save_doc(doc)

        hints = plugin_prompt_hints()
        assert any("qc_episode" in hint for hint in hints), hints

        same_a = resolve_safe(f"dramas/{SLUG}/tmp_a.png")
        same_b = resolve_safe(f"dramas/{SLUG}/tmp_b.png")
        diff_b = resolve_safe(f"dramas/{SLUG}/tmp_d.png")
        _png(same_a, SAME)
        _png(same_b, SAME)
        _png(diff_b, DIFF)
        hi = score_ssim_paths([same_a, same_b])
        lo = score_ssim_paths([same_a, diff_b])
        assert hi.get("status") == "ok" and float(hi["ssim"]) >= 0.85, hi
        assert lo.get("status") == "ok" and float(lo["ssim"]) < 0.85, lo

        result = qc_episode(SLUG, 1)
        qc = result["qc"]
        assert qc["verdict"] == "待修", qc
        assert qc["can_pass"] is False, qc
        assert "skipped" in str(qc.get("block_reason") or "").lower() or "不得记为通过" in str(qc.get("block_reason") or ""), qc
        row1 = next(r for r in qc["shots"] if r["n"] == 1)
        assert row1["identity"]["status"] == "n/a", row1["identity"]
        assert check_allows_pass(row1["identity"]) is True
        row2 = next(r for r in qc["shots"] if r["n"] == 2)
        assert row2["identity"]["status"] == "skipped", row2["identity"]
        assert qc_passed(row2["identity"]) is False
        assert check_allows_pass(row2["identity"]) is False

        try:
            pass_episode_qc(SLUG, 1)
            raise AssertionError("skipped must not pass the episode")
        except DramaBadRequest as e:
            assert "通过" in str(e) or "skipped" in str(e).lower() or "不得" in str(e), e

        upload_character_ref(SLUG, "hero", _png_bytes(SAME))
        lock_character_ref(SLUG, "hero", True)
        doc = load_doc(SLUG, 1)
        s2 = _shot(doc, 2)
        voice_rel = shot_assets(SLUG, 1, 2)["voice"]
        voice_path = resolve_safe(voice_rel)
        voice_path.parent.mkdir(parents=True, exist_ok=True)
        voice_path.write_bytes(b"ID3fake-voice")
        s2.setdefault("assets", {})["voice"] = voice_rel
        s2["dirty"] = []
        ident = qc_shot_identity(SLUG, 1, s2, apply=True)
        save_doc(doc)
        assert ident["status"] == "ok" and ident["pass"] is True, ident
        assert "voice" not in (s2.get("dirty") or [])

        _png(resolve_safe((s2.get("assets") or {})["scene"]), DIFF)
        s2["dirty"] = []
        fail = qc_shot_identity(SLUG, 1, s2, apply=True)
        save_doc(doc)
        assert fail["pass"] is False, fail
        dirty = s2.get("dirty") or []
        assert "scene" in dirty and "motion" in dirty, dirty
        assert "voice" not in dirty
        assert voice_path.read_bytes() == b"ID3fake-voice"

        _png(resolve_safe((s2.get("assets") or {})["scene"]), SAME)
        s2["dirty"] = [x for x in dirty if x != "voice"]
        qc_shot_identity(SLUG, 1, s2, apply=True)
        clip_hash = clip_path.read_bytes()
        for shot in doc["shots"]:
            bundle = shot.setdefault("qc", {})
            bundle["identity"] = shot.get("identity") or _pass_check()
            if str((bundle.get("identity") or {}).get("status") or "") == "n/a":
                bundle["identity"]["required"] = False
            bundle["lip"] = {"status": "n/a", "pass": False, "required": False, "reason": "smoke"}
            bundle["flicker"] = _pass_check(ssim=0.99, method="ssim")
        doc.setdefault("qc", {})["loudness"] = _pass_check(lufs=-14.0, method="ebur128", lufs_target=-14)
        save_doc(doc)

        ep = pass_episode_qc(SLUG, 1)
        assert ep["qc"]["verdict"] == "通过", ep["qc"]
        assert ep["qc"]["can_pass"] is True, ep["qc"]
        assert clip_path.read_bytes() == clip_hash
        assert voice_path.read_bytes() == b"ID3fake-voice"

        rejected = reject_shot_qc(SLUG, 1, 2)
        assert rejected["qc"]["verdict"] == "待修", rejected["qc"]
        row = next(r for r in rejected["qc"]["shots"] if r["n"] == 2)
        assert row["verdict"] == "待修", row
        assert clip_path.read_bytes() == clip_hash

        print("Q7 smoke ok")
    finally:
        if root.exists():
            shutil.rmtree(root)


if __name__ == "__main__":
    main()
