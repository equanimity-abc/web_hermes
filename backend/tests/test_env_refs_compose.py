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
    # 定场：环境优先
    refs = qc.compose_shot_image_refs(
        "demo", {"location_id": "loc", "kind": "establishing", "size": "WS"}, max_refs=3
    )
    assert refs[0].endswith("loc_plate.png") or "loc_plate" in refs[0]
    assert any("face" in r for r in refs)
    assert len(refs) <= 3
    # 对话近景：脸优先（身份锁）
    refs_d = qc.compose_shot_image_refs(
        "demo", {"location_id": "loc", "kind": "dialogue", "size": "MCU"}, max_refs=3
    )
    assert refs_d[0].endswith("face.png") or "face" in refs_d[0]


def test_hq_skips_layered_compositing_by_default():
    """专业档默认关闭 bbox 贴层（DRAMA_LAYERED_SCENE=0）。"""
    from config import config

    assert str(getattr(config, "DRAMA_LAYERED_SCENE", "0") or "0").strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    )


def test_compose_shot_image_refs_faces_capped_at_two(monkeypatch, tmp_path):
    """Plan: env 1 + face ≤2; without plate, still at most 2 faces."""
    from tools import drama_qc as qc

    faces = []
    for i in range(4):
        p = tmp_path / f"face{i}.png"
        p.write_bytes(b"x" * 64)
        faces.append(str(p).replace("\\", "/"))

    monkeypatch.setattr(qc, "locked_env_refs_for_shot", lambda slug, shot: [])
    monkeypatch.setattr(qc, "locked_face_refs_for_shot", lambda slug, shot: faces)
    refs = qc.compose_shot_image_refs("demo", {"n": 1}, max_refs=3)
    assert len(refs) == 2
    assert all("face" in r for r in refs)


def test_scene_prompt_includes_location_anchor(monkeypatch):
    from tools.drama_video import _scene_prompt

    monkeypatch.setattr(
        "tools.drama_characters.load_characters",
        lambda slug: [
            {
                "id": "palace",
                "name": "广寒宫前殿",
                "category": "scene",
                "look": "白玉台阶桂树",
                "anchor_prompt": "飞檐轮廓稳定",
                "colors": "冷蓝",
            }
        ],
    )
    monkeypatch.setattr(
        "tools.drama_characters.find_character",
        lambda cards, cid: next((c for c in cards if c["id"] == cid), None),
    )
    monkeypatch.setattr("tools.drama_styles.style_prompt_clause", lambda *a, **k: "")
    monkeypatch.setattr("tools.drama_spatial.spatial_prompt_clause", lambda plan: "")
    text = _scene_prompt(
        "测试集",
        {
            "画面": "嫦娥立于殿前",
            "location_id": "palace",
            "prop_ids": [],
            "角色": ["嫦娥"],
            "kind": "establishing",
        },
        [
            {"id": "c1", "name": "嫦娥", "category": "character", "look": "白衣"},
        ],
        slug="demo",
    )
    assert "广寒宫前殿" in text
    assert "白玉台阶" in text or "飞檐" in text or "冷蓝" in text
