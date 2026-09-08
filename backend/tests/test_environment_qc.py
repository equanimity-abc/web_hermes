"""P4: soft environment QC vs location plate."""

from __future__ import annotations

from pathlib import Path


def test_qc_shot_environment_closeup_skipped():
    from tools.drama_qc import qc_shot_environment

    shot = {
        "n": 1,
        "location_id": "palace",
        "kind": "dialogue",
        "size": "CU",
        "画面": "特写",
        "assets": {},
    }
    result = qc_shot_environment("demo", 1, shot, apply=False)
    assert result["status"] == "skipped"
    assert result["reason"] == "closeup"
    assert result["pass"] is True


def test_qc_shot_environment_ssim_pass(monkeypatch, tmp_path):
    from PIL import Image

    from tools import drama_qc as qc

    scene = tmp_path / "scene.png"
    plate = tmp_path / "plate.png"
    Image.new("RGB", (128, 128), (40, 60, 80)).save(scene)
    Image.new("RGB", (128, 128), (42, 62, 82)).save(plate)

    loc = {
        "id": "palace",
        "name": "广寒宫",
        "category": "scene",
        "ref_plate": str(plate),
        "ref_locked": True,
    }
    shot = {
        "n": 1,
        "location_id": "palace",
        "kind": "establishing",
        "size": "WS",
        "画面": "广寒宫全景",
        "assets": {"scene": str(scene)},
        "locked": [],
        "dirty": [],
    }

    monkeypatch.setattr(qc, "load_characters", lambda slug: [loc])
    monkeypatch.setattr(qc, "_scene_path", lambda s: scene)
    monkeypatch.setattr("tools.drama_characters.find_character", lambda cards, cid: loc)
    monkeypatch.setattr("tools.drama_characters.ref_plate_exists", lambda slug, c: True)
    monkeypatch.setattr("tools.drama_characters.environment_ref_rel", lambda slug, c: str(plate))
    monkeypatch.setattr("tools.drama_characters.normalize_category", lambda c: "scene")
    monkeypatch.setattr(qc, "resolve_safe", lambda rel: Path(rel))

    result = qc.qc_shot_environment("demo", 1, shot, apply=True, ssim_min=0.2)
    assert result["status"] == "ok"
    assert result["pass"] is True
    assert result["ssim"] >= 0.2
