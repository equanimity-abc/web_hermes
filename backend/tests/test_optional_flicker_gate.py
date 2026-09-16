"""定场/空镜无真 I2V 时，闪烁闸不得 Fail Loud。"""

from __future__ import annotations


def test_optional_kind_flicker_no_video_is_na():
    from tools.drama_hq_contract import HQ_I2V_OPTIONAL_KINDS
    from tools.drama_qc import check_allows_pass

    assert "establishing" in HQ_I2V_OPTIONAL_KINDS
    flicker = {
        "status": "n/a",
        "pass": False,
        "required": False,
        "reason": "optional_kind_no_motion",
        "hint": "本镜为 establishing，无真 I2V 运动片，闪烁验收不适用",
    }
    assert check_allows_pass(flicker) is True


def test_advisory_identity_allows_resume_gate():
    from tools.drama_qc import check_allows_pass

    identity = {
        "status": "ok",
        "pass": False,
        "required": False,
        "enforcement": "advisory",
        "cosine": 0.65,
    }
    assert check_allows_pass(identity) is True
