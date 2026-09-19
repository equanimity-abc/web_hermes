"""SeriesPack schema: SSOT script pack for Ark drama pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from tools.drama_series_pack import (
    SCHEMA_VERSION,
    SeriesPack,
    dump_series_pack,
    load_series_pack_file,
    loads_series_pack,
    series_pack_json_schema,
    write_json_schema_file,
)

EXAMPLE = Path(__file__).resolve().parents[1] / "src" / "data" / "series_pack.example.json"
SCHEMA_OUT = Path(__file__).resolve().parents[1] / "src" / "tools" / "schemas" / "series_pack.schema.json"


def test_example_pack_validates():
    pack = load_series_pack_file(EXAMPLE)
    assert pack.schema_version == SCHEMA_VERSION
    assert pack.meta.aspect == "9:16"
    assert pack.style.audio_default == "native"
    assert pack.cast[0].id == "linwan"
    assert pack.episodes[0].shots[0].camera == "推"
    assert "静帧" in pack.locations[0].plate or "空镜" in pack.locations[0].plate


def test_still_rejects_process_words():
    raw = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    raw["episodes"][0]["shots"][0]["still"] = "林晚近景，然后跑向门口"
    with pytest.raises(ValidationError, match="still"):
        loads_series_pack(raw)


def test_dialogue_speaker_must_be_in_cast():
    raw = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    raw["episodes"][0]["shots"][0]["dialogue"][0]["speaker"] = "unknown"
    with pytest.raises(ValidationError):
        loads_series_pack(raw)


def test_unknown_location_rejected():
    raw = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    raw["episodes"][0]["shots"][0]["location"] = "nowhere"
    with pytest.raises(ValidationError, match="location"):
        loads_series_pack(raw)


def test_json_schema_export(tmp_path: Path):
    schema = series_pack_json_schema()
    assert "properties" in schema
    assert "meta" in schema["properties"] or "$defs" in schema or "definitions" in schema
    out = write_json_schema_file(tmp_path / "series_pack.schema.json")
    assert out.is_file()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data.get("title") == "SeriesPack" or "SeriesPack" in json.dumps(data)


def test_dump_roundtrip():
    pack = load_series_pack_file(EXAMPLE)
    text = dump_series_pack(pack)
    again = loads_series_pack(text)
    assert again.meta.title == pack.meta.title
    assert len(again.episodes[0].shots) == 3


def test_coerce_llm_dirty_fields():
    """LLM 常把 palette 写成句、gender 写成「男」、look_full 带「手持」——加载时纠偏。"""
    raw = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    raw["style"]["palette"] = "土黄、岩灰、深褐，点缀鎏金与青金蓝"
    raw["cast"][0]["gender"] = "男"
    raw["cast"][0]["look_full"] = (
        "正面全身定妆：花白短须粗布短打，手持锄头站姿挺拔，浅色纯底可辨五官服装"
    )
    pack = loads_series_pack(raw)
    assert isinstance(pack.style.palette, list)
    assert len(pack.style.palette) >= 2
    assert pack.cast[0].gender == "male"
    assert "手持" not in pack.cast[0].look_full
    assert "锄头" not in pack.cast[0].look_full


def test_coerce_llm_dialogue_line_and_kind():
    """LLM 常把台词字段写成 line、kind 写成中文「对白」——加载时吸收到 schema 字段。"""
    raw = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    shot = raw["episodes"][0]["shots"][0]
    shot["kind"] = "对白"
    shot["dialogue"] = [{"speaker": "linwan", "line": "今晚，必须走。"}]
    pack = loads_series_pack(raw)
    fixed = pack.episodes[0].shots[0]
    assert fixed.kind == "dialogue"
    assert fixed.dialogue[0].text == "今晚，必须走。"
    assert fixed.dialogue[0].speaker == "linwan"


def test_rejects_establishing_empty_shot():
    raw = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    raw["episodes"][0]["shots"][0]["kind"] = "establishing"
    with pytest.raises(ValidationError, match="禁止 establishing"):
        loads_series_pack(raw)


def test_requires_motion_for_all_shots():
    raw = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    raw["episodes"][0]["shots"][0]["motion"] = ""
    with pytest.raises(ValidationError, match="motion"):
        loads_series_pack(raw)


def test_write_canonical_schema_file():
    """Keep checked-in schema file in sync with Pydantic model."""
    write_json_schema_file(SCHEMA_OUT)
    assert SCHEMA_OUT.is_file()
    pack = SeriesPack.model_validate_json(EXAMPLE.read_text(encoding="utf-8"))
    assert pack.cast[0].name == "林晚"
