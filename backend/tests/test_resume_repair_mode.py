"""Resume path: flicker fail must redo motion, not lip-only."""

from __future__ import annotations

from tools.drama_produce import _resume_repair_mode


def test_clip_only_dirty_is_flicker_not_lip():
    mode = _resume_repair_mode(
        dirty={"clip"},
        resume_from="",
        i2v_src="ai",
        scene_ok=True,
        clip_ok=True,
        scene_locked=False,
    )
    assert mode == "flicker"


def test_lip_clip_dirty_is_lip():
    mode = _resume_repair_mode(
        dirty={"lip", "clip"},
        resume_from="",
        i2v_src="ai",
        scene_ok=True,
        clip_ok=True,
        scene_locked=False,
    )
    assert mode == "lip"


def test_resume_from_motion_beats_lip_dirty():
    mode = _resume_repair_mode(
        dirty={"lip", "clip"},
        resume_from="motion",
        i2v_src="ai",
        scene_ok=True,
        clip_ok=True,
        scene_locked=False,
    )
    assert mode == "flicker"
