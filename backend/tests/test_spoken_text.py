from tools.drama_video import (
    clean_subtitle,
    is_inner_monologue,
    monologue_display_text,
    spoken_text,
    spoken_text_for_shot,
)


def test_spoken_text_extracts_quotes_and_drops_stagecraft():
    raw = '林薇薇（夸张地）: “哎呀！对不起姐姐！” 林晚（低头）: “没关系。”'
    assert spoken_text(raw) == "哎呀！对不起姐姐！没关系。"


def test_spoken_text_strips_speaker_prefix():
    assert spoken_text("林晚: 没关系。") == "没关系。"


def test_spoken_text_does_not_fall_back_to_subtitle():
    assert spoken_text("", "第一回合，开始。") == ""


def test_clean_subtitle_keeps_narrative():
    assert clean_subtitle("第一回合，开始。") == "第一回合，开始。"


def test_spoken_text_for_shot_uses_speaker_lines_only():
    shot = {
        "speaker": "林晚",
        "对白": '林薇薇（夸张地）: “哎呀！对不起姐姐！” 林晚（低头）: “没关系。一件衣服而已。”',
    }
    assert spoken_text_for_shot(shot) == "没关系。一件衣服而已。"


def test_spoken_text_for_shot_fuzzy_speaker_name():
    shot = {
        "speaker": "林薇",
        "对白": '林薇薇（轻声）: “姐姐醒了？”',
    }
    assert spoken_text_for_shot(shot) == "姐姐醒了？"


def test_inner_monologue_detection():
    assert is_inner_monologue("这一次，我不会再任人摆布。")
    assert is_inner_monologue("【内心独白】不会再任人摆布。")
    assert not is_inner_monologue("三年前·林家大宅")
    assert not is_inner_monologue("她也记得一切。")
    assert monologue_display_text("【内心独白】不会再任人摆布。") == "不会再任人摆布。"
