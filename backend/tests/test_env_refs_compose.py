"""P2: compose env+face refs and Seedream prompt split."""

from __future__ import annotations

from tools.providers.ark_providers import _prompt_with_identity_refs


def test_prompt_splits_env_and_face():
    text = _prompt_with_identity_refs("竖屏关键帧", ref_count=2, env_ref_count=1)
    assert "环境底板" in text or "地点" in text
    assert "角色定妆" in text or "同一张脸" in text


def test_compose_shot_image_refs_orders_plate_then_face(monkeypatch, tmp_path):
    from tools import drama_qc as qc

    plate = tmp_path / "loc_plate.png"
    face = tmp_path / "face.png"
    prop = tmp_path / "prop.png"
    for p in (plate, face, prop):
        p.write_bytes(b"x" * 64)

    monkeypatch.setattr(
        qc,
        "locked_env_refs_for_shot",
        lambda slug, shot: [str(plate).replace("\\", "/"), str(prop).replace("\\", "/")],
    )
    monkeypatch.setattr(
        qc,
        "locked_face_refs_for_shot",
        lambda slug, shot: [str(face).replace("\\", "/")],
    )
    refs = qc.compose_shot_image_refs("demo", {"location_id": "loc"}, max_refs=3)
    assert refs[0].endswith("loc_plate.png") or "loc_plate" in refs[0]
    assert any("face" in r for r in refs)
    assert len(refs) <= 3
