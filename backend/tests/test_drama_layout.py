"""Layout SSOT: series_pack hydrates creative fields; project shell is slim."""

from __future__ import annotations

import json

from tools.drama_layout import (
    LAYOUT_VERSION,
    dump_layout_manifest,
    hydrate_characters_from_pack,
    hydrate_episode_doc_from_pack,
    slim_project_shell,
)
from tools.drama_series_pack import (
    CastMember,
    EpisodePack,
    LocationSpec,
    SeriesMeta,
    SeriesPack,
    SeriesStyle,
    ShotSpec,
)


def _mini_pack() -> SeriesPack:
    return SeriesPack(
        meta=SeriesMeta(title="测剧", logline="一句卖点足够长了", seconds_per_episode=30),
        style=SeriesStyle(
            visual="二次元赛璐璐竖屏短剧，清晰线稿，非写实",
            bgm_mood="古风励志",
            bgm_instruments="鼓点弦乐",
        ),
        cast=[
            CastMember(
                id="hero",
                name="主角",
                gender="male",
                look_full="青年男子，短发黑瞳，粗布短打，站姿挺拔，正面全身可辨五官与服装细节足够",
                look_face="剑眉星目，左眉一道浅疤",
                voice="青年男声中气足，语速偏快",
                trait="隐忍",
            )
        ],
        locations=[
            LocationSpec(
                id="yard",
                name="小院",
                plate="无人物竖屏空镜，土坯小院柴门，冷青山影压顶，暖黄油灯光",
                light="冷暖对撞",
                anchors=["柴门", "窄土路"],
            )
        ],
        episodes=[
            EpisodePack(
                n=1,
                title="开篇",
                beat="钩子",
                shots=[
                    ShotSpec(
                        n=1,
                        t_in=0,
                        t_out=3,
                        kind="dialogue",
                        cast=["hero"],
                        location="yard",
                        props=[],
                        shot_size="近景",
                        camera="推",
                        still="青年男子站在柴门前仰望巨山，正面近景面部清晰",
                        motion="缓缓抬头，握紧拳头",
                        dialogue=[],
                    )
                ],
            )
        ],
    )


def test_slim_project_shell_drops_logline_dup():
    pack = _mini_pack()
    slim = slim_project_shell(
        {"slug": "demo", "title": "旧标题", "logline": "旧梗概很长", "episodes": []},
        pack,
    )
    assert slim["layout_version"] == LAYOUT_VERSION
    assert slim["script_schema"] == "series_pack"
    assert slim["logline"] == ""
    assert slim["title"] == "测剧"
    assert slim["episodes"][0]["n"] == 1
    assert "path" not in slim["episodes"][0]


def test_hydrate_characters_from_pack_overrides_look():
    pack = _mini_pack()
    rows = [
        {
            "id": "hero",
            "pack_id": "hero",
            "name": "旧名",
            "look": "旧外形",
            "look_face": "旧脸",
            "category": "character",
            "ref": "dramas/demo/characters/hero.png",
        }
    ]
    out = hydrate_characters_from_pack(rows, pack)
    assert out[0]["name"] == "主角"
    assert "粗布短打" in out[0]["look"]
    assert "浅疤" in out[0]["look_face"]
    assert out[0]["_creative_ssot"] == "series_pack"


def test_hydrate_episode_doc_from_pack_overrides_still():
    pack = _mini_pack()
    doc = {
        "slug": "demo",
        "episode": 1,
        "shots": [
            {
                "n": 1,
                "画面": "旧画面",
                "still": "旧still",
                "candidates": [{"id": "c1"}],
                "locked": ["scene"],
            }
        ],
    }
    out = hydrate_episode_doc_from_pack(doc, pack)
    assert "仰望巨山" in out["shots"][0]["画面"] or "仰望巨山" in out["shots"][0]["still"]
    assert out["shots"][0]["candidates"] == [{"id": "c1"}]
    assert out["shots"][0]["locked"] == ["scene"]
    assert out["creative_ssot"] == "series_pack"
    assert "古风励志" in (out.get("meta") or {}).get("配乐", "")


def test_layout_manifest():
    m = dump_layout_manifest("any-slug")
    assert m["layout_version"] == LAYOUT_VERSION
    assert "bible.md" in m["files"]["deprecated_as_ssot"]
    assert m["files"]["assets_runtime"].endswith("characters.json")


def test_script_markdown_from_doc_has_shot_heads():
    from tools.drama_layout import script_markdown_from_doc, _is_usable_script

    md = script_markdown_from_doc(
        {
            "title": "开篇",
            "episode": 1,
            "meta": {"时长": "30s", "配乐": "鼓点"},
            "shots": [
                {
                    "n": 1,
                    "duration": 3,
                    "still": "青年站柴门前",
                    "画面": "青年站柴门前",
                    "地点": "小院",
                    "角色": ["主角"],
                    "字幕": "我要移山",
                }
            ],
        }
    )
    assert _is_usable_script(md)
    assert "### Shot 1" in md
    assert "青年站柴门前" in md
    assert not _is_usable_script("# 已迁移\n\n请编辑 series_pack.json")
    assert not _is_usable_script("")


def test_resolve_episode_script_from_shots(tmp_path, monkeypatch):
    from tools import drama_layout as layout
    from tools import workspace as ws

    monkeypatch.setattr(ws, "workspace_root", lambda: tmp_path)
    monkeypatch.setattr(layout, "load_pack_or_none", lambda _s: None)

    slug = "demo"
    work = tmp_path / "dramas" / slug / "videos" / "ep01"
    work.mkdir(parents=True)
    doc = {
        "slug": slug,
        "episode": 1,
        "title": "开篇",
        "shots": [{"n": 1, "duration": 3, "still": "仰望巨山", "画面": "仰望巨山", "角色": ["主角"]}],
    }
    (work / "shots.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    resolved = layout.resolve_episode_script(slug, 1)
    assert resolved
    assert "### Shot 1" in resolved
    assert "仰望巨山" in resolved


def test_resolve_episode_script_from_pack(tmp_path, monkeypatch):
    from tools import drama_layout as layout
    from tools import workspace as ws

    monkeypatch.setattr(ws, "workspace_root", lambda: tmp_path)
    monkeypatch.setattr(layout, "load_pack_or_none", lambda _s: _mini_pack())

    resolved = layout.resolve_episode_script("demo", 1)
    assert resolved
    assert "### Shot 1" in resolved
    assert "仰望巨山" in resolved or "柴门" in resolved


def test_default_draft_retries_empty(monkeypatch):
    from tools import drama_series_pack_gen as gen

    calls = {"n": 0}

    def _fake(_slug, _prompt, *, system=""):
        calls["n"] += 1
        if calls["n"] < 3:
            return ""
        return '{"ok": true}'

    monkeypatch.setattr("tools.drama_script.draft_text_sync", _fake)
    out = gen._default_draft("s", "p", system="sys")
    assert out == '{"ok": true}'
    assert calls["n"] == 3
