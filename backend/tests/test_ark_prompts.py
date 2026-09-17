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


def test_shot_frame_writing_rule_mentions_seedance():
    assert "Seedance" in SHOT_FRAME_WRITING_RULE
    assert "运镜" in SHOT_FRAME_WRITING_RULE
