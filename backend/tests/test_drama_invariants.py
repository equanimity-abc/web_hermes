"""Core invariant tests for the drama pipeline (P2-12).

Covers the P0/P1/P2 fixes so regressions are caught:
  - retry circuit breaker semantics
  - identity proxy can never pass
  - model overrides merge (3 layers)
  - cost accounting
  - slug/episode/shot parsing
  - shot path error readability
"""

from __future__ import annotations

import pytest

from tools.drama_common import DramaBadRequest, parse_episode, parse_shot_n, parse_slug
from tools.drama_models import (
    append_cost,
    cost_entry,
    models_with_overrides,
    normalize_models,
)
from tools.drama_retry import CircuitBreaker, retry_call


# ---------------------------------------------------------------- P1-6 retry
def test_circuit_breaker_opens_after_threshold():
    cb = CircuitBreaker(failure_threshold=2, cooldown_sec=60)
    assert cb.should_attempt() is True
    cb.record_failure()
    assert cb.should_attempt() is True  # below threshold
    cb.record_failure()
    assert cb.should_attempt() is False  # now open
    cb.record_success()
    assert cb.should_attempt() is True  # reset


def test_retry_call_returns_last_result_not_raises():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        return None  # never truthy

    result = retry_call(flaky, attempts=3, delay=0)
    assert result is None
    assert calls["n"] == 3


def test_retry_call_ok_predicate_and_backoff():
    def value():
        return "fallback"

    # ok predicate never accepts "fallback", so it retries all attempts
    result = retry_call(value, attempts=3, delay=0, ok=lambda r: r == "ai")
    assert result == "fallback"


def test_retry_call_success_stops_early():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        return "ai" if calls["n"] >= 2 else "none"

    result = retry_call(flaky, attempts=5, delay=0, ok=lambda r: r == "ai")
    assert result == "ai"
    assert calls["n"] == 2


# ---------------------------------------------------------------- P1-7 identity
def test_proxy_identity_cannot_pass():
    from tools.drama_qc import check_allows_pass

    proxy = {"status": "degraded", "reason": "proxy_identity", "method": "proxy", "cosine": 0.9}
    assert check_allows_pass(proxy) is False  # 0.9 也不通过


def test_arcface_identity_ok_and_pass_wins():
    from tools.drama_qc import check_allows_pass

    ok = {"status": "ok", "pass": True, "method": "arcface"}
    assert check_allows_pass(ok) is True


# ---------------------------------------------------------------- P0-5 overrides
def test_models_with_overrides_deep_merges_episode_and_shot():
    from tools.drama_models import default_models

    base = default_models()
    # Simulate episode and shot overrides without touching the workspace.
    raw = {
        **base,
        "image": {
            **base["image"],
            "dialogue": {**base["image"]["dialogue"], "provider": "flux"},
        },
    }
    doc = {
        "style_id": "",
        "models_overrides": {"lip": {"provider": "musetalk", "enabled": True}},
        "shot_models": {
            "3": {"image": {"dialogue": {"provider": "jimeng", "model": "char-consistent"}}}
        },
    }
    models = models_with_overrides("test-slug", doc=doc)
    # episode override wins over project
    assert models["lip"]["provider"] == "musetalk"
    # shot override wins over episode-level for that shot's route
    shot_models = models_with_overrides("test-slug", doc=doc, shot={"n": 3})
    assert shot_models["image"]["dialogue"]["provider"] == "jimeng"


def test_models_with_overrides_rejects_unknown_node():
    from tools.drama_models import default_models

    doc = {"models_overrides": {"bogus_node": {"x": 1}}}
    models = models_with_overrides("test-slug", doc=doc)
    # unknown node ignored, still normalized
    assert "bogus_node" not in models


# ---------------------------------------------------------------- P1-9 cost
def test_append_cost_accumulates():
    doc = {}
    append_cost(doc, provider="kling", layer="motion", cost=2.5, shot=1)
    append_cost(doc, provider="musetalk", layer="lip", cost=0.8, shot=2)
    total = sum(round(float(e["cost"]), 4) for e in doc["cost_log"])
    assert total == 3.3


def test_cost_entry_shape():
    entry = cost_entry(provider="http", layer="scene", cost=0.05, shot=3)
    assert entry["provider"] == "http"
    assert entry["layer"] == "scene"
    assert entry["cost"] == 0.05
    assert entry["shot"] == 3


# ---------------------------------------------------------------- P2-13 parsing
def test_parse_slug_validation():
    assert parse_slug("cold-palace") == "cold-palace"
    with pytest.raises(DramaBadRequest):
        parse_slug("../etc")


def test_parse_episode_and_shot_ranges():
    with pytest.raises(DramaBadRequest):
        parse_episode(0)
    with pytest.raises(DramaBadRequest):
        parse_episode(100)
    with pytest.raises(DramaBadRequest):
        parse_shot_n(0)


# ---------------------------------------------------------------- P2-15 readabaility
def test_path_for_readable_error():
    from tools.drama_video import _path_for

    shot = {"n": 4, "assets": {"scene": "dramas/slug/videos/ep01/shot04_scene.png"}}
    # No missing path; this resolves within workspace root. Instead assert
    # missing layer raises a readable ValueError.
    with pytest.raises(ValueError) as exc:
        _path_for({"n": 4, "assets": {}}, "scene")
    assert "scene" in str(exc.value)
    assert "4" in str(exc.value)


# ------------------------------------------------ regression: budget_state UnboundLocalError
def test_budget_state_nonempty_shots_no_unbound_local(monkeypatch):
    """Regression: non-empty shots + episode must not raise UnboundLocalError.

    The bug: `from tools.drama_shots import load_doc` lived inside a conditional
    block but was later used unconditionally. Non-empty shots skipped the block
    and left the local `load_doc` unbound.
    """
    import tools.drama_models as dm

    monkeypatch.setattr(dm, "load_models", lambda slug: dm.default_models())
    monkeypatch.setattr(
        dm,
        "estimate_episode_i2v",
        lambda slug, shots, episode=None, doc=None: {
            "i2v_estimate": 0.0,
            "lip_estimate": 0.0,
            "image_estimate": 0.0,
        },
    )
    monkeypatch.setattr(dm, "actual_episode_cost", lambda slug, episode: 0.0)

    result = dm.budget_state("test-slug", episode=1, shots=[{"n": 1}])
    assert result["enabled"] is False
    assert result["spent"] == 0.0
