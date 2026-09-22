"""I2V automation: single provider, no same-tier hop / no generic auto-retry.

唯一例外：输出撞「疑似真人/敏感内容」时，降级方案 A（不传首帧、只用大头照锁脸）重试一次。
"""

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
    from tools.drama_i2v import (
        _format_i2v_fail_detail,
        _is_output_sensitive_i2v_error,
        _is_privacy_i2v_error,
    )

    assert _is_privacy_i2v_error(
        "HTTP 400: InputImageSensitiveContentDetected.PrivacyInformation: real person"
    )
    assert not _is_privacy_i2v_error("HTTP 500: timeout")
    assert _is_output_sensitive_i2v_error(
        "HTTP 400: OutputVideoSensitiveContentDetected: blocked"
    )
    assert not _is_privacy_i2v_error(
        "HTTP 400: OutputVideoSensitiveContentDetected: blocked"
    )
    msg = _format_i2v_fail_detail(
        "model=x; HTTP 400: OutputVideoSensitiveContentDetected"
    )
    assert "输出侧" in msg
    assert "动漫" in msg


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


def test_run_i2v_with_same_tier_alt_retries_reference_only_on_safety(tmp_path, monkeypatch):
    from tools import drama_i2v as di2v

    scene = tmp_path / "s.png"
    dest = tmp_path / "o.mp4"
    scene.write_bytes(b"x")
    calls: list[str] = []

    def fake_run(provider, *_a, **_k):
        calls.append(provider)
        return len(calls) >= 2  # 首次失败（撞敏感），第二次（方案 A）成功

    monkeypatch.setattr(di2v, "_run_i2v_provider", fake_run)
    shot: dict = {"_safety_retry_needed": True}
    assert (
        di2v._run_i2v_with_same_tier_alt(
            "seedance", scene, dest, shot, 4.0, models={}, planned="L2"
        )
        is True
    )
    assert calls == ["seedance", "seedance"]
    assert shot.get("_force_reference_only") is True
    assert "_safety_retry_needed" not in shot
