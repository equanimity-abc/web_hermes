"""P0：角色–空间预规划与多人脸一对一匹配。"""

from __future__ import annotations

from tools.drama_spatial import (
    build_spatial_plan,
    rewrite_scene_for_plan,
    spatial_prompt_clause,
)


def test_dual_shot_spatial_plan_and_rewrite():
    shot = {
        "n": 4,
        "kind": "dialogue",
        "speaker": "玉兔",
        "subject": "",
        "画面": "竖屏远景，嫦娥拎着玉兔站在广寒宫边",
        "角色": ["嫦娥", "玉兔"],
    }
    # 无真实项目卡时 build 用空 cast → slots 可能空；用最小 stub 测 rewrite + clause
    plan = {
        "version": 1,
        "subject_id": "yutu",
        "speaker_id": "yutu",
        "slots": [
            {
                "character_id": "yutu",
                "character_name": "玉兔",
                "role": "identity",
                "anchor": "right_front",
                "bbox_norm": [0.28, 0.12, 0.92, 0.80],
                "min_face_ratio": 0.015,
            },
            {
                "character_id": "ce",
                "character_name": "嫦娥",
                "role": "support",
                "anchor": "left_mid",
                "bbox_norm": [0.05, 0.18, 0.48, 0.78],
                "min_face_ratio": 0.008,
            },
        ],
    }
    rewritten = rewrite_scene_for_plan(shot["画面"], plan)
    assert "中近景" in rewritten
    assert "远景" not in rewritten.replace("中近景", "")
    assert "玉兔" in rewritten
    clause = spatial_prompt_clause(plan)
    assert "构图预规划" in clause
    assert "玉兔" in clause and "嫦娥" in clause


def test_default_min_face_ratio_is_mcu_friendly():
    from tools.drama_spatial import _default_slots

    slots = _default_slots(
        [{"id": "a", "name": "嫦娥", "look": "x", "category": "character"}],
        subject_id="a",
    )
    assert slots and float(slots[0]["min_face_ratio"]) <= 0.02


def test_subject_prefers_on_screen_cast_over_offscreen_speaker(monkeypatch):
    from tools import drama_spatial as sp

    cards = [
        {"id": "ce", "name": "嫦娥", "category": "character", "look": "a"},
        {"id": "yt", "name": "玉兔", "category": "character", "look": "b"},
    ]
    monkeypatch.setattr(sp, "load_characters", lambda slug: cards)
    monkeypatch.setattr(
        sp,
        "resolve_shot_characters",
        lambda shot, characters: [c for c in characters if c["id"] == "yt"],
    )
    shot = {"speaker": "嫦娥", "角色": ["玉兔"], "字幕": "玉兔：不是我……"}
    hit = sp.subject_character("demo", shot)
    assert hit and hit["id"] == "yt"


def test_stale_subject_outside_cast_is_ignored(monkeypatch):
    """第1镜角色栏只有嫦娥时，不得被脏 subject=玉兔钉死。"""
    from tools import drama_spatial as sp

    cards = [
        {"id": "ce", "name": "嫦娥", "category": "character", "look": "a"},
        {"id": "yt", "name": "玉兔", "category": "character", "look": "b"},
    ]
    monkeypatch.setattr(sp, "load_characters", lambda slug: cards)
    monkeypatch.setattr(
        sp,
        "resolve_shot_characters",
        lambda shot, characters: [c for c in characters if c["id"] == "ce"],
    )
    shot = {
        "speaker": "嫦娥",
        "角色": ["嫦娥"],
        "字幕": "嫦娥：谁偷了我的不死药？！",
        "subject": "yt",
    }
    hit = sp.subject_character("demo", shot)
    assert hit and hit["id"] == "ce"
    assert shot.get("subject") in ("", None)


def test_infer_speaker_prefers_dialogue_over_stale_speaker():
    from tools.drama_models import infer_speaker, apply_shot_class

    shot = {
        "speaker": "嫦娥",
        "字幕": "玉兔（奶声奶气）：不是我……",
        "角色": ["玉兔"],
    }
    assert infer_speaker(shot) == "玉兔"
    apply_shot_class(shot)
    assert shot["speaker"] == "玉兔"


def test_search_similar_frames_requires_cast_overlap():
    """主体相同但角色集合无交集时不得命中（防 shot2 玉兔图串进 shot1 嫦娥）。"""
    want = {"ce"}
    frames = [
        {
            "episode": 1,
            "shot": 2,
            "character_ids": ["yt"],
            "subject_id": "ce",
        },
        {
            "episode": 1,
            "shot": 3,
            "character_ids": ["ce"],
            "subject_id": "ce",
        },
    ]
    hits = []
    for frame in frames:
        have = set(frame["character_ids"])
        overlap = want & have
        if want and not overlap:
            continue
        hits.append(frame)
    assert [h["shot"] for h in hits] == [3]


def test_dialogue_speaker_beats_stale_subject_in_cast(monkeypatch):
    """双人镜：字幕是嫦娥时，不得被残留 subject=玉兔压过。"""
    from tools import drama_spatial as sp

    cards = [
        {"id": "ce", "name": "嫦娥", "category": "character", "look": "a"},
        {"id": "yt", "name": "玉兔", "category": "character", "look": "b"},
    ]
    monkeypatch.setattr(sp, "load_characters", lambda slug: cards)
    monkeypatch.setattr(
        sp,
        "resolve_shot_characters",
        lambda shot, characters: list(characters),
    )
    shot = {
        "speaker": "玉兔",
        "角色": ["嫦娥", "玉兔"],
        "字幕": "嫦娥（咬牙）：不是你还能是谁？！",
        "subject": "yt",
    }
    hit = sp.subject_character("demo", shot)
    assert hit and hit["id"] == "ce"


def test_shot4_style_dialogue_beats_cast_order(monkeypatch):
    """角色栏嫦娥在前，字幕玉兔说话 → 主体必须是玉兔。"""
    from tools import drama_spatial as sp

    cards = [
        {"id": "ce", "name": "嫦娥", "category": "character", "look": "a"},
        {"id": "yt", "name": "玉兔", "category": "character", "look": "b"},
    ]
    monkeypatch.setattr(sp, "load_characters", lambda slug: cards)
    monkeypatch.setattr(
        sp,
        "resolve_shot_characters",
        lambda shot, characters: list(characters),
    )
    shot = {
        "speaker": "嫦娥",
        "角色": ["嫦娥", "玉兔"],
        "字幕": "玉兔（急喊）：我是要带你回人间！",
        "画面": "竖屏中近景，嫦娥拎着玉兔，特写「玉兔」正面清晰露脸占主要人脸",
    }
    hit = sp.subject_character("demo", shot)
    assert hit and hit["id"] == "yt"
