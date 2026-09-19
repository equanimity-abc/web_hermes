"""Ark prompt builders for Seedream / Seedance."""

from __future__ import annotations

from tools.drama_ark_prompts import (
    SHOT_FRAME_WRITING_RULE,
    build_seedance_i2v_prompt,
    build_seedream_video_still_prompt,
    camera_motion_zh,
)
from tools.drama_characters import ANIME_STYLE_GUARD
from tools.drama_i2v import _motion_prompt


def test_camera_motion_zh_maps_punch_in():
    assert "前推" in camera_motion_zh("punch_in")


def test_seedream_still_marks_video_frame():
    text = build_seedream_video_still_prompt(
        title="EP01",
        scene="中景，少女望向窗外",
        style_guard=ANIME_STYLE_GUARD,
    )
    assert "视频静帧" in text
    assert "Seedance" in text
    assert "9:16" in text
    assert ANIME_STYLE_GUARD in text


def test_seedance_i2v_default_includes_dialogue_when_generate_audio():
    shot = {
        "画面": "近景，少女皱眉抬头",
        "camera": "punch_in",
        "字幕": "林晚：今晚必须离开。",
    }
    text = build_seedance_i2v_prompt(
        shot,
        style_guard=ANIME_STYLE_GUARD,
        generate_audio=True,
        manual_voice=False,
    )
    assert "主体必须与首帧" in text
    assert "运镜" in text
    assert "今晚必须离开" in text
    assert "口型" in text


def test_seedance_i2v_manual_voice_skips_invented_lines():
    shot = {
        "画面": "近景对白",
        "camera": "punch_in",
        "字幕": "林晚：你好世界专用句。",
        "manual_voice": True,
    }
    text = build_seedance_i2v_prompt(
        shot,
        generate_audio=False,
        manual_voice=True,
    )
    assert "参考音频" in text
    assert "你好世界专用句" not in text


def test_seedance_i2v_identity_clause():
    from tools.drama_ark_prompts import build_seedance_identity_ref_clause, build_seedance_i2v_prompt

    clause = build_seedance_identity_ref_clause(face_index=2, body_index=3)
    assert "@图片2" in clause and "@图片3" in clause
    assert "大头照" in clause and "全身照" in clause
    assert "三视图" in clause
    text = build_seedance_i2v_prompt(
        {"画面": "近景抬头", "camera": "punch_in"},
        identity_ref_clause=clause,
        generate_audio=False,
    )
    assert "@图片2" in text and "大头照" in text


def test_motion_prompt_wired():
    text = _motion_prompt(
        {
            "画面": "中景，少年握拳",
            "camera": "punch_in",
            "字幕": "",
            "manual_voice": False,
        }
    )
    assert "首帧" in text
    assert "运镜" in text
    assert ANIME_STYLE_GUARD in text


def test_motion_prompt_includes_identity_when_indexed():
    text = _motion_prompt(
        {
            "画面": "近景对白",
            "camera": "punch_in",
            "字幕": "",
            "manual_voice": False,
            "_seedance_face_image_index": 2,
            "_seedance_body_image_index": 3,
        }
    )
    assert "@图片2" in text and "@图片3" in text


def test_shot_frame_writing_rule_mentions_seedance():
    assert "Seedance" in SHOT_FRAME_WRITING_RULE
    assert "运镜" in SHOT_FRAME_WRITING_RULE
