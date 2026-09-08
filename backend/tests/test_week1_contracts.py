"""Week1 contract tests: TTS degrade policy, voice hint, BGM intent."""

from __future__ import annotations

import pytest

from tools.drama_bgm_catalog import match_bgm_by_intent
from tools.drama_characters import voice_hint_to_gender
from tools.drama_tts_policy import (
    allow_tts_edge_degrade,
    refuse_or_edge,
    reset_tts_edge_degrade,
    set_tts_edge_degrade,
)


def test_voice_hint_to_gender():
    assert voice_hint_to_gender("女声温柔") == "female"
    assert voice_hint_to_gender("男声低沉") == "male"
    assert voice_hint_to_gender("") == ""


def test_match_bgm_by_intent_prefers_mood():
    tracks = [
        {"id": "rebirth_resolve", "mood": "励志", "title": "决意", "notes": ""},
        {"id": "suspense_dark", "mood": "悬疑", "title": "暗涌", "notes": "紧张暗流"},
    ]
    assert match_bgm_by_intent("古风悬疑紧张", tracks) == "suspense_dark"
    assert match_bgm_by_intent("重生觉醒励志", tracks) == "rebirth_resolve"


def test_studio_tts_refuses_edge_degrade(tmp_path):
    token = set_tts_edge_degrade(False)
    try:
        assert allow_tts_edge_degrade() is False
        with pytest.raises(RuntimeError, match="禁止静默降级"):
            refuse_or_edge("hi", tmp_path / "a.mp3", voice=None, reason="no key")
    finally:
        reset_tts_edge_degrade(token)


def test_draft_tts_allows_edge_degrade(tmp_path, monkeypatch):
    token = set_tts_edge_degrade(True)
    try:
        monkeypatch.setattr(
            "tools.providers.tts_providers._edge_tts",
            lambda text, dest, *, voice=None: True,
        )
        assert refuse_or_edge("hi", tmp_path / "a.mp3", voice=None, reason="no key") is True
    finally:
        reset_tts_edge_degrade(token)
