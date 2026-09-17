"""SeriesPack copy-only materialize (no look/plate/still expansion)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.drama_series_pack import load_series_pack_file
from tools.drama_series_pack_materialize import (
    copy_motion_prompt,
    copy_still_prompt,
    format_dialogue_subtitle,
    materialize_series_pack,
    pack_shot_to_legacy,
)

EXAMPLE = Path(__file__).resolve().parents[1] / "src" / "data" / "series_pack.example.json"


def test_format_dialogue_and_legacy_shot():
    pack = load_series_pack_file(EXAMPLE)
    shot = pack.episodes[0].shots[0]
    cast = {c.id: c.name for c in pack.cast}
    loc = {x.id: x.name for x in pack.locations}
    prop = {p.id: p.name for p in pack.props}
    legacy = pack_shot_to_legacy(
        shot,
        cast_name_by_id=cast,
        loc_name_by_id=loc,
        prop_name_by_id=prop,
    )
    assert legacy["画面"] == shot.still
    assert legacy["still"] == shot.still
    assert legacy["motion"] == shot.motion
    assert legacy["camera"] == "推"
    assert "林晚" in legacy["字幕"]
    assert legacy["角色"] == ["linwan"]


def test_copy_prompts_prefer_still_motion():
    shot = {
        "still": "静帧A",
        "画面": "旧画面不应优先",
        "motion": "抬手说话",
        "shot_size": "近景",
        "camera": "推",
    }
    assert "静帧A" in copy_still_prompt(shot)
    assert "旧画面" not in copy_still_prompt(shot)
    motion = copy_motion_prompt(shot)
    assert "抬手说话" in motion
    assert "近景" in motion
    assert "推" in motion


def test_materialize_copies_look_without_expansion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from tools import workspace as ws

    monkeypatch.setattr(ws, "workspace_root", lambda: tmp_path)
    slug = "pack-mat"
    (tmp_path / "dramas" / slug).mkdir(parents=True)
    pack = load_series_pack_file(EXAMPLE)
    look = pack.cast[0].look_full
    plate = pack.locations[0].plate

    result = materialize_series_pack(slug, pack)
    assert result["ok"] is True

    chars = json.loads((tmp_path / "dramas" / slug / "characters.json").read_text(encoding="utf-8"))
    by_id = {c["id"]: c for c in chars["characters"]}
    assert by_id["linwan"]["look"] == look
    assert look in by_id["guanghan_stair"]["look"] or by_id["guanghan_stair"]["look"].startswith(plate[:20])
    # plate 正文必须原样出现，允许后缀附加光影（仍是拷贝字段）
    assert plate in by_id["guanghan_stair"]["look"]

    shots_path = tmp_path / "dramas" / slug / "videos" / "ep01" / "shots.json"
    assert shots_path.is_file()
    doc = json.loads(shots_path.read_text(encoding="utf-8"))
    assert doc["shots"][0]["still"] == pack.episodes[0].shots[0].still
    assert doc["shots"][0]["motion"] == pack.episodes[0].shots[0].motion
    assert doc["shots"][0]["画面"] == pack.episodes[0].shots[0].still


def test_subtitle_format():
    text = format_dialogue_subtitle(
        [{"speaker": "linwan", "text": "走", "emotion": "压抑"}],
        {"linwan": "林晚"},
    )
    assert text == "林晚（压抑）：走"
