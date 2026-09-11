"""Anime style guard is injected into image prompts."""

from __future__ import annotations

from tools.drama_characters import (
    ANIME_STYLE_GUARD,
    build_face_ref_prompt,
    build_location_plate_prompt,
)
from tools.drama_video import _scene_prompt


def test_anime_style_guard_in_core_prompts():
    assert "禁止写实摄影" in ANIME_STYLE_GUARD
    face = build_face_ref_prompt({"id": "a", "name": "愚公", "look": "白须老人"})
    loc = build_location_plate_prompt({"name": "太行山", "look": "山道"})
    scene = _scene_prompt(
        "t",
        {"n": 1, "画面": "近景对话", "kind": "dialogue"},
        [{"id": "a", "name": "愚公"}],
    )
    assert ANIME_STYLE_GUARD in face
    assert ANIME_STYLE_GUARD in loc
    assert ANIME_STYLE_GUARD in scene
