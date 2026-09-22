"""运镜关键词：避免「天花板」等误判成极端仰拍。"""

from __future__ import annotations

from tools.drama_video import _camera_style, _scene_prompt


def test_dialogue_far_shot_forces_speaker_face_lock():
    from tools.drama_video import _scene_prompt

    shot = {
        "n": 4,
        "kind": "dialogue",
        "speaker": "玉兔",
        "画面": "竖屏远景，嫦娥拎着玉兔站在广寒宫边的云海旁，玉兔突然张嘴吐出不死药",
    }
    chars = [
        {"id": "a", "name": "嫦娥", "look": "白裙"},
        {"id": "b", "name": "玉兔", "look": "兔耳髻"},
    ]
    prompt = _scene_prompt("EP01", shot, chars)
    assert "竖屏中近景" in prompt or "中近景" in prompt
    assert "远景" not in prompt.split("身份锁")[0]  # 画面侧已改写
    assert "身份锁角色「玉兔」" in prompt
    assert prompt.index("玉兔：") < prompt.index("嫦娥：")


def test_ceiling_with_closeup_is_punch_in_not_rise():
    shot = {
        "n": 2,
        "kind": "dialogue",
        "画面": "竖屏特写，嫦娥的身体开始飘向天花板，她惊恐地瞪大眼，手抓向地面",
    }
    assert _camera_style(shot) == "punch_in"


def test_sky_keywords_still_rise_without_closeup():
    shot = {"n": 1, "画面": "广角，角色凌空升向天宫，云层翻涌"}
    assert _camera_style(shot) == "rise"


def test_dialogue_rise_prompt_forbids_extreme_low_angle():
    shot = {"n": 1, "kind": "dialogue", "画面": "角色凌空升向天宫"}
    # 无特写时仍可 rise，但有角色时应软化为可辨脸
    chars = [{"name": "嫦娥", "look": "白裙"}]
    prompt = _scene_prompt("EP", shot, chars)
    assert "禁止极端低角度仰拍遮脸" in prompt
    assert "低角度仰拍，高耸建筑" not in prompt


def test_face_closeup_scene_downgraded_to_bust():
    """面部大特写/特写首帧 → 中近景胸像，避免 Seedance 图生视频被「疑似真人」拦截。"""
    shot = {
        "n": 1,
        "kind": "reaction",
        "speaker": "嫦娥",
        "画面": "竖屏面部大特写，嫦娥惊恐地瞪大眼",
    }
    chars = [{"id": "a", "name": "嫦娥", "look": "白裙"}]
    prompt = _scene_prompt("EP01", shot, chars)
    assert "竖屏面部大特写" not in prompt  # 原始特写文案被改写
    assert "中近景" in prompt
    assert "半身或胸像" in prompt
    assert "禁止面部大特写" in prompt  # 但仍显式禁止大特写


def test_plain_closeup_word_downgraded_to_bust():
    shot = {
        "n": 2,
        "kind": "dialogue",
        "speaker": "玉兔",
        "画面": "近景，玉兔凑近镜头低语",
    }
    chars = [{"id": "b", "name": "玉兔", "look": "兔耳髻"}]
    prompt = _scene_prompt("EP01", shot, chars)
    assert "中近景" in prompt
    assert "半身或胸像" in prompt
