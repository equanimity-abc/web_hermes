"""DialogueTrack: multi-speaker speaker↔voice bindings + timings."""

from tools.drama_dialogue import (
    active_speaker_at,
    apply_turn_timings,
    build_dialogue_track,
    parse_dialogue_segments,
    resolve_speaker_binding,
    spoken_text_from_track,
    track_to_voice_turns,
)


CAST = [
    {"id": "a", "name": "林薇薇", "voice": "zh-CN-XiaoxiaoNeural", "aliases": ["林薇"], "category": "character"},
    {"id": "b", "name": "林晚", "voice": "zh-CN-XiaoyiNeural", "aliases": [], "category": "character"},
]


def test_parse_named_quotes():
    raw = '林薇薇（夸张地）: “哎呀！对不起姐姐！” 林晚（低头）: “没关系。”'
    segs = parse_dialogue_segments(raw)
    assert segs == [("林薇薇", "哎呀！对不起姐姐！"), ("林晚", "没关系。")]


def test_build_multi_binds_character_voices():
    shot = {
        "字幕": '林薇薇（夸张地）: “哎呀！对不起姐姐！” 林晚（低头）: “没关系。”',
        "speaker": "林晚",
    }
    track = build_dialogue_track(shot, CAST)
    assert track["mode"] == "multi"
    assert track["lip_strategy"] == "per_turn"
    assert len(track["turns"]) == 2
    # Canonical card names — never aliases
    assert track["turns"][0]["speaker"] == "林薇薇"
    assert track["turns"][0]["character_name"] == "林薇薇"
    assert track["turns"][0]["voice"] == "zh-CN-XiaoxiaoNeural"
    assert track["turns"][1]["speaker"] == "林晚"
    assert track["turns"][1]["voice"] == "zh-CN-XiaoyiNeural"
    assert track["primary_speaker"] == "林晚"
    assert spoken_text_from_track(track) == "哎呀！对不起姐姐！没关系。"


def test_alias_resolves_to_canonical_name():
    cast = [
        {
            "id": "ruoxi",
            "name": "白若曦",
            "voice": "zh-CN-XiaoxiaoNeural",
            "aliases": ["林晚", "若曦"],
            "category": "character",
        },
        {
            "id": "ruolin",
            "name": "白若琳",
            "voice": "zh-CN-XiaoyiNeural",
            "aliases": ["林薇薇", "若琳"],
            "category": "character",
        },
    ]
    shot = {
        "字幕": '林薇薇: “哎呀！对不起姐姐！” 林晚: “没关系。”',
        "speaker": "ruoxi",
        "角色": ["林晚", "林薇薇"],
    }
    track = build_dialogue_track(shot, cast)
    assert track["mode"] == "multi"
    assert track["turns"][0]["speaker"] == "白若琳"
    assert track["turns"][1]["speaker"] == "白若曦"
    assert track["primary_speaker"] == "白若曦"
    assert all(b["speaker"] in ("白若曦", "白若琳") for b in track["bindings"])


def test_plain_ellipsis_infers_multi_by_scene_order():
    cast = [
        {
            "id": "ruoxi",
            "name": "白若曦",
            "voice": "zh-CN-XiaoxiaoNeural",
            "aliases": ["林晚"],
            "category": "character",
        },
        {
            "id": "ruolin",
            "name": "白若琳",
            "voice": "zh-CN-XiaoyiNeural",
            "aliases": ["林薇薇"],
            "category": "character",
        },
    ]
    shot = {
        "画面": "林薇薇端着牛奶走下楼梯，经过林晚身边时，故意手一滑。",
        "字幕": "哎呀！对不起姐姐，我太不小心了！我这就让人来收拾……没关系。一件衣服而已。",
        "角色": ["林晚", "林薇薇"],
        "speaker": "ruoxi",
    }
    track = build_dialogue_track(shot, cast)
    assert track["mode"] == "multi"
    assert track["lip_strategy"] == "per_turn"
    assert track["turns"][0]["speaker"] == "白若琳"
    assert "对不起姐姐" in track["turns"][0]["text"]
    assert track["turns"][1]["speaker"] == "白若曦"
    assert "一件衣服" in track["turns"][1]["text"]


def test_build_single_uses_shot_speaker_voice():
    shot = {
        "speaker": "林晚",
        "字幕": '林晚（低头）: “没关系。一件衣服而已。”',
    }
    track = build_dialogue_track(shot, CAST)
    assert track["mode"] == "single"
    assert len(track["turns"]) == 1
    assert track["turns"][0]["voice"] == "zh-CN-XiaoyiNeural"
    assert track["turns"][0]["text"] == "没关系。一件衣服而已。"


def test_resolve_alias_speaker():
    bind = resolve_speaker_binding("林薇", CAST)
    assert bind["character_id"] == "a"
    assert bind["voice"] == "zh-CN-XiaoxiaoNeural"


def test_apply_turn_timings_and_active_speaker():
    shot = {
        "字幕": '林薇薇: “第一句。” 林晚: “第二句。”',
    }
    track = build_dialogue_track(shot, CAST)
    timed = [
        {"start": 0.0, "end": 1.2, "voice": "zh-CN-XiaoxiaoNeural"},
        {"start": 1.2, "end": 2.5, "voice": "zh-CN-XiaoyiNeural"},
    ]
    track = apply_turn_timings(track, timed)
    assert track["total_duration"] == 2.5
    assert track["turns"][0]["start"] == 0.0
    assert track["turns"][1]["end"] == 2.5
    assert active_speaker_at(track, 0.5) == "林薇薇"
    assert active_speaker_at(track, 1.5) == "林晚"
    vt = track_to_voice_turns(track)
    assert len(vt) == 2
    assert vt[0]["start"] == 0.0


def test_three_speakers_named_lines_match_cards():
    cast = [
        {
            "id": "ruoxi",
            "name": "白若曦",
            "voice": "zh-CN-XiaoxiaoNeural",
            "aliases": ["林晚"],
            "category": "character",
        },
        {
            "id": "ruolin",
            "name": "白若琳",
            "voice": "zh-CN-XiaoyiNeural",
            "aliases": ["林薇薇"],
            "category": "character",
        },
        {
            "id": "huilan",
            "name": "林慧兰",
            "voice": "zh-CN-YunxiNeural",
            "aliases": ["养母"],
            "category": "character",
        },
    ]
    shot = {
        "字幕": (
            '林慧兰: “给我滚出去！” '
            '林薇薇: “姐姐她偷文件了！” '
            '林晚: “我没有。”'
        ),
        "角色": ["林晚", "林薇薇", "林慧兰"],
        "speaker": "ruoxi",
    }
    track = build_dialogue_track(shot, cast)
    assert track["mode"] == "multi"
    assert track["lip_strategy"] == "per_turn"
    assert len(track["turns"]) == 3
    assert [t["speaker"] for t in track["turns"]] == ["林慧兰", "白若琳", "白若曦"]
    assert [t["voice"] for t in track["turns"]] == [
        "zh-CN-YunxiNeural",
        "zh-CN-XiaoyiNeural",
        "zh-CN-XiaoxiaoNeural",
    ]
    assert track["cast_matched"] >= 3
    ids = {b["character_id"] for b in track["bindings"]}
    assert ids >= {"ruoxi", "ruolin", "huilan"}


def test_bullet_named_lines():
    raw = "- 林慧兰: “滚出去！”\n- 林晚: “妈！”"
    segs = parse_dialogue_segments(raw)
    assert segs == [("林慧兰", "滚出去！"), ("林晚", "妈！")]
