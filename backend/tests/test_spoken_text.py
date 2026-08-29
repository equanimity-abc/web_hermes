from tools.drama_shots import migrate_shot_script_fields
from tools.drama_video import clean_subtitle, spoken_text, spoken_text_for_shot, subtitle_display_text


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
        "字幕": '林薇薇（夸张地）: “哎呀！对不起姐姐！” 林晚（低头）: “没关系。一件衣服而已。”',
    }
    assert spoken_text_for_shot(shot) == "没关系。一件衣服而已。"


def test_spoken_text_for_shot_fuzzy_speaker_name():
    shot = {
        "speaker": "林薇",
        "字幕": '林薇薇（轻声）: “姐姐醒了？”',
    }
    assert spoken_text_for_shot(shot) == "姐姐醒了？"


def test_subtitle_display_strips_monologue_tag():
    assert subtitle_display_text("【内心独白】不会再任人摆布。") == "不会再任人摆布。"
    assert subtitle_display_text("三年前·林家大宅") == "三年前·林家大宅"


def test_migrate_legacy_dialogue_caption_fields():
    migrated = migrate_shot_script_fields(
        {"对白": "我没死？", "字幕": "三年前·林家大宅", "画面": "x"}
    )
    assert migrated["字幕"] == "我没死？"
    assert migrated["旁白"] == "三年前·林家大宅"
    assert "对白" not in migrated
    # idempotent
    again = migrate_shot_script_fields(migrated)
    assert again["字幕"] == "我没死？"
    assert again["旁白"] == "三年前·林家大宅"
