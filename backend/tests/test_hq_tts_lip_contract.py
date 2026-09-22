"""HQ TTS + lip contract: Seed Audio TTS; Seedance-baked lip (no PixVerse)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.drama_hq_contract import assert_hq_tts_ready
from tools.drama_lip import lip_provider_cascade
from tools.providers.lip_providers import lip_source_is_real


def test_lip_source_mock_not_real():
    assert lip_source_is_real("mock") is False
    assert lip_source_is_real("seedance") is True
    assert lip_source_is_real("pixverse") is False  # 非 Ark 口型已移除
    assert lip_source_is_real("seedance+per_turn") is True


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


def test_lip_cascade_studio_single_provider(monkeypatch):
    monkeypatch.setattr(
        "tools.drama_lip._provider_ready",
        lambda pid: pid == "seedance",
    )
    monkeypatch.setattr(
        "tools.drama_hq_contract.is_hq_no_fallback",
        lambda slug, models=None: True,
    )
    monkeypatch.setattr(
        "tools.drama_profiles.resolve_quality_profile",
        lambda slug=None, models=None: "studio",
    )
    assert lip_provider_cascade("seedance", slug="demo") == ["seedance"]
    assert lip_provider_cascade("pixverse", slug="demo") == []
    assert lip_provider_cascade("missing", slug="demo") == []


