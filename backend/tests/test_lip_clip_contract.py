"""Regression: lip_source suffixes (e.g. pixverse+per_turn) must count as real lip."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.drama_dialogue import build_dialogue_track, infer_turn_timings_from_voice
from tools.providers.lip_providers import lip_source_is_real, lip_video_usable


def test_lip_source_is_real_strips_strategy_suffix():
    assert lip_source_is_real("pixverse+per_turn") is True
    assert lip_source_is_real("latentsync+per_turn") is True
    assert lip_source_is_real("fallback") is False
    assert lip_source_is_real("") is False


def test_lip_video_usable_with_per_turn_suffix(tmp_path: Path):
    lip = tmp_path / "shot07_lip.mp4"
    lip.write_bytes(b"x" * 2048)
    shot = {"lip_source": "pixverse+per_turn", "assets": {"lip": str(lip)}}
    assert lip_video_usable(shot, lip) is True


def test_lip_video_usable_rejects_missing_file(tmp_path: Path):
    lip = tmp_path / "missing.mp4"
    shot = {"lip_source": "pixverse+per_turn"}
    assert lip_video_usable(shot, lip) is False


def test_infer_turn_timings_from_voice_splits_by_text_weight():
    track = {
        "mode": "multi",
        "turns": [
            {"index": 0, "text": "哎呀！对不起姐姐，我太不小心了！", "voice": "v1"},
            {"index": 1, "text": "没关系。一件衣服而已。", "voice": "v2"},
        ],
    }
    out = infer_turn_timings_from_voice(track, 9.0)
    turns = out["turns"]
    assert len(turns) == 2
    assert turns[0]["start"] == 0.0
    assert turns[0]["end"] >= turns[1]["start"]
    assert abs(turns[-1]["end"] - 9.0) < 0.2


def test_timed_turns_recover_from_script_when_metadata_lost(monkeypatch, tmp_path: Path):
    from tools.drama_lip import _timed_turns_for_lip

    voice = tmp_path / "voice.mp3"
    voice.write_bytes(b"x" * 100)
    shot = {
        "n": 7,
        "字幕": "哎呀！对不起姐姐，我太不小心了！……没关系。一件衣服而已。",
        "角色": ["林晚", "林薇薇"],
        "画面": "林薇薇端着牛奶走下楼梯",
    }
    monkeypatch.setattr(
        "tools.drama_video._probe_duration",
        lambda _p: 9.0,
    )
    turns = _timed_turns_for_lip(shot, voice_path=voice, slug="rebirth_heiress")
    assert len(turns) >= 2
    assert turns[0]["end"] > turns[0]["start"]
    assert turns[1]["end"] > turns[1]["start"]


def test_square_box_is_pixel_square():
    """Crop/paste geometry must stay pixel-square so the mouth never squashes."""
    from tools.drama_lip import _square_box

    x, y, bw, bh = _square_box(1080, 1920, (0.08, 0.10, 0.34, 0.30))
    assert abs((bw * 1080) - (bh * 1920)) < 1.0
    assert 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0


def test_explicit_layout_director_override():
    """Director can pin cast→side deterministically via shot.lip_layout."""
    from tools.drama_lip import _explicit_layout

    shot = {"lip_layout": {"left": "ruolin", "right": "ruoxi"}}
    turns = [{"character_id": "ruolin"}, {"character_id": "ruoxi"}]
    layout = _explicit_layout("demo", shot, turns, ["ruolin", "ruoxi"], 1080, 1920)
    assert layout["ruolin"][0] < 0.3
    assert layout["ruoxi"][0] > 0.4


def test_explicit_layout_numeric_box():
    """Director can pin exact normalized boxes per character."""
    from tools.drama_lip import _coerce_box, _explicit_layout

    assert _coerce_box([0.1, 0.2, 0.3, 0.4], 1080, 1920) == (0.1, 0.2, 0.3, 0.4)
    shot = {"lip_layout": {"ruolin": [0.05, 0.1, 0.3, 0.3]}}
    layout = _explicit_layout("demo", shot, [], ["ruolin", "ruoxi"], 1080, 1920)
    assert layout["ruolin"] == (0.05, 0.1, 0.3, 0.3)


def test_lip_degradation_notice_is_recorded():
    """Degradation must never be silent — warnings + source land on the shot."""
    from tools.drama_lip import _lip_warn, _set_layout_source

    shot = {}
    _set_layout_source(shot, "color")
    _lip_warn(shot, "多人口型：ArcFace 身份锁不可用，已降级为颜色启发式定位")
    assert shot["lip_layout_source"] == "color"
    assert shot["lip_degraded"] is True
    assert shot["lip_warnings"] == ["多人口型：ArcFace 身份锁不可用，已降级为颜色启发式定位"]

    # dedup
    _lip_warn(shot, "多人口型：ArcFace 身份锁不可用，已降级为颜色启发式定位")
    assert len(shot["lip_warnings"]) == 1

