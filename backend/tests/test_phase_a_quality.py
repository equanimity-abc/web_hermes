"""Phase A: Fail Loud gates + product defaults."""

from __future__ import annotations

import pytest

from config import config
from tools.drama_lip import QUALITY_CASCADE, lip_provider_cascade
from tools.drama_models import DEFAULT_PRESET, default_models
from tools.drama_quality import assert_shots_qc_for_export, assert_studio_providers


def test_phase_a_defaults():
    assert int(getattr(config, "DRAMA_SHOT_CONCURRENCY", 0) or 0) == 2
    assert DEFAULT_PRESET == "ark"
    assert QUALITY_CASCADE[0] == "seedance"
    assert default_models()["lip"]["provider"] == "seedance"


def test_lip_cascade_seedance_only(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "LIP_QUALITY", "max")
    monkeypatch.setattr(config, "LIP_ALLOW_MOCK", "0")
    monkeypatch.setattr(config, "ARK_API_KEY", "ark-test")
    monkeypatch.setattr(config, "LIP_PROVIDER", "seedance")
    monkeypatch.setattr(
        "tools.drama_profiles.resolve_quality_profile",
        lambda slug=None, models=None: "draft",
    )
    monkeypatch.setattr(
        "tools.drama_hq_contract.is_hq_no_fallback",
        lambda slug="", models=None: False,
    )
    cascade = lip_provider_cascade("seedance")
    assert cascade == ["seedance"]


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

    # QC 永久关闭：即使未 force 也不再硬拦
    ok = assert_shots_qc_for_export("s", 1, doc, force=False)
    assert ok["ok"] is True
    assert ok.get("qc_disabled") is True
    ok2 = assert_shots_qc_for_export("s", 1, doc, force=True)
    assert ok2["forced"] is True


def test_qc_shot_bundle_preserves_produce_state(monkeypatch: pytest.MonkeyPatch):
    """QC 打分不得覆盖产线失败标记（produce_ok/resume_from），否则续跑会误判从头重渲。"""
    from tools.drama_qc import qc_shot_bundle

    monkeypatch.setattr(
        "tools.drama_qc.qc_shot_lip",
        lambda slug, shot, apply=True: {"status": "ok", "pass": True},
    )
    monkeypatch.setattr(
        "tools.drama_qc.qc_shot_flicker",
        lambda slug, shot, apply=True: {"status": "ok", "pass": True},
    )

    shot = {
        "n": 1,
        "qc": {
            "produce_ok": False,
            "produce_error": "Shot 4 超时",
            "produce_stage": "motion",
            "resume_from": "motion",
            "resume_hint": "重试 I2V",
        },
    }
    bundle = qc_shot_bundle("s", 1, shot)

    assert bundle["produce_ok"] is False
    assert bundle["produce_error"] == "Shot 4 超时"
    assert bundle["resume_from"] == "motion"
    assert bundle["produce_stage"] == "motion"
    assert bundle["resume_hint"] == "重试 I2V"
    # 写回 shot 后同样保留
    assert shot["qc"]["produce_ok"] is False
    assert shot["qc"]["resume_from"] == "motion"
