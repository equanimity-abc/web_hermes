"""Q0 smoke: kind/speaker routing L0 vs L1, research card gate, cost fields."""

from __future__ import annotations

import json
import os
import shutil

os.environ["IMAGE_GEN_PROVIDER"] = "none"

import agent.loop  # noqa: F401

from config import config
from tools.drama_i2v import should_try_i2v
from tools.drama_models import (
    effective_motion_ladder,
    estimate_i2v,
    load_models,
    research_complete,
    set_provider_available,
)
from tools.drama_shots import load_doc, save_doc
from tools.drama_studio import classify_shots, get_episode, get_models, patch_shot, save_character, save_script
from tools.workspace import resolve_safe

config.IMAGE_GEN_PROVIDER = "none"

SLUG = "q0-smoke"
MD = """# Q0 验收
- 时长: 8s
- 钩子: 开场
- 悬念: 结尾

## 分镜
### Shot 1 (0-4s)
- 画面: 宫殿远景
- 对白:
- 字幕:

### Shot 2 (4-8s)
- 画面: 角色特写
- 对白: 旁白：今夜入宫
- 字幕: 今夜入宫
- 角色: hero
"""


def _shot(doc: dict, n: int) -> dict:
    return next(s for s in doc["shots"] if int(s["n"]) == n)


def main() -> None:
    root = resolve_safe(f"dramas/{SLUG}")
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    (root / "project.json").write_text(
        json.dumps({"slug": SLUG, "title": "Q0 验收", "logline": "路由", "episodes": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    save_character(SLUG, {"id": "hero", "name": "主角", "look": "黑发", "voice": "zh-CN-YunxiNeural"})
    save_script(SLUG, 1, MD)

    classified = classify_shots(SLUG, 1)
    assert classified["classified"] == 2, classified
    doc = load_doc(SLUG, 1)
    s1, s2 = _shot(doc, 1), _shot(doc, 2)
    assert s1["kind"] == "establishing", s1
    assert s1["size"] == "WS", s1
    assert s2["kind"] == "dialogue", s2
    assert s2["speaker"] == "hero", s2
    assert effective_motion_ladder(s1, slug=SLUG) == "L0", s1
    assert effective_motion_ladder(s2, slug=SLUG) == "L2", s2

    s1["i2v"] = "on"
    s1["locked"] = ["scene"]
    s2["i2v"] = "auto"
    s2["locked"] = ["scene"]
    save_doc(doc)
    assert should_try_i2v(s1, slug=SLUG) is False
    assert should_try_i2v(s2, slug=SLUG) is True

    voice_before = list(s2.get("dirty") or [])
    patched = patch_shot(SLUG, 1, 2, {"kind": "establishing"})
    new_dirty = patched.get("dirty") or []
    assert "clip" in new_dirty, patched
    assert "motion" in new_dirty, patched
    assert "voice" not in new_dirty, new_dirty
    doc = load_doc(SLUG, 1)
    s2 = _shot(doc, 2)
    assert s2["kind"] == "establishing"
    assert effective_motion_ladder(s2, slug=SLUG) == "L0"
    assert should_try_i2v(s2, slug=SLUG) is False
    _ = voice_before

    patch_shot(SLUG, 1, 2, {"kind": "dialogue", "speaker": "hero"})
    models = load_models(SLUG)
    assert models["currency"] == "CNY"
    assert models["providers"]["mock"]["available"] is True
    assert models["providers"]["kling"]["available"] is False
    assert research_complete(models["providers"]["kling"])

    try:
        set_provider_available(SLUG, "kling", True)
    except ValueError:
        raise AssertionError("完整调研卡应允许手动标 available")
    models = load_models(SLUG)
    assert models["providers"]["kling"]["available"] is True
    set_provider_available(SLUG, "kling", False)

    models["providers"]["hailuo"]["notes"] = ""
    models["providers"]["hailuo"]["available"] = True
    from tools.drama_models import save_models

    save_models(SLUG, models)
    models = load_models(SLUG)
    assert models["providers"]["hailuo"]["available"] is False, "不完整调研卡不得 available"

    try:
        set_provider_available(SLUG, "hailuo", True)
        raise AssertionError("不完整调研卡不能 available")
    except ValueError:
        pass

    est0 = estimate_i2v(SLUG, _shot(load_doc(SLUG, 1), 1))
    est1 = estimate_i2v(SLUG, _shot(load_doc(SLUG, 1), 2))
    assert est0["ladder"] == "L0" and est0["will_run"] is False, est0
    assert est1["ladder"] == "L1" and est1["will_run"] is True, est1

    ep = get_episode(SLUG, 1)
    assert ep["shot_kinds"]
    assert ep["cost"]["currency"] == "CNY"
    assert ep["shots"][0]["route"]["ladder"] == "L0"
    assert ep["shots"][1]["speaker"] == "hero"
    pub = get_models(SLUG)
    assert pub["models"]["providers"]["mock"]["cost_per_shot"] == 0

    print("Q0 smoke ok: classify L0/L1, speaker, research gate, cost fields")


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
