"""S0 honest-layer tests: provider name must match the registered adapter."""

from __future__ import annotations

from tools.drama_models import default_models, provider_health


def test_jimeng_is_missing_not_silent():
    """jimeng is written in pro.json but has no adapter — must be flagged missing."""
    models = default_models()
    models["image"]["dialogue"]["provider"] = "jimeng"
    health = provider_health(models)
    jimeng = next(
        it for it in health["items"]
        if it["capability"] == "image" and it["written"] == "jimeng"
    )
    assert jimeng["status"] == "missing"
    assert "无真适配器" in jimeng["reason"] or "无 image 适配器" in jimeng["reason"]


def test_volcano_is_edge_tts_alias():
    """volcano is registered as an edge-tts pass-through — must be flagged alias."""
    models = default_models()
    models["tts"]["provider"] = "volcano"
    health = provider_health(models)
    tts = next(it for it in health["items"] if it["capability"] == "tts")
    assert tts["written"] == "volcano"
    assert tts["status"] == "alias"
    assert tts["real"] == "edge-tts"


def test_musetalk_is_commercial_promise():
    """musetalk has no real adapter, only an http stub — must not claim live."""
    models = default_models()
    models["lip"]["provider"] = "musetalk"
    health = provider_health(models)
    lip = next(it for it in health["items"] if it["capability"] == "lip")
    assert lip["written"] == "musetalk"
    assert lip["status"] == "missing"


def test_local_backends_are_live():
    """name-accurate local backends are live, never flagged as degrades."""
    models = default_models()
    # Turn every node onto a genuine local backend so health reports fully live.
    models["lip"]["provider"] = "mock"
    models["tts"]["provider"] = "edge-tts"
    for kind in models["motion"]:
        models["motion"][kind]["provider"] = "l0"
    health = provider_health(models)
    assert health["healthy"] is True
    assert health["degraded_count"] == 0


def test_default_models_reports_pro_promise_degraded():
    """default models promise musetalk (lip) + kling (action) but have no real adapter."""
    health = provider_health(default_models())
    degraded = {it["written"] for it in health["items"] if it["status"] in ("alias", "missing")}
    assert "musetalk" in degraded
    assert "kling" in degraded