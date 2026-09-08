"""正脸特写锚与结构化 traits。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.drama_characters import (
    enriched_look,
    identity_ref_rel,
    normalize_character,
    ref_face_rel,
    traits_incomplete,
    traits_phrase,
)


def test_traits_phrase_and_enriched_look():
    char = {
        "look": "玄色劲装，披风",
        "hair": "黑色短发",
        "eyes": "锐利黑瞳",
        "outfit": "玄色劲装",
        "marks": "左眉疤",
    }
    phrase = traits_phrase(char)
    assert "发型发色：黑色短发" in phrase
    assert "特征标记：左眉疤" in phrase
    look = enriched_look(char)
    assert "玄色劲装" in look
    assert "黑色短发" in look
    assert traits_incomplete(char) is False
    assert traits_incomplete({"look": "x", "hair": "a"}) is True


def test_identity_ref_prefers_face(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    slug = "test-face-anchor"
    cid = "hero1"
    face_rel = ref_face_rel(slug, cid)
    body_rel = f"dramas/{slug}/characters/{cid}.png"

    root = tmp_path / "ws"
    face_path = root / face_rel
    body_path = root / body_rel
    face_path.parent.mkdir(parents=True, exist_ok=True)
    face_path.write_bytes(b"face" * 100)
    body_path.write_bytes(b"body" * 100)

    monkeypatch.setattr("config.config.WORKSPACE_DIR", str(root))

    char = {
        "id": cid,
        "name": "少年",
        "ref": body_rel,
        "ref_face": face_rel,
    }
    assert identity_ref_rel(slug, char) == face_rel

    face_path.unlink()
    assert identity_ref_rel(slug, char) == body_rel


def test_normalize_keeps_trait_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("config.config.WORKSPACE_DIR", str(tmp_path / "ws"))
    char = normalize_character(
        "demo",
        {
            "id": "c1",
            "name": "嫦娥",
            "look": "广袖宫装",
            "hair": "高髻",
            "eyes": "凤眼",
            "outfit": "月白宫装",
            "marks": "花钿",
        },
    )
    assert char["hair"] == "高髻"
    assert char["eyes"] == "凤眼"
    assert char["outfit"] == "月白宫装"
    assert char["marks"] == "花钿"
    assert char["ref_face"].endswith("c1_face.png")
