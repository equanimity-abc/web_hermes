"""Manual scene lock must outrank script merge / dirty / regen."""

from __future__ import annotations

from tools.drama_shots import infer_dirty, merge_from_parsed, normalize_shot
from tools.drama_video import generate_shot_candidates


def test_normalize_shot_strips_dirty_intersect_locked():
    shot = normalize_shot(
        "demo",
        1,
        {
            "n": 1,
            "画面": "locked plate",
            "locked": ["scene"],
            "dirty": ["scene", "clip", "voice"],
            "assets": {"scene": "dramas/demo/ep01/shot01/scene.png", "clip": "dramas/demo/ep01/shot01/clip.mp4"},
            "status": "dirty",
        },
    )
    assert "scene" not in shot["dirty"]
    assert shot["locked"] == ["scene"]
    assert "clip" in shot["dirty"] or "voice" in shot["dirty"] or shot["dirty"] == ["clip", "voice"]


def test_normalize_shot_whole_shot_lock_clears_dirty():
    shot = normalize_shot(
        "demo",
        1,
        {
            "n": 2,
            "locked": ["shot"],
            "dirty": ["scene", "clip", "overlay"],
            "status": "dirty",
        },
    )
    assert shot["dirty"] == []


def test_infer_dirty_skips_locked_scene_on_script_change():
    old = {
        "画面": "A",
        "地点": "厅",
        "道具": [],
        "字幕": "你好",
        "旁白": "",
        "角色": ["a"],
        "locked": ["scene"],
        "duration": 5,
        "start": 0,
        "end": 5,
        "timing": "0-5s",
    }
    new = {**old, "画面": "B", "地点": "街"}
    dirty = infer_dirty(old, new)
    assert "scene" not in dirty


def test_merge_from_parsed_keeps_manual_scene_lock(tmp_path, monkeypatch):
    slug = "lock-demo"
    monkeypatch.setattr("tools.drama_shots.load_characters", lambda _s: [])
    existing = {
        "slug": slug,
        "episode": 1,
        "shots": [
            {
                "n": 1,
                "画面": "旧画面",
                "地点": "旧地点",
                "道具": [],
                "字幕": "台词",
                "旁白": "",
                "角色": [],
                "locked": ["scene"],
                "dirty": [],
                "status": "rendered",
                "duration": 5,
                "start": 0,
                "end": 5,
                "timing": "0-5s",
                "prompt": "keep-me",
                "assets": {"scene": f"dramas/{slug}/ep01/shot01/scene.png"},
                "scene_source": "chosen",
                "chosen": "c1",
                "candidates": [],
            }
        ],
    }
    parsed = {
        "meta": {"title": "t"},
        "shots": [
            {
                "n": 1,
                "画面": "新画面会被忽略",
                "地点": "新地点",
                "道具": ["杯"],
                "字幕": "台词",
                "旁白": "",
                "角色": [],
                "duration": 5,
                "start": 0,
                "end": 5,
                "timing": "0-5s",
            }
        ],
    }
    doc = merge_from_parsed(slug, 1, parsed, existing=existing)
    shot = doc["shots"][0]
    assert shot["locked"] == ["scene"]
    assert "scene" not in (shot.get("dirty") or [])
    assert shot["画面"] == "旧画面"
    assert shot["地点"] == "旧地点"
    assert shot["prompt"] == "keep-me"


def test_generate_shot_candidates_hard_skips_locked_scene(monkeypatch):
    called = {"n": 0}

    def boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("must not generate when scene locked")

    monkeypatch.setattr("tools.drama_video.load_characters", boom)
    shot = {"n": 1, "locked": ["scene"], "candidates": [{"id": "c1"}], "assets": {}}
    out = generate_shot_candidates("demo", 1, shot, count=4)
    assert out == [{"id": "c1"}]
    assert called["n"] == 0
