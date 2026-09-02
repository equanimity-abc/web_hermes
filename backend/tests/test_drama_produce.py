"""Tests for HQ autopilot helpers."""

from __future__ import annotations

from tools.drama_produce import (
    ensure_characters_from_shots,
    ensure_default_bgm,
    extract_single_episode_markdown,
    parse_series_spec,
    suggest_project_slug,
)


def test_suggest_slug_from_ascii_title():
    assert suggest_project_slug("重生复仇", "Rebirth Heiress") == "rebirth-heiress"


def test_suggest_slug_from_chinese_falls_back_to_hash():
    slug = suggest_project_slug("被赶出家门的豪门养女重生复仇")
    assert slug.startswith("drama-")
    assert len(slug) <= 40


def test_parse_series_spec_from_chinese_premise():
    spec = parse_series_spec("帮我制作《大闹天宫》AI漫剧，共3集，每集60秒")
    assert spec["episode_count"] == 3
    assert spec["seconds_per_episode"] == 60
    assert spec["count_explicit"] is True
    assert spec["shot_min"] <= spec["shot_max"]


def test_parse_series_spec_defaults_one_episode_when_unspecified():
    spec = parse_series_spec("帮我做一部重生复仇漫剧")
    assert spec["episode_count"] == 1
    assert spec["count_explicit"] is False
    assert spec["seconds_per_episode"] == 60
    # 只说时长、没说集数 → 仍默认 1 集
    spec2 = parse_series_spec("做一部竖屏漫剧，每集45秒")
    assert spec2["episode_count"] == 1
    assert spec2["count_explicit"] is False
    assert spec2["seconds_per_episode"] == 45


def test_parse_series_spec_ignores_di_n_ji_as_series_count():
    # 「第2集」是集号，不是「做成2集」
    spec = parse_series_spec("帮我重做第2集的旁白")
    assert spec["episode_count"] == 1
    assert spec["count_explicit"] is False


def test_parse_series_spec_agent_default_one_does_not_override_premise():
    spec = parse_series_spec("共3集每集60秒", episode_count=1)
    assert spec["episode_count"] == 3


def test_parse_series_spec_overrides_and_defaults():
    assert parse_series_spec("随便一个故事")["episode_count"] == 1
    assert parse_series_spec("随便一个故事")["seconds_per_episode"] == 60
    spec = parse_series_spec("随便", episode_count=2, seconds=30)
    assert spec["episode_count"] == 2
    assert spec["seconds_per_episode"] == 30
    assert parse_series_spec("每集约一分钟")["seconds_per_episode"] == 60
    assert parse_series_spec("制作三集，每集60秒")["episode_count"] == 3


def test_extract_single_episode_markdown_keeps_only_requested_ep():
    raw = """# EP01 石猴出世
- 时长: 60s
## 分镜
### Shot 1 (0-3s)
- 画面: a

---

# EP02 大闹天宫
- 时长: 60s
## 分镜
### Shot 1 (0-3s)
- 画面: b

# EP03 齐天大圣
- 时长: 60s
## 分镜
### Shot 1 (0-3s)
- 画面: c
"""
    ep1 = extract_single_episode_markdown(raw, 1)
    assert "EP01" in ep1
    assert "EP02" not in ep1
    assert "画面: a" in ep1
    assert "画面: b" not in ep1
    ep2 = extract_single_episode_markdown(raw, 2)
    assert "EP02" in ep2
    assert "画面: b" in ep2
    assert "画面: a" not in ep2


def test_ensure_characters_from_shots_creates_missing(tmp_path, monkeypatch):
    slug = "demo_auto"
    doc = {
        "shots": [
            {"n": 1, "角色": "林晚", "字幕": ""},
            {"n": 2, "角色": "林薇薇", "字幕": ""},
        ]
    }

    store: list[dict] = []

    monkeypatch.setattr("tools.drama_characters.load_characters", lambda s: list(store))
    monkeypatch.setattr(
        "tools.drama_characters.upsert_character",
        lambda s, patch: {**patch, "id": patch.get("id") or "x", "category": "character"},
    )
    monkeypatch.setattr(
        "tools.drama_characters.match_character_token",
        lambda token, cards: None,
    )
    monkeypatch.setattr(
        "tools.drama_characters.infer_roles_from_dialogue",
        lambda dialogue, cards: [],
    )

    created = ensure_characters_from_shots(slug, doc)
    assert len(created) == 2


def test_ensure_default_bgm_uses_catalog(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr("tools.drama_audio.has_bgm", lambda mix: False)
    monkeypatch.setattr("tools.drama_audio.load_mix", lambda slug, ep: {"bgm": {}})
    monkeypatch.setattr(
        "tools.drama_audio.load_catalog",
        lambda slug: {
            "tracks": [
                {
                    "id": "rebirth_resolve",
                    "path": "shared/x.mp3",
                    "license": "catalog:rebirth_resolve",
                }
            ]
        },
    )
    monkeypatch.setattr(
        "tools.drama_audio.patch_mix",
        lambda slug, ep, patch: calls.append(patch.get("catalog_id", "")) or {},
    )

    assert ensure_default_bgm("demo", 1) is True
    assert calls == ["rebirth_resolve"]
