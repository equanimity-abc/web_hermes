"""S0 honest-layer tests: provider name must match the registered adapter."""

from __future__ import annotations

from tools.drama_models import default_models, provider_health


def test_jimeng_gated_without_env():
    """S1: jimeng adapter exists but needs CONSISTENT_IMAGE_URL → gated (honest)."""
    models = default_models()
    models["image"]["dialogue"]["provider"] = "jimeng"
    health = provider_health(models)
    jimeng = next(
        it for it in health["items"]
        if it["capability"] == "image" and it["written"] == "jimeng"
    )
    assert jimeng["status"] == "gated"
    assert "CONSISTENT_IMAGE_URL" in jimeng["reason"]


def test_jimeng_live_with_env(monkeypatch):
    """S1: with the env URL set, jimeng is live (adapter registered)."""
    from config import config as _cfg

    monkeypatch.setattr(_cfg, "CONSISTENT_IMAGE_URL", "https://img.example.com/consist")
    models = default_models()
    models["image"]["dialogue"]["provider"] = "jimeng"
    health = provider_health(models)
    jimeng = next(
        it for it in health["items"]
        if it["capability"] == "image" and it["written"] == "jimeng"
    )
    assert jimeng["status"] == "live"


def test_volcano_gated_without_tts_url():
    """S3: volcano now has a real HTTP TTS gateway — gated until TTS_API_URL is set."""
    models = default_models()
    models["tts"]["provider"] = "volcano"
    health = provider_health(models)
    tts = next(it for it in health["items"] if it["capability"] == "tts")
    assert tts["written"] == "volcano"
    assert tts["status"] == "gated"
    assert "TTS_API_URL" in tts["reason"]


def test_musetalk_gated_without_lip_url():
    """S3: musetalk has a real http lip adapter — gated until LIP_API_URL is set."""
    models = default_models()
    models["lip"]["provider"] = "musetalk"
    health = provider_health(models)
    lip = next(it for it in health["items"] if it["capability"] == "lip")
    assert lip["written"] == "musetalk"
    assert lip["status"] == "gated"
    assert "LIP_API_URL" in lip["reason"]


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
    degraded = {
        it["written"]
        for it in health["items"]
        if it["status"] in ("alias", "missing", "gated")
    }
    assert "musetalk" in degraded
    assert "kling" in degraded


def test_image_cache_key_is_content_addressed():
    """S1: cache key is deterministic and sensitive to prompt/seed/refs."""
    from tools.providers.image_providers import _cache_key

    a = _cache_key("wukong faces the sky", seed=1, width=1620, height=2880, model="char-consistent")
    b = _cache_key("wukong faces the sky", seed=1, width=1620, height=2880, model="char-consistent")
    c = _cache_key("wukong faces the sky", seed=2, width=1620, height=2880, model="char-consistent")
    d = _cache_key("wukong faces the sky", seed=1, width=1620, height=2880, model="char-consistent", refs=("dramas/s/shots/p.png",))
    assert a == b
    assert a != c
    assert a != d


def test_kling_gated_without_i2v_url():
    """S2: kling adapter exists but needs I2V_API_URL → gated (honest)."""
    models = default_models()
    models["motion"]["action"]["provider"] = "kling"
    health = provider_health(models)
    kling = next(
        it for it in health["items"]
        if it["capability"] == "i2v" and it["written"] == "kling"
    )
    assert kling["status"] == "gated"
    assert "I2V_API_URL" in kling["reason"]


def test_kling_live_with_i2v_url(monkeypatch):
    """S2: with I2V_API_URL set, kling is live via the gateway adapter."""
    from config import config as _cfg

    monkeypatch.setattr(_cfg, "I2V_API_URL", "https://i2v.example.com/submit")
    models = default_models()
    models["motion"]["action"]["provider"] = "kling"
    health = provider_health(models)
    kling = next(
        it for it in health["items"]
        if it["capability"] == "i2v" and it["written"] == "kling"
    )
    assert kling["status"] == "live"


def test_pollinations_i2v_never_claims_ai():
    """S2: pollinations is an image service, not I2V — honest fallback to still."""
    from pathlib import Path

    from tools.drama_i2v import _provider_pollinations

    ok = _provider_pollinations(Path("scene.png"), Path("out.mp4"), {"画面": "x"}, 2.0)
    assert ok is False
