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


def test_write_canonical_schema_file():
    """Keep checked-in schema file in sync with Pydantic model."""
    write_json_schema_file(SCHEMA_OUT)
    assert SCHEMA_OUT.is_file()
    pack = SeriesPack.model_validate_json(EXAMPLE.read_text(encoding="utf-8"))
    assert pack.cast[0].name == "林晚"
