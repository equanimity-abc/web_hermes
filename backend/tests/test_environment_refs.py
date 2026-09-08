"""P1: environment refs — scene detail, master plate, prop setting."""

from __future__ import annotations

from tools.drama_characters import (
    build_location_plate_prompt,
    environment_anchor_prompt,
    ref_plate_rel,
)


def test_build_location_plate_prompt_no_people():
    prompt = build_location_plate_prompt(
        {"name": "广寒宫前殿", "category": "scene", "look": "白玉台阶与桂树", "colors": "冷蓝"}
    )
    assert "无人物" in prompt
    assert "广寒宫前殿" in prompt
    assert "底板" in prompt


def test_environment_anchor_prompt_scene_and_prop():
    scene = environment_anchor_prompt(
        {"name": "广寒宫", "category": "scene", "look": "白玉宫殿", "colors": "冷蓝"}
    )
    assert "广寒宫" in scene
    assert "主光" in scene or "材质" in scene
    prop = environment_anchor_prompt(
        {"name": "不死药", "category": "prop", "look": "银蓝色圆形仙药"}
    )
    assert "不死药" in prop
    assert ref_plate_rel("demo", "loc1").endswith("loc1_plate.png")


def test_ensure_environment_refs_generates_detail_and_plate(monkeypatch):
    store = [
        {
            "id": "palace",
            "name": "广寒宫前殿",
            "category": "scene",
            "look": "白玉台阶，桂树成荫，冷蓝月光，石砖地面，宫殿飞檐清晰可辨，主光来自左上方",
            "ref": "",
            "ref_plate": "",
            "ref_locked": False,
            "anchor_prompt": "",
        },
        {
            "id": "pill",
            "name": "不死药",
            "category": "prop",
            "look": "银蓝光泽的圆形仙药，表面有细密云纹，体积约拇指大小，金属质感瓶塞",
            "ref": "",
            "ref_locked": False,
            "anchor_prompt": "",
        },
    ]

    def _load(_slug):
        return list(store)

    def _upsert(_slug, patch):
        cid = str(patch.get("id") or "")
        for i, rec in enumerate(store):
            if rec.get("id") == cid:
                store[i] = {**rec, **{k: v for k, v in patch.items() if v is not None}}
                return store[i]
        store.append(dict(patch))
        return store[-1]

    def _find(cards, cid):
        for c in cards or store:
            if c.get("id") == cid:
                return c
        return None

    monkeypatch.setattr("tools.drama_environment.load_characters", _load)
    monkeypatch.setattr("tools.drama_characters.load_characters", _load)
    monkeypatch.setattr("tools.drama_characters.upsert_character", _upsert)
    monkeypatch.setattr("tools.drama_characters.find_character", _find)
    monkeypatch.setattr(
        "tools.drama_characters.set_ref_locked",
        lambda slug, cid, locked: _upsert(slug, {"id": cid, "ref_locked": locked}),
    )
    monkeypatch.setattr(
        "tools.drama_characters.ref_exists",
        lambda slug, rec: bool(str((rec or {}).get("ref") or "").endswith(".png")),
    )
    monkeypatch.setattr(
        "tools.drama_characters.ref_plate_exists",
        lambda slug, rec: bool(str((rec or {}).get("ref_plate") or "").endswith("_plate.png")),
    )
    monkeypatch.setattr(
        "tools.drama_video.generate_character_portrait",
        lambda slug, rec, seed=None: f"dramas/{slug}/characters/{rec['id']}.png",
    )
    monkeypatch.setattr(
        "tools.drama_video.generate_location_plate",
        lambda slug, rec, seed=None: f"dramas/{slug}/characters/{rec['id']}_plate.png",
    )
    monkeypatch.setattr("tools.drama_common.parse_slug", lambda s: s)

    from tools.drama_environment import ensure_environment_refs

    summary = ensure_environment_refs("demo", lock=True)
    assert "palace" in summary["scenes"]
    assert "palace" in summary["plates"]
    assert "pill" in summary["props"]
    palace = next(c for c in store if c["id"] == "palace")
    assert palace["ref"].endswith("palace.png")
    assert palace["ref_plate"].endswith("palace_plate.png")
    assert palace.get("ref_locked") is True
    pill = next(c for c in store if c["id"] == "pill")
    assert pill["ref"].endswith("pill.png")
    assert pill.get("ref_locked") is True
