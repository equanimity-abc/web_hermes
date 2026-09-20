"""P2：跨镜轨迹与失败层判定。"""

from __future__ import annotations

from tools.drama_layers import _failing_character_ids


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
