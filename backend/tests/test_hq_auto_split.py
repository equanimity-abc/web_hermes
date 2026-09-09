"""HQ auto_split: multi-speaker shots → single-speaker beats."""

from __future__ import annotations

from tools.drama_dialogue import (
    group_turns_by_speaker_runs,
    normalize_hq_auto_split_doc,
    split_shot_auto,
    track_distinct_speakers,
)


def test_group_speaker_runs_collapses_consecutive():
    turns = [
        {"character_id": "a", "character_name": "甲", "speaker": "甲", "text": "你好"},
        {"character_id": "a", "character_name": "甲", "speaker": "甲", "text": "在吗"},
        {"character_id": "b", "character_name": "乙", "speaker": "乙", "text": "在"},
        {"character_id": "a", "character_name": "甲", "speaker": "甲", "text": "好"},
    ]
    runs = group_turns_by_speaker_runs(turns)
    assert len(runs) == 3
    assert len(runs[0]) == 2
    assert runs[1][0]["character_id"] == "b"


def test_split_shot_auto_makes_singles():
    parent = {
        "n": 2,
        "duration": 6.0,
        "画面": "两人对话",
        "字幕": "甲：「你好」乙：「嗨」",
        "角色": ["甲", "乙"],
        "kind": "dialogue",
        "dialogue_track": {
            "mode": "multi",
            "lip_strategy": "per_turn",
            "turns": [
                {
                    "index": 0,
                    "speaker": "甲",
                    "character_id": "c1",
                    "character_name": "甲",
                    "text": "你好",
                    "voice": "v1",
                },
                {
                    "index": 1,
                    "speaker": "乙",
                    "character_id": "c2",
                    "character_name": "乙",
                    "text": "嗨",
                    "voice": "v2",
                },
            ],
        },
        "assets": {"scene": "x.png", "voice": "y.mp3"},
    }
    children = split_shot_auto(parent, slug="demo", cast=[])
    assert len(children) == 2
    assert children[0]["speaker"] == "甲"
    assert children[1]["speaker"] == "乙"
    assert children[0]["dialogue_track"]["mode"] == "single"
    assert len(track_distinct_speakers(children[0]["dialogue_track"])) == 1
    assert children[0]["hq_dialogue_policy"] == "auto_split"
    assert children[0]["hq_split_from"] == 2
    assert children[0].get("assets") == {}
    assert "你好" in children[0]["字幕"]
    assert "嗨" in children[1]["字幕"]


def test_normalize_hq_auto_split_doc_renumbers(monkeypatch):
    doc = {
        "shots": [
            {
                "n": 1,
                "duration": 3,
                "字幕": "旁白",
                "kind": "establishing",
                "dialogue_track": {"mode": "single", "turns": []},
            },
            {
                "n": 2,
                "duration": 6,
                "字幕": "甲：「a」乙：「b」",
                "角色": ["甲", "乙"],
                "kind": "dialogue",
                "dialogue_track": {
                    "mode": "multi",
                    "turns": [
                        {
                            "speaker": "甲",
                            "character_id": "c1",
                            "character_name": "甲",
                            "text": "a",
                        },
                        {
                            "speaker": "乙",
                            "character_id": "c2",
                            "character_name": "乙",
                            "text": "b",
                        },
                    ],
                },
            },
        ],
        "timeline": {"order": [1, 2], "fade_sec": 0.2},
    }
    monkeypatch.setattr("tools.drama_characters.load_characters", lambda slug: [])
    out = normalize_hq_auto_split_doc("demo", 1, doc)
    assert out["changed"] is True
    assert out["split_parents"] == 1
    assert out["child_shots"] == 2
    shots = out["doc"]["shots"]
    assert [s["n"] for s in shots] == [1, 2, 3]
    assert shots[1]["hq_split_from"] == 2
    assert shots[2]["hq_split_from"] == 2
    # idempotent on children
    out2 = normalize_hq_auto_split_doc("demo", 1, out["doc"])
    assert out2["changed"] is False
    assert len(out2["doc"]["shots"]) == 3
