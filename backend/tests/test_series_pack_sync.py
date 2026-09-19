"""sync_asset_to_series_pack copies card edits back into series_pack.json."""

from __future__ import annotations

import json
from pathlib import Path

from tools.drama_series_pack import load_series_pack_file
from tools.drama_series_pack_gen import save_series_pack
from tools.drama_series_pack_materialize import sync_asset_to_series_pack


EXAMPLE = Path(__file__).resolve().parents[1] / "src" / "data" / "series_pack.example.json"


def test_sync_character_look_to_series_pack(tmp_path, monkeypatch):
    from tools import workspace as ws

    monkeypatch.setattr(ws, "workspace_root", lambda: tmp_path)
    slug = "sync-pack"
    root = tmp_path / "dramas" / slug
    root.mkdir(parents=True)
    pack = load_series_pack_file(EXAMPLE)
    save_series_pack(slug, pack)

    ok = sync_asset_to_series_pack(
        slug,
        {
            "id": "linwan",
            "pack_id": "linwan",
            "category": "character",
            "name": "林晚",
            "look": "新全身定妆描述，瓜子脸，墨黑长直发，朱红滚边袍，正面全身站立浅色纯底",
            "look_face": "新正脸锚点杏眼浅棕瞳",
            "gender": "female",
            "age_band": "18-22",
            "voice_hint": "女，18-22，中高音，语速中偏快",
            "voice": "zh_female_vv_uranus_bigtts",
            "trait": "决断",
            "catchphrase": "必须走",
        },
    )
    assert ok is True
    raw = json.loads((root / "series_pack.json").read_text(encoding="utf-8"))
    cast = next(c for c in raw["cast"] if c["id"] == "linwan")
    assert cast["look_full"].startswith("新全身定妆")
    assert cast["look_face"].startswith("新正脸")
    assert cast["trait"] == "决断"
    assert cast["voice_id"] == "zh_female_vv_uranus_bigtts"
