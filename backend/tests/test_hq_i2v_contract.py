"""HQ I2V contract: studio forces strict, no Ken Burns."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.drama_hq_contract import assert_hq_i2v_ready
from tools.drama_i2v import try_generate_i2v


def test_hq_shot_layers_default_seedance_audio_then_clip():
    """默认：无独立配音层；手动配音才含 voice；I2V 后只组装成片。"""
    from tools.drama_produce import HQ_POST_I2V_LAYERS, HQ_SHOT_LAYERS, HQ_SHOT_LAYERS_MANUAL_VOICE

    assert HQ_SHOT_LAYERS == ("scene", "overlay")
    assert HQ_SHOT_LAYERS_MANUAL_VOICE == ("scene", "overlay", "voice")
    assert "lip" not in HQ_SHOT_LAYERS
    assert "voice" not in HQ_SHOT_LAYERS
    assert HQ_POST_I2V_LAYERS == ("clip",)
    assert "lip" not in HQ_POST_I2V_LAYERS


def test_try_generate_i2v_strict_l0_no_kenburns(monkeypatch, tmp_path: Path):
    scene = tmp_path / "scene.png"
    scene.write_bytes(b"x" * 100)
    dest = tmp_path / "motion.mp4"

    monkeypatch.setattr("tools.drama_i2v.shutil.which", lambda *_a, **_k: "ffmpeg")
    monkeypatch.setattr("tools.drama_i2v.i2v_seconds", lambda shot: 4.0)
    monkeypatch.setattr("tools.drama_i2v.motion_seconds", lambda shot: 4.0)
    monkeypatch.setattr(
        "tools.drama_models.effective_motion_ladder",
        lambda shot, slug=None, models=None: "L0",
    )
    monkeypatch.setattr(
        "tools.drama_models.models_with_overrides",
        lambda *a, **k: {},
    )
    monkeypatch.setattr("tools.drama_i2v._resolved_i2v_provider", lambda shot: "l0")

    called = {"kb": False}

    def _kb(*a, **k):
        called["kb"] = True
        return True

    monkeypatch.setattr("tools.drama_i2v._provider_mock_ai", _kb)
    src = try_generate_i2v(scene, dest, {"n": 1, "_slug": "demo"}, strict=True)
    assert src == "none"
    assert called["kb"] is False


def test_assert_hq_i2v_ready_fail(monkeypatch):
    monkeypatch.setattr("tools.drama_models.infer_kind", lambda shot: "dialogue")
    monkeypatch.setattr("tools.drama_models.load_models", lambda slug: {})
    monkeypatch.setattr("tools.drama_models.provider_usable", lambda models, pid: False)
    with pytest.raises(ValueError, match="真 I2V"):
        assert_hq_i2v_ready("demo", {"n": 1, "kind": "dialogue"})


def test_assert_hq_i2v_ready_optional_kind(monkeypatch):
    monkeypatch.setattr("tools.drama_models.infer_kind", lambda shot: "title")
    out = assert_hq_i2v_ready("demo", {"n": 1, "kind": "title"})
    assert out.get("optional") is True
