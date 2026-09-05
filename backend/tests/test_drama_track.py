"""P2：跨镜轨迹与失败层判定。"""

from __future__ import annotations

from tools.drama_layers import _failing_character_ids
from tools.drama_track import load_track, record_shot_identity_pass, previous_passed_face


def test_failing_character_ids_subject_and_support():
    identity = {
        "character_id": "a",
        "threshold": 0.75,
        "matches": [
            {"character_id": "a", "role": "identity", "matched": True, "cosine": 0.4},
            {"character_id": "b", "role": "support", "matched": True, "cosine": 0.9},
            {"character_id": "c", "role": "support", "matched": False, "cosine": None},
        ],
    }
    assert _failing_character_ids(identity) == ["a"]


def test_track_roundtrip(tmp_path, monkeypatch):
    import tools.drama_track as tr

    monkeypatch.setattr(tr, "track_path", lambda slug, ep: tmp_path / "faces.json")
    shot = {"n": 2, "assets": {"scene": "dramas/x/videos/ep01/shot02_scene.png"}}
    identity = {
        "pass": True,
        "matches": [
            {
                "character_id": "cid1",
                "character_name": "嫦娥",
                "matched": True,
                "cosine": 0.88,
                "bbox": [1, 2, 3, 4],
                "face_ratio": 0.1,
            }
        ],
    }
    record_shot_identity_pass("x", 1, shot, identity)
    doc = load_track("x", 1)
    assert "cid1" in doc["characters"]
    assert doc["characters"]["cid1"]["last"]["shot"] == 2
    prev = previous_passed_face("x", 1, "cid1", before_shot=3)
    assert prev and prev["cosine"] == 0.88
    assert previous_passed_face("x", 1, "cid1", before_shot=2) is None
