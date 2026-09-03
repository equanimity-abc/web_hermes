"""Phase A: Fail Loud gates + product defaults."""

from __future__ import annotations

import pytest

from config import config
from tools.drama_lip import QUALITY_CASCADE, lip_provider_cascade
from tools.drama_models import DEFAULT_PRESET, default_models
from tools.drama_qc import DEFAULT_IDENTITY_MIN
from tools.drama_quality import assert_shots_qc_for_export, assert_studio_providers


def test_phase_a_defaults():
    assert int(getattr(config, "DRAMA_SHOT_CONCURRENCY", 0) or 0) == 8
    assert DEFAULT_IDENTITY_MIN == 0.75
    assert default_models()["qc"]["identity_min"] == 0.75
    assert DEFAULT_PRESET == "ark"
    assert QUALITY_CASCADE[0] in ("pixverse", "pixverse-lipsync")
    assert "latentsync" in QUALITY_CASCADE


def test_lip_cascade_pixverse_first(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "LIP_QUALITY", "max")
    monkeypatch.setattr(config, "LIP_ALLOW_MOCK", "0")
    monkeypatch.setattr(config, "DASHSCOPE_API_KEY", "ds")
    monkeypatch.setattr(config, "DASHSCOPE_MAAS_BASE_URL", "https://example.maas")
    monkeypatch.setattr(config, "REPLICATE_API_TOKEN", "r")
    monkeypatch.setattr(config, "LIP_PROVIDER", "pixverse")
    cascade = lip_provider_cascade("pixverse")
    assert cascade[0] in ("pixverse", "pixverse-lipsync")


def test_assert_studio_providers_fail_loud(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "ARK_API_KEY", "")
    monkeypatch.setattr(config, "DASHSCOPE_API_KEY", "")
    monkeypatch.setattr(config, "DASHSCOPE_MAAS_BASE_URL", "")
    monkeypatch.setattr(config, "REPLICATE_API_TOKEN", "")

    from tools import drama_models
    from tools.drama_config import load_preset

    doc = default_models()
    doc["preset"] = "ark"
    preset = load_preset("ark")
    for node, value in (preset.get("models") or {}).items():
        if isinstance(value, dict) and node != "providers":
            doc[node] = value

    monkeypatch.setattr(drama_models, "load_models", lambda slug: doc)
    with pytest.raises(ValueError, match="缺少可用模型"):
        assert_studio_providers("any-slug")


def test_export_qc_force_bypass(monkeypatch: pytest.MonkeyPatch):
    doc = {"shots": [{"n": 1, "locked": []}]}

    monkeypatch.setattr(
        "tools.drama_qc.qc_shot_bundle",
        lambda slug, ep, shot, apply=True: {
            "can_pass": False,
            "block_reason": "身份未通过",
            "identity": {"status": "ok", "pass": False},
        },
    )
    monkeypatch.setattr(
        "tools.drama_shots.ordered_shots_from_doc",
        lambda d: d.get("shots") or [],
    )
    monkeypatch.setattr("tools.drama_qc.shot_can_pass", lambda bundle: False)

    with pytest.raises(ValueError, match="QC 硬闸"):
        assert_shots_qc_for_export("s", 1, doc, force=False)
    ok = assert_shots_qc_for_export("s", 1, doc, force=True)
    assert ok["forced"] is True
