"""Q8 smoke: style pack overlay; 古风对话 uses character model; establishing stays cheap."""

from __future__ import annotations

import hashlib
import json
import os
import shutil

os.environ["IMAGE_GEN_PROVIDER"] = "none"

import agent.loop  # noqa: F401

from tools.drama_characters import load_characters, resolve_shot_characters
from tools.drama_models import models_rel
from tools.drama_shots import load_doc, save_doc, shot_assets
from tools.drama_studio import DramaBadRequest, apply_style, classify_shots, save_character, save_script
from tools.drama_video import _scene_prompt
from tools.loader import plugin_prompt_hints
from tools.workspace import resolve_safe

SLUG = "q8-smoke"
MD = """# Q8 验收
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
LOOK = "black hair, sharp eyes, silk robe"


def _shot(doc: dict, n: int) -> dict:
    return next(s for s in doc["shots"] if int(s["n"]) == n)


def _sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_dummy_clip(slug: str, n: int):
    assets = shot_assets(slug, 1, n)
    path = resolve_safe(assets["clip"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(f"fake-clip-{n}".encode())
    return path


def main() -> None:
    root = resolve_safe(f"dramas/{SLUG}")
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    (root / "project.json").write_text(
        json.dumps({"slug": SLUG, "title": "Q8 验收", "logline": "风格包", "episodes": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    save_character(SLUG, {"id": "hero", "name": "主角", "look": LOOK, "voice": "zh-CN-YunxiNeural"})
    save_script(SLUG, 1, MD)
    classified = classify_shots(SLUG, 1)
    assert classified["classified"] == 2, classified

    clips = [_write_dummy_clip(SLUG, 1), _write_dummy_clip(SLUG, 2)]
    doc = load_doc(SLUG, 1)
    s1, s2 = _shot(doc, 1), _shot(doc, 2)
    assert s1["kind"] == "establishing", s1
    assert s2["kind"] == "dialogue", s2
    for shot in (s1, s2):
        shot["dirty"] = []
        shot["status"] = "rendered"
    save_doc(doc)
    hashes0 = [_sha(p) for p in clips]
    dirty0 = [list(_shot(load_doc(SLUG, 1), n).get("dirty") or []) for n in (1, 2)]
    models_path = resolve_safe(models_rel(SLUG))
    models_hash = _sha(models_path) if models_path.is_file() else ""

    hints = plugin_prompt_hints()
    assert any("apply_style" in hint for hint in hints), hints

    webtoon = apply_style(SLUG, 1, "webtoon-city")
    d_img = next(s for s in webtoon["shots"] if s["n"] == 2)["image"]
    assert d_img["model"] == "flux-scene", d_img
    assert "character" not in [str(x).lower() for x in (d_img.get("refs") or [])], d_img
    assert d_img.get("character_model") is False, d_img

    ancient = apply_style(SLUG, 1, "ancient-dialogue")
    assert ancient["style_id"] == "ancient-dialogue", ancient
    assert any(p.get("title") == "古风对话" for p in ancient.get("styles") or []), ancient.get("styles")
    est = next(s for s in ancient["shots"] if s["n"] == 1)["image"]
    dia = next(s for s in ancient["shots"] if s["n"] == 2)["image"]
    assert dia["model"] == "char-lora", dia
    assert "character" in [str(x).lower() for x in (dia.get("refs") or [])], dia
    assert dia.get("character_model") is True, dia
    assert est["model"] == "flux-scene", est
    assert est.get("cheap") is True, est
    assert float(est["cost_per_shot"]) < float(dia["cost_per_shot"]), (est, dia)
    cost = ancient.get("cost") or {}
    assert "image_estimate" in cost, cost
    assert float(cost["image_estimate"]) > 0, cost
    assert cost.get("style_id") == "ancient-dialogue", cost
    assert "古风" in str(cost.get("style_title") or ""), cost
    assert "未重渲" in str(ancient.get("hint") or ""), ancient.get("hint")

    hashes1 = [_sha(p) for p in clips]
    assert hashes1 == hashes0, (hashes0, hashes1)
    doc = load_doc(SLUG, 1)
    dirty1 = [list(_shot(doc, n).get("dirty") or []) for n in (1, 2)]
    assert dirty1 == dirty0, (dirty0, dirty1)
    assert "clip" not in dirty1[0] and "voice" not in dirty1[1], dirty1
    if models_hash:
        assert _sha(models_path) == models_hash, "apply_style must not rewrite models.json"

    cards = load_characters(SLUG)
    s1, s2 = _shot(doc, 1), _shot(doc, 2)
    s2["_episode"] = 1
    dia_prompt = _scene_prompt("Q8 验收", s2, resolve_shot_characters(s2, cards), slug=SLUG)
    s2.pop("_episode", None)
    low = dia_prompt.lower()
    assert "hanfu" in low or "ancient" in low, dia_prompt
    assert "lora:ancient-char" in low, dia_prompt
    assert "character lora" in low, dia_prompt
    assert LOOK.split(",")[0] in dia_prompt, dia_prompt

    s1["_episode"] = 1
    est_prompt = _scene_prompt("Q8 验收", s1, resolve_shot_characters(s1, cards), slug=SLUG)
    s1.pop("_episode", None)
    elow = est_prompt.lower()
    assert "scene model flux-scene" in elow or "lora:ancient-palace" in elow, est_prompt
    assert "character lora" not in elow, est_prompt

    d4_prompt = _scene_prompt("Q8 验收", s2, resolve_shot_characters(s2, cards), slug=SLUG)
    assert LOOK.split(",")[0] in d4_prompt, d4_prompt

    try:
        apply_style(SLUG, 1, "no-such-pack")
        raise AssertionError("unknown style_id should fail")
    except DramaBadRequest:
        pass

    print("Q8 smoke ok: 古风对话 character route, establishing cheap, clips untouched")


if __name__ == "__main__":
    try:
        main()
    finally:
        root = resolve_safe(f"dramas/{SLUG}")
        if root.exists():
            try:
                shutil.rmtree(root)
            except OSError:
                pass
