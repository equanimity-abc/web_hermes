"""Q3 smoke: L0–L3 routing, establishing forbids I2V, expensive cap, mock L3."""

from __future__ import annotations

import json
import os
import shutil
import subprocess

os.environ["IMAGE_GEN_PROVIDER"] = "none"
os.environ["I2V_PROVIDER"] = "mock"

import agent.loop  # noqa: F401

from config import config
from tools.drama_i2v import generate_shot_i2v, motion_rel, should_try_i2v
from tools.drama_models import (
    MAX_EXPENSIVE_I2V,
    effective_motion_ladder,
    estimate_episode_i2v,
    estimate_i2v,
    i2v_run_ladder,
    load_models,
    set_provider_available,
)
from tools.drama_shots import load_doc, save_doc, shot_assets
from tools.drama_studio import DramaBadRequest, classify_shots, generate_i2v_shot, save_character, save_script
from tools.workspace import resolve_safe

config.IMAGE_GEN_PROVIDER = "none"
config.I2V_PROVIDER = "mock"

SLUG = "q3-smoke"
MD = """# Q3 验收
- 时长: 16s
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

### Shot 4 (12-16s)
- 画面: 收势
- 对白:
- 字幕:
- 角色: hero
"""


def _shot(doc: dict, n: int) -> dict:
    return next(s for s in doc["shots"] if int(s["n"]) == n)


def _png(path, color: str = "445566") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=1080x1920:d=0.04", "-frames:v", "1", str(path)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or "ffmpeg png failed")


def main() -> None:
    if shutil.which("ffmpeg") is None:
        print("skip Q3 smoke: ffmpeg not in PATH")
        return

    root = resolve_safe(f"dramas/{SLUG}")
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    (root / "project.json").write_text(
        json.dumps({"slug": SLUG, "title": "Q3", "logline": "运动档", "episodes": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    save_character(SLUG, {"id": "hero", "name": "主角", "look": "黑发", "voice": "zh-CN-YunxiNeural"})
    save_script(SLUG, 1, MD)
    classify_shots(SLUG, 1)
    doc = load_doc(SLUG, 1)
    _shot(doc, 3)["kind"] = "action"
    _shot(doc, 3)["size"] = "MS"
    _shot(doc, 4)["kind"] = "action"
    _shot(doc, 4)["size"] = "MS"
    for n in (1, 2, 3, 4):
        assets = shot_assets(SLUG, 1, n)
        _png(resolve_safe(assets["scene"]))
        shot = _shot(doc, n)
        shot["locked"] = ["scene"]
        shot["i2v"] = "on"
        shot.setdefault("assets", {})["scene"] = assets["scene"]
        shot["assets"]["motion"] = assets["motion"]
    save_doc(doc)

    s1, s2, s3 = _shot(load_doc(SLUG, 1), 1), _shot(load_doc(SLUG, 1), 2), _shot(load_doc(SLUG, 1), 3)
    assert effective_motion_ladder(s1, slug=SLUG) == "L0"
    assert effective_motion_ladder(s2, slug=SLUG) == "L2"
    assert effective_motion_ladder(s3, slug=SLUG) == "L3"
    assert i2v_run_ladder(s2, slug=SLUG) == "L1"
    assert i2v_run_ladder(s3, slug=SLUG) == "L1"
    assert should_try_i2v(s1, slug=SLUG) is False
    assert should_try_i2v(s3, slug=SLUG) is True

    est0 = estimate_i2v(SLUG, s1)
    est_a = estimate_i2v(SLUG, s3)
    assert est0["will_run"] is False and est0["ladder"] == "L0"
    assert est_a["planned_ladder"] == "L3"
    assert est_a["expensive"] is False
    assert est_a["provider"] in ("mock", "l0")

    try:
        generate_i2v_shot(SLUG, 1, 1)
        raise AssertionError("L0 must refuse I2V")
    except DramaBadRequest:
        pass

    doc = load_doc(SLUG, 1)
    info = generate_shot_i2v(SLUG, 1, _shot(doc, 3), force=True)
    save_doc(doc)
    assert info["i2v_source"] == "ai", info
    motion = resolve_safe(motion_rel(SLUG, 1, 3))
    assert motion.is_file() and motion.stat().st_size > 500
    assert _shot(load_doc(SLUG, 1), 3).get("i2v_ladder") == "L3"

    models = load_models(SLUG)
    set_provider_available(SLUG, "kling", True)
    models = load_models(SLUG)
    assert models["providers"]["kling"]["available"] is True
    s3 = _shot(load_doc(SLUG, 1), 3)
    est_k = estimate_i2v(SLUG, s3)
    assert est_k["planned_ladder"] == "L3"
    assert est_k["expensive"] is True or est_k["provider"] == "kling"

    doc = load_doc(SLUG, 1)
    _shot(doc, 2)["i2v_source"] = "ai"
    _shot(doc, 2)["i2v_expensive"] = True
    _shot(doc, 3)["i2v_source"] = "ai"
    _shot(doc, 3)["i2v_expensive"] = True
    save_doc(doc)
    s_new = dict(_shot(load_doc(SLUG, 1), 4))
    s_new["_slug"] = SLUG
    s_new["_episode"] = 1
    from tools.drama_i2v import _resolved_i2v_provider

    provider = _resolved_i2v_provider(s_new)
    assert provider == "mock", provider
    assert s_new.get("i2v_deferred") is True
    assert MAX_EXPENSIVE_I2V == 2

    ep_cost = estimate_episode_i2v(SLUG, load_doc(SLUG, 1)["shots"])
    assert ep_cost["expensive_cap"] == 2
    assert "lip_estimate" in ep_cost

    set_provider_available(SLUG, "kling", False)
    print("Q3 smoke ok: L0/L2/L3 routing, I2V forbid on establishing, expensive cap")


if __name__ == "__main__":
    try:
        main()
    finally:
        root = resolve_safe(f"dramas/{SLUG}")
        if root.exists():
            shutil.rmtree(root)
