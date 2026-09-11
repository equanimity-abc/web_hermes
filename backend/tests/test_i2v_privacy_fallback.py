"""I2V automation: single provider, no same-tier hop / no auto-retry."""

from __future__ import annotations


def test_same_tier_alts_disabled():
    from tools.drama_i2v import _same_tier_alt_provider, _same_tier_alt_providers

    models = {
        "providers": {
            "kling-video": {"available": True},
            "wanx-video": {"available": True},
        }
    }
    assert _same_tier_alt_providers("seedance", models) == []
    assert _same_tier_alt_provider("seedance", models) is None


def test_privacy_error_detector():
    from tools.drama_i2v import _is_privacy_i2v_error

    assert _is_privacy_i2v_error(
        "HTTP 400: InputImageSensitiveContentDetected.PrivacyInformation: real person"
    )
    assert not _is_privacy_i2v_error("HTTP 500: timeout")


def test_run_i2v_with_same_tier_alt_primary_only(tmp_path, monkeypatch):
    from tools import drama_i2v as di2v

    scene = tmp_path / "s.png"
    dest = tmp_path / "o.mp4"
    scene.write_bytes(b"x")
    calls: list[str] = []

    def fake_run(provider, *_a, **_k):
        calls.append(provider)
        return False

    monkeypatch.setattr(di2v, "_run_i2v_provider", fake_run)
    shot: dict = {}
    assert (
        di2v._run_i2v_with_same_tier_alt(
            "seedance",
            scene,
            dest,
            shot,
            4.0,
            models={"providers": {"kling-video": {"available": True}}},
            planned="L2",
        )
        is False
    )
    assert calls == ["seedance"]
    assert shot.get("i2v_provider") == "seedance"
