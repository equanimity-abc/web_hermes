"""Phase E: quality_profile hooks + research backlog placeholders."""

from __future__ import annotations

import pytest


def test_normalize_pro_alias_to_studio():
    from tools.drama_profiles import normalize_quality_profile

    assert normalize_quality_profile("pro") == "studio"


def test_resolve_default_studio():
    from tools.drama_profiles import resolve_quality_profile

    assert resolve_quality_profile("", models={}) == "studio"
    assert resolve_quality_profile("", models={"quality_profile": "studio"}) == "studio"


def test_assert_balanced_raises():
    from tools.drama_profiles import assert_profile_allows_studio_gates

    with pytest.raises(ValueError, match="balanced"):
        assert_profile_allows_studio_gates("balanced")


def test_draft_badge():
    from tools.drama_profiles import profile_policy

    assert profile_policy("draft")["badge"] == "草稿"


def test_research_backlog_has_l5():
    from tools.drama_profiles import research_backlog

    ids = {row["id"] for row in research_backlog()}
    assert "L5" in ids


def test_default_models_quality_profile():
    from tools.drama_models import default_models

    assert default_models()["quality_profile"] == "studio"
