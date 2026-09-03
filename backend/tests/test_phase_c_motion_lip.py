"""Phase C: motion floors + karaoke ASS + pro/ark preset alignment."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.drama_config import load_preset
from tools.drama_karaoke import build_karaoke_dialogue, write_karaoke_ass
from tools.drama_motion_floors import KIND_FLOOR, assert_motion_floor
from tools.drama_qc import DEFAULT_LSE_C_MIN


def test_kind_floor_dialogue_and_action():
    assert KIND_FLOOR["dialogue"] == "L1"
    assert KIND_FLOOR["action"] == "L3"


def test_assert_motion_floor_raises_on_l0_dialogue():
    shot = {"n": 1, "kind": "dialogue", "i2v_ladder": "L0"}
    with pytest.raises(RuntimeError, match="低于专业档下限"):
        assert_motion_floor(shot, slug="", models=None)


def test_build_karaoke_dialogue_chinese_nonempty():
    body = build_karaoke_dialogue("你好世界", 2.0)
    assert body
    assert "\\k" in body
    assert "你" in body


def test_write_karaoke_ass_creates_file(tmp_path: Path):
    dest = tmp_path / "shot01_overlay.ass"
    written = write_karaoke_ass(dest, "你好", duration=1.5)
    assert written == dest
    assert dest.is_file()
    text = dest.read_text(encoding="utf-8-sig")
    assert "[Events]" in text
    assert "Dialogue:" in text


def test_default_lse_c_min():
    assert DEFAULT_LSE_C_MIN == 0.15


def test_ark_preset_motion_dialogue_fallback_and_karaoke():
    ark = load_preset("ark")
    motion = (ark.get("models") or {}).get("motion") or {}
    dialogue = motion.get("dialogue") or {}
    assert dialogue.get("fallback") == "L1"
    subtitle = (ark.get("models") or {}).get("subtitle") or {}
    assert subtitle.get("style") == "karaoke"


def test_pro_preset_motion_fallbacks_and_karaoke():
    pro = load_preset("pro")
    motion = (pro.get("models") or {}).get("motion") or {}
    assert (motion.get("dialogue") or {}).get("fallback") == "L1"
    assert (motion.get("reaction") or {}).get("fallback") == "L1"
    assert (motion.get("action") or {}).get("fallback") == "L3"
    subtitle = (pro.get("models") or {}).get("subtitle") or {}
    assert subtitle.get("style") == "karaoke"
