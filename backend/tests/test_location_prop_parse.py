"""P0: location/prop script fields, extraction, and auto card binding."""

from __future__ import annotations

from tools.drama_environment import (
    ensure_locations_and_props_from_shots,
    extract_location_from_scene,
    extract_props_from_scene,
    normalize_location_name,
    normalize_prop_names,
)
from tools.drama_script import format_episode_markdown, scrub_script_markdown
from tools.drama_video import parse_episode_markdown


def test_parse_episode_markdown_location_and_props():
    md = """# 测试
- 时长: 20s

## 分镜
### Shot 1 (0-7s)
- 画面: 嫦娥站在广寒宫前殿
- 地点: 广寒宫前殿
- 道具: 不死药、佩剑
- 字幕: 嫦娥: 来了
- 旁白:
- 角色: 嫦娥
"""
    parsed = parse_episode_markdown(md)
    shot = parsed["shots"][0]
    assert shot["地点"] == "广寒宫前殿"
    assert "不死药" in shot["道具"]
    assert "佩剑" in shot["道具"]


def test_format_and_scrub_keeps_location_props():
    parsed = {
        "title": "测试",
        "meta": {"时长": "20s"},
        "shots": [
            {
                "n": 1,
                "timing": "0-7s",
                "画面": "嫦娥立于殿前",
                "地点": "广寒宫前殿",
                "道具": ["不死药"],
                "字幕": "嫦娥: 嗯",
                "旁白": "",
                "角色": "嫦娥",
            }
        ],
    }
    md = format_episode_markdown(parsed)
    assert "- 地点: 广寒宫前殿" in md
    assert "- 道具: 不死药" in md
    cleaned = scrub_script_markdown("好的，已修改：\n\n" + md + "\n希望满意")
    assert "- 地点: 广寒宫前殿" in cleaned
    assert "希望满意" not in cleaned


def test_extract_location_and_props_from_scene_prose():
    scene = "竖屏近景，嫦娥站在广寒宫前殿台阶上，指尖攥着不死药"
    assert normalize_location_name(extract_location_from_scene(scene)) == "广寒宫前殿"
    props = extract_props_from_scene(scene, exclude={"嫦娥"})
    assert "不死药" in props


def test_normalize_prop_names_dedupes():
    assert normalize_prop_names("不死药、佩剑、不死药") == ["不死药", "佩剑"]
    assert normalize_prop_names(["A", "A", "B"]) == ["A", "B"]


def test_ensure_locations_and_props_from_shots_creates_cards(monkeypatch):
    store: list[dict] = []

    def _load(_slug: str):
        return list(store)

    def _upsert(_slug: str, patch: dict):
        rec = {
            "id": str(patch.get("id") or patch.get("name") or "x"),
            "name": patch.get("name"),
            "category": patch.get("category") or "character",
            "look": patch.get("look") or "",
            "aliases": list(patch.get("aliases") or []),
            "colors": patch.get("colors") or "",
        }
        store[:] = [rec if c.get("id") == rec["id"] else c for c in store]
        if not any(c.get("id") == rec["id"] for c in store):
            store.append(rec)
        return rec

    monkeypatch.setattr("tools.drama_environment.load_characters", _load)
    monkeypatch.setattr("tools.drama_environment.upsert_character", _upsert)
    monkeypatch.setattr("tools.drama_environment.match_character_token", lambda token, cards: None)

    # Re-import match path uses module-level; ensure match_asset_token uses patched load
    from tools import drama_environment as env

    monkeypatch.setattr(env, "load_characters", _load)
    monkeypatch.setattr(env, "upsert_character", _upsert)

    def _match_token(token, characters):
        for c in characters:
            if c.get("name") == token or token in (c.get("aliases") or []):
                return c
        return None

    monkeypatch.setattr(env, "match_character_token", _match_token)

    doc = {
        "shots": [
            {
                "n": 1,
                "画面": "嫦娥站在广寒宫前殿，手握不死药",
                "地点": "广寒宫前殿",
                "道具": "不死药",
                "角色": ["嫦娥"],
            },
            {
                "n": 2,
                "画面": "竖屏中景，嫦娥仍站在广寒宫前殿",
                "地点": "",
                "道具": "",
                "角色": ["嫦娥"],
            },
        ]
    }
    summary = ensure_locations_and_props_from_shots("demo", doc)
    assert summary["locations_created"]
    assert summary["props_created"]
    assert doc["shots"][0]["location_id"]
    assert doc["shots"][0]["prop_ids"]
    # Shot 2 should inherit/extract same location via heuristic + name match
    assert doc["shots"][1]["地点"]
    assert doc["shots"][1]["location_id"] == doc["shots"][0]["location_id"]
    cats = {c["category"] for c in store}
    assert "scene" in cats
    assert "prop" in cats


def test_ensure_merges_prop_aliases(monkeypatch):
    store = [
        {
            "id": "pill",
            "name": "不死药",
            "category": "prop",
            "look": "仙药",
            "aliases": ["不死药"],
        }
    ]

    def _load(_slug):
        return list(store)

    def _upsert(_slug, patch):
        cid = str(patch.get("id") or "")
        for i, rec in enumerate(store):
            if rec.get("id") == cid or rec.get("name") == patch.get("name"):
                store[i] = {**rec, **{k: v for k, v in patch.items() if v is not None}}
                return store[i]
        rec = {
            "id": str(patch.get("id") or patch.get("name") or "x"),
            "name": patch.get("name"),
            "category": patch.get("category") or "character",
            "look": patch.get("look") or "",
            "aliases": list(patch.get("aliases") or []),
        }
        store.append(rec)
        return rec

    from tools import drama_environment as env

    monkeypatch.setattr(env, "load_characters", _load)
    monkeypatch.setattr(env, "upsert_character", _upsert)

    def _match_token(token, characters, category=None):
        for c in characters:
            if category and c.get("category") != category:
                continue
            if c.get("name") == token or token in (c.get("aliases") or []):
                return c
        return None

    monkeypatch.setattr(env, "match_character_token", lambda token, characters: None)
    monkeypatch.setattr(env, "match_asset_token", _match_token)

    doc = {
        "shots": [
            {
                "n": 1,
                "画面": "手握仙丹",
                "地点": "",
                "道具": "仙丹",
                "角色": [],
            }
        ]
    }
    # First bind with alias name that should merge onto 不死药 if match finds it
    # Simulate match by name alias via custom match that maps 仙丹 → pill when we add alias after first create
    def _match_asset(token, characters, category=None):
        for c in characters:
            if category and str(c.get("category") or "") != category:
                continue
            if c.get("name") == token or token in (c.get("aliases") or []):
                return c
            # treat 仙丹 as synonym of 不死药 for this test once card exists
            if token == "仙丹" and c.get("name") == "不死药":
                return c
        return None

    monkeypatch.setattr(env, "match_asset_token", _match_asset)
    summary = ensure_locations_and_props_from_shots("demo", doc)
    assert doc["shots"][0]["prop_ids"] == ["pill"]
    pill = next(c for c in store if c["id"] == "pill")
    assert "仙丹" in (pill.get("aliases") or [])
    assert not summary["props_created"]  # reused existing card
