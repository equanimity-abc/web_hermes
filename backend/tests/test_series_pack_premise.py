"""create_from_premise wires SeriesPack path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.drama_series_pack import load_series_pack_file


EXAMPLE = Path(__file__).resolve().parents[1] / "src" / "data" / "series_pack.example.json"


def test_create_from_premise_uses_series_pack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from tools import workspace as ws
    from tools.drama_produce import create_from_premise

    monkeypatch.setattr(ws, "workspace_root", lambda: tmp_path)
    pack = load_series_pack_file(EXAMPLE)

    def fake_gen(slug, premise, **kwargs):
        return pack

    def fake_produce(slug, episode, **kwargs):
        return {
            "ok": True,
            "job_id": f"job-{episode}",
            "status": "queued",
            "play_url": None,
        }

    monkeypatch.setattr(
        "tools.drama_series_pack_gen.generate_series_pack_from_premise",
        fake_gen,
    )
    monkeypatch.setattr("tools.drama_studio.produce_episode", fake_produce)
    # init_project_from_premise still creates real project under tmp workspace
    result = create_from_premise(
        "广寒宫侍女月蚀夜盗月核",
        slug="from-pack",
        title="广寒夜奔",
        overwrite=True,
        background=True,
    )
    assert result["ok"] is True
    assert result["slug"] == "from-pack"
    assert (tmp_path / "dramas" / "from-pack" / "series_pack.json").is_file()
    assert (tmp_path / "dramas" / "from-pack" / "characters.json").is_file()
    shots = tmp_path / "dramas" / "from-pack" / "videos" / "ep01" / "shots.json"
    assert shots.is_file()
    doc = json.loads(shots.read_text(encoding="utf-8"))
    assert doc["shots"][0]["still"]
    assert doc["shots"][0]["motion"]
    project = json.loads((tmp_path / "dramas" / "from-pack" / "project.json").read_text(encoding="utf-8"))
    assert project.get("script_schema") == "series_pack"
    assert result["scripts"][0]["source"] == "series_pack"
