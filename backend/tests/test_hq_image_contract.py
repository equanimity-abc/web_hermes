"""HQ image contract: locked refs + no free cascade + no still fallback."""

from __future__ import annotations

import pytest

from tools.drama_hq_contract import (
    HQ_FORBIDDEN_IMAGE,
    assert_hq_image_ready,
    hq_image_provider_chain,
    is_hq_no_fallback,
)
from tools.drama_video import _image_provider_chain


def test_hq_forbidden_includes_pollinations():
    assert "pollinations" in HQ_FORBIDDEN_IMAGE


def test_hq_image_chain_single(monkeypatch):
    monkeypatch.setattr(
        "tools.providers.registry.has",
        lambda cap, pid: cap == "image" and pid in ("seedream", "kling-image", "pollinations"),
    )
    assert hq_image_provider_chain("seedream") == ["seedream"]
    assert hq_image_provider_chain("pollinations") == ["seedream"]


def test_image_provider_chain_studio_no_cascade(monkeypatch):
    monkeypatch.setattr(
        "tools.drama_hq_contract.is_hq_no_fallback",
        lambda slug, models=None: True,
    )
    monkeypatch.setattr(
        "tools.providers.registry.has",
        lambda cap, pid: cap == "image" and pid in ("seedream", "kling-image", "jimeng"),
    )
    chain = _image_provider_chain(
        "seedream",
        {"kind": "dialogue"},
        refs=("a.png",),
        slug="demo",
    )
    assert chain == ["seedream"]


def test_assert_hq_image_ready_missing_lock(monkeypatch):
    monkeypatch.setattr(
        "tools.drama_models.load_models",
        lambda slug: {"image": {"dialogue": {"provider": "seedream"}}},
    )
    monkeypatch.setattr(
        "tools.drama_styles.image_route",
        lambda slug, shot, **k: {"provider": "seedream"},
    )
    monkeypatch.setattr(
        "tools.drama_models.provider_usable",
        lambda models, pid: True,
    )
    monkeypatch.setattr(
        "tools.drama_characters.load_characters",
        lambda slug: [{"id": "c1", "name": "后羿", "ref_locked": False}],
    )
    monkeypatch.setattr(
        "tools.drama_characters.resolve_shot_characters",
        lambda shot, cards: cards,
    )
    monkeypatch.setattr(
        "tools.drama_characters.character_requires_face_identity",
        lambda c: True,
    )
    monkeypatch.setattr(
        "tools.drama_characters.ref_exists",
        lambda slug, c: False,
    )
    with pytest.raises(ValueError, match="锁定定妆"):
        assert_hq_image_ready("demo", {"n": 1, "kind": "dialogue"})


def test_is_hq_default_studio():
    assert is_hq_no_fallback("", models={"quality_profile": "studio"}) is True
    assert is_hq_no_fallback("", models={"quality_profile": "draft"}) is False
