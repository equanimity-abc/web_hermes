"""P3: layered scene reuses locked location plate."""

from __future__ import annotations

from pathlib import Path


def test_layered_reuses_locked_location_plate(monkeypatch, tmp_path):
    from PIL import Image

    from tools import drama_layers as layers

    slug = "demo"
    plate_src = tmp_path / "loc_plate.png"
    Image.new("RGB", (256, 448), (20, 40, 60)).save(plate_src)

    shot = {
        "n": 1,
        "画面": "嫦娥站在广寒宫",
        "location_id": "palace",
        "spatial_plan": {
            "slots": [
                {
                    "character_id": "change",
                    "character_name": "嫦娥",
                    "role": "identity",
                    "anchor": "center_front",
                    "bbox_norm": [0.2, 0.15, 0.8, 0.85],
                }
            ]
        },
    }

    char = {
        "id": "change",
        "name": "嫦娥",
        "category": "character",
        "ref": "dramas/demo/characters/change.png",
        "ref_locked": True,
    }
    loc = {
        "id": "palace",
        "name": "广寒宫",
        "category": "scene",
        "ref_plate": str(plate_src),
        "ref_locked": True,
        "look": "白玉宫殿",
    }

    monkeypatch.setattr(layers, "load_characters", lambda s: [char, loc])
    monkeypatch.setattr(layers, "character_requires_face_identity", lambda c: c.get("id") == "change")
    monkeypatch.setattr(layers, "build_spatial_plan", lambda slug, shot: shot["spatial_plan"])
    monkeypatch.setattr(
        layers,
        "layer_rel",
        lambda slug, ep, n, kind, cid="": f"dramas/{slug}/videos/ep01/shot01_{kind}{('_'+cid) if cid else ''}.png",
    )

    def _resolve(rel: str):
        path = Path(rel)
        if path.is_absolute():
            return path
        return tmp_path / Path(str(rel).replace("\\", "/")).name

    monkeypatch.setattr(layers, "resolve_safe", _resolve)

    called = {"gen": 0}

    def _gen(*args, **kwargs):
        called["gen"] += 1
        dest = args[1] if len(args) > 1 else kwargs.get("dest")
        Image.new("RGB", (128, 224), (90, 90, 90)).save(dest)
        return True

    monkeypatch.setattr("tools.drama_video._generate_scene_image", _gen)
    monkeypatch.setattr("tools.drama_qc._char_ref_path", lambda slug, c: str(tmp_path / "face.png"))
    monkeypatch.setattr("tools.drama_characters.ref_exists", lambda slug, c: True)
    monkeypatch.setattr("tools.drama_characters.ref_plate_exists", lambda slug, c: c.get("id") == "palace")
    monkeypatch.setattr("tools.drama_characters.environment_ref_rel", lambda slug, c: str(plate_src))
    monkeypatch.setattr(
        "tools.drama_characters.find_character",
        lambda cards, cid: next((x for x in cards if x["id"] == cid), None),
    )
    monkeypatch.setattr("tools.drama_characters.normalize_category", lambda c: str(c or "character"))
    Image.new("RGB", (64, 64), (200, 160, 140)).save(tmp_path / "face.png")

    dest = tmp_path / "out.png"
    result = layers.generate_layered_scene(slug, 1, shot, dest, title="测试", seed=1)
    assert result.get("ok") is True
    assert result.get("plate_source") == "reused"
    assert called["gen"] >= 1  # character layer still generated
    assert dest.is_file()
