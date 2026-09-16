"""Stale merge after rerender must not wipe lip_source."""

from __future__ import annotations


def test_refresh_shot_from_disk_keeps_lip_source(tmp_path, monkeypatch):
    from tools import drama_produce as dp

    disk_shot = {
        "n": 1,
        "lip_source": "pixverse",
        "lip_score": {"ok": True},
        "assets": {"lip": "dramas/x/videos/ep01/shot01_lip.mp4"},
    }
    mem_shot = {
        "n": 1,
        "lip_source": "",
        "assets": {"lip": "dramas/x/videos/ep01/shot01_lip.mp4"},
        "_flicker_only_repair": True,
    }

    monkeypatch.setattr(
        "tools.drama_shots.load_doc",
        lambda slug, ep: {"shots": [disk_shot]},
    )
    monkeypatch.setattr(
        "tools.drama_shots.find_shot",
        lambda doc, sn: disk_shot if int(sn) == 1 else None,
    )

    out = dp._refresh_shot_from_disk("x", 1, mem_shot)
    assert out is mem_shot
    assert mem_shot["lip_source"] == "pixverse"
    assert mem_shot["lip_score"] == {"ok": True}
    assert mem_shot.get("_flicker_only_repair") is True


def test_assert_studio_lip_recovers_orphan(monkeypatch, tmp_path):
    from tools import drama_quality as dq

    lip = tmp_path / "shot01_lip.mp4"
    voice = tmp_path / "shot01.mp3"
    lip.write_bytes(b"x" * 2000)
    voice.write_bytes(b"y" * 2000)

    shot = {
        "n": 1,
        "lip_source": "",
        "assets": {"lip": str(lip), "voice": str(voice)},
        "字幕": "角色：「你好」",
        "kind": "dialogue",
    }

    monkeypatch.setattr(
        "tools.drama_profiles.resolve_quality_profile",
        lambda slug: "studio",
    )
    monkeypatch.setattr(
        "tools.drama_lip.lip_eligible",
        lambda shot, models=None: {"ok": True},
    )
    monkeypatch.setattr(
        "tools.providers.lip_providers.lip_video_usable",
        lambda shot, path: (shot.__setitem__("lip_source", "recovered") or True),
    )
    monkeypatch.setattr(
        "tools.workspace.resolve_safe",
        lambda rel: lip if "lip" in str(rel) else voice,
    )

    dq.assert_studio_lip_shot("x", shot)
    assert shot["lip_source"] == "recovered"
