"""影子/剪影不得建角色卡。"""

from __future__ import annotations

import pytest

from tools.drama_characters import (
    CharacterError,
    canonical_role_name,
    character_requires_face_identity,
    is_shadow_stage_card,
    match_character_token,
    role_token_face_exempt,
)


def test_canonical_role_name_strips_shadow_note():
    assert canonical_role_name("后羿（仅影子）") == "后羿"
    assert canonical_role_name("后羿(仅影子)") == "后羿"
    assert canonical_role_name("嫦娥") == "嫦娥"


def test_face_exempt_and_shadow_card():
    assert role_token_face_exempt("后羿（仅影子）") is True
    assert role_token_face_exempt("纯黑剪影") is True
    assert role_token_face_exempt("后羿") is False
    shadow = {"name": "后羿（仅影子）", "look": "剪影", "category": "character"}
    face = {"name": "后羿", "look": "玄色劲装", "category": "character"}
    assert is_shadow_stage_card(shadow) is True
    assert is_shadow_stage_card(face) is False
    assert character_requires_face_identity(shadow) is False
    assert character_requires_face_identity(face) is True


def test_match_prefers_face_card_over_silhouette():
    face = {
        "id": "houyi",
        "name": "后羿",
        "look": "玄色劲装",
        "category": "character",
        "aliases": [],
    }
    shadow = {
        "id": "houyi_shadow",
        "name": "后羿（仅影子）",
        "look": "纯黑剪影无五官",
        "category": "character",
        "aliases": [],
    }
    hit = match_character_token("后羿（仅影子）", [shadow, face])
    assert hit is not None and hit["id"] == "houyi"
    hit2 = match_character_token("后羿", [shadow, face])
    assert hit2 is not None and hit2["id"] == "houyi"


def test_upsert_rejects_pure_shadow_name(monkeypatch):
    from tools import drama_characters as dc

    monkeypatch.setattr(dc, "load_characters", lambda slug: [])
    monkeypatch.setattr(dc, "save_characters", lambda slug, cards: "ok")
    with pytest.raises(CharacterError, match="不能单独建角色卡"):
        dc.upsert_character("demo", {"name": "剪影", "look": "黑影"})
