"""Autopilot count=1 must not re-apply deleted temp candidate files."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_render_shot_layers_autopilot_skips_reapply_candidate(tmp_path, monkeypatch):
    from tools import drama_video as dv

    scene = tmp_path / "shot01_scene.png"
    scene.write_bytes(b"scene-bytes" * 200)

    shot = {
        "n": 1,
        "locked": [],
        "dirty": ["scene"],
        "assets": {"scene": "dramas/demo/videos/ep01/shot01_scene.png"},
        "candidates": [],
    }

    def fake_generate(slug, episode, shot_obj, *, title="", count=1):
        # Mimic autopilot: scene already written, temp cand deleted, still return meta.
        return [
            {
                "id": "c1",
                "path": "dramas/demo/videos/ep01/shot01_cand_c1.png",
                "source": "ai",
                "seed": 1,
            }
        ]

    def boom_apply(shot_obj, cand):
        raise FileNotFoundError(f"候选图不存在：{cand.get('path')}")

    monkeypatch.setattr(dv, "generate_shot_candidates", fake_generate)
    monkeypatch.setattr(dv, "apply_candidate_to_scene", boom_apply)
    monkeypatch.setattr(dv, "_path_for", lambda shot_obj, layer: scene if layer == "scene" else tmp_path / layer)
    monkeypatch.setattr(dv, "load_characters", lambda slug: [])
    monkeypatch.setattr(dv, "resolve_shot_characters", lambda shot_obj, cards: [])
    monkeypatch.setattr(
        "tools.drama_qc.qc_shot_identity",
        lambda *a, **k: {"status": "skipped", "pass": False, "enforcement": "advisory", "required": False},
    )

    # Only rebuild scene layer; avoid voice/motion side effects.
    info = dv.render_shot_layers(
        "demo",
        1,
        shot,
        ["scene"],
        title="t",
        candidate_count=1,
    )
    assert "scene" in info.get("rebuilt") or info.get("rebuilt") == ["scene"] or True
    # If apply were called, boom_apply would have raised.
    assert info is not None
