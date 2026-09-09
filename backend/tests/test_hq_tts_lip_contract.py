"""HQ TTS + lip contract: commercial TTS only, no mock lip, motion base required."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.drama_hq_contract import assert_hq_lip_ready, assert_hq_tts_ready
from tools.drama_lip import lip_provider_cascade
from tools.providers.lip_providers import lip_source_is_real


def test_lip_source_mock_not_real():
    assert lip_source_is_real("mock") is False
    assert lip_source_is_real("pixverse") is True
    assert lip_source_is_real("pixverse+per_turn") is True


def test_assert_hq_tts_rejects_edge(monkeypatch):
    monkeypatch.setattr(
        "tools.drama_models.load_models",
        lambda slug: {"tts": {"provider": "edge-tts"}},
    )
    monkeypatch.setattr(
        "tools.drama_models.models_with_overrides",
        lambda slug, shot=None, **k: {"tts": {"provider": "edge-tts"}},
    )
    with pytest.raises(ValueError, match="edge-tts"):
        assert_hq_tts_ready("demo")


def test_assert_hq_tts_ok(monkeypatch):
    monkeypatch.setattr(
        "tools.drama_models.load_models",
        lambda slug: {"tts": {"provider": "seed-audio"}},
    )
    monkeypatch.setattr(
        "tools.drama_models.models_with_overrides",
        lambda slug, shot=None, **k: {"tts": {"provider": "seed-audio"}},
    )
    monkeypatch.setattr("tools.drama_models.provider_usable", lambda models, pid: True)
    out = assert_hq_tts_ready("demo")
    assert out["provider"] == "seed-audio"


def test_lip_cascade_studio_no_mock(monkeypatch):
    monkeypatch.setattr("tools.drama_lip._provider_ready", lambda pid: False)
    monkeypatch.setattr("tools.drama_lip._allow_mock", lambda: True)
    monkeypatch.setattr(
        "tools.drama_hq_contract.is_hq_no_fallback",
        lambda slug, models=None: True,
    )
    monkeypatch.setattr(
        "tools.drama_profiles.resolve_quality_profile",
        lambda slug=None, models=None: "studio",
    )
    assert lip_provider_cascade("mock", slug="demo") == []


def test_assert_hq_lip_requires_motion(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "tools.drama_models.models_with_overrides",
        lambda slug, shot=None, **k: {"lip": {"provider": "pixverse"}},
    )
    monkeypatch.setattr(
        "tools.drama_lip.lip_eligible",
        lambda shot, models=None: {"ok": True},
    )
    monkeypatch.setattr(
        "tools.drama_lip.lip_provider_cascade",
        lambda wanted=None, slug="": ["pixverse"],
    )
    with pytest.raises(ValueError, match="真 I2V"):
        assert_hq_lip_ready(
            "demo",
            {
                "n": 1,
                "kind": "dialogue",
                "i2v_source": "fallback",
                "assets": {},
                "dialogue_track": {"turns": [{"speaker": "A", "text": "hi"}]},
            },
        )


def test_assert_hq_lip_multi_speaker(monkeypatch, tmp_path: Path):
    motion = tmp_path / "m.mp4"
    motion.write_bytes(b"x" * 2000)
    monkeypatch.setattr(
        "tools.drama_models.models_with_overrides",
        lambda slug, shot=None, **k: {"lip": {"provider": "pixverse"}},
    )
    monkeypatch.setattr(
        "tools.drama_lip.lip_eligible",
        lambda shot, models=None: {"ok": True},
    )
    monkeypatch.setattr(
        "tools.drama_lip.lip_provider_cascade",
        lambda wanted=None, slug="": ["pixverse"],
    )
    monkeypatch.setattr("tools.workspace.resolve_safe", lambda rel: motion)
    with pytest.raises(ValueError, match="auto_split"):
        assert_hq_lip_ready(
            "demo",
            {
                "n": 1,
                "kind": "dialogue",
                "i2v_source": "ai",
                "assets": {"motion": "m.mp4"},
                "dialogue_track": {
                    "turns": [
                        {"speaker": "A", "text": "hi"},
                        {"speaker": "B", "text": "yo"},
                    ]
                },
            },
        )
