"""P1：特征锚与分层融合几何。"""

from __future__ import annotations

from tools.drama_characters import character_anchor_prompt
from tools.drama_layers import _bbox_pixels, _occlusion_ordered_slots


def test_character_anchor_prompt_prefers_frozen():
    char = {"name": "玉兔", "look": "很长的外形描写" * 20, "anchor_prompt": "玉兔：兔耳髻短句"}
    assert character_anchor_prompt(char) == "玉兔：兔耳髻短句"
    assert "同一张脸" in character_anchor_prompt({"name": "嫦娥", "look": "白裙飞天髻"})


def test_occlusion_orders_back_then_front():
    plan = {
        "slots": [
            {"character_id": "a", "role": "identity"},
            {"character_id": "b", "role": "support"},
        ],
        "occlusion": [{"front": "a", "back": "b"}],
    }
    ordered = _occlusion_ordered_slots(plan)
    assert [s["character_id"] for s in ordered] == ["b", "a"]


def test_bbox_pixels_clamps():
    x, y, w, h = _bbox_pixels([0.1, 0.2, 0.6, 0.9], 1000, 2000)
    assert x == 100 and y == 400
    assert w == 500 and h == 1400
