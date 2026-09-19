"""Ark face+body pair refs and canvas defaults."""

from __future__ import annotations

from pathlib import Path

from PIL import Image


def test_character_ark_pair_refs_face_then_body(tmp_path, monkeypatch):
    from tools import drama_characters as dc

    slug = "ark-demo"
    root = tmp_path / "dramas" / slug / "characters"
    root.mkdir(parents=True)
    body = root / "hero.png"
    face = root / "hero_face.png"
    Image.new("RGB", (1440, 2560), (10, 20, 30)).save(body)
    Image.new("RGB", (1024, 1024), (200, 100, 50)).save(face)

    def _resolve(rel: str) -> Path:
        rel = str(rel).replace("\\", "/").lstrip("/")
        return tmp_path / rel

    monkeypatch.setattr(dc, "resolve_safe", _resolve)
    char = {
        "id": "hero",
        "ref": f"dramas/{slug}/characters/hero.png",
        "ref_face": f"dramas/{slug}/characters/hero_face.png",
    }
    pair = dc.character_ark_pair_refs(slug, char)
    assert pair == [
        f"dramas/{slug}/characters/hero_face.png",
        f"dramas/{slug}/characters/hero.png",
    ]


def test_character_default_canvas_is_portrait_9_16():
    from tools.drama_characters import BODY_REF_PORTRAIT_KEY, default_ref_size_for, ref_canvas_size

    assert default_ref_size_for("character") == BODY_REF_PORTRAIT_KEY == 1440
    assert ref_canvas_size({"category": "character"}) == (1440, 2560)
