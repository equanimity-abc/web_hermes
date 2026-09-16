"""Cast naming + relationship graph helpers."""

from __future__ import annotations

from tools.drama_cast_graph import parse_relationship_section, preferred_character_name
from tools.drama_characters import match_character_token


def test_preferred_character_name_kinship_paren_nick():
    name, aliases = preferred_character_name("愚公的小孙女（小石）")
    assert name == "小石"
    assert "愚公的小孙女" in aliases
    assert "愚公的小孙女（小石）" in aliases


def test_match_yugong_not_xiaoshi_via_kinship_alias():
    xiaoshi = {
        "id": "cd1f9df28",
        "name": "小石",
        "category": "character",
        "aliases": ["愚公的小孙女", "愚公的小孙女（小石）"],
    }
    only_xiaoshi = [xiaoshi]
    assert match_character_token("愚公", only_xiaoshi) is None

    yugong = {
        "id": "cyugong01",
        "name": "愚公",
        "category": "character",
        "aliases": [],
    }
    both = [xiaoshi, yugong]
    hit = match_character_token("愚公", both)
    assert hit is not None and hit["id"] == "cyugong01"


def test_parse_relationship_section():
    md = """# bible
## 角色关系
- 小石 → 愚公：孙女
- 智叟 -> 愚公: 邻居
## 其它
"""
    edges = parse_relationship_section(md)
    assert len(edges) == 2
    assert edges[0] == {"from": "小石", "to": "愚公", "rel": "孙女"}
    assert edges[1] == {"from": "智叟", "to": "愚公", "rel": "邻居"}
