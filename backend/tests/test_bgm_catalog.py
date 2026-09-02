"""BGM catalog merge tests."""

from __future__ import annotations

from tools.drama_audio import load_catalog


def test_load_catalog_includes_shared_tracks():
    cat = load_catalog("_nonexistent_project_slug")
    tracks = cat.get("tracks") or []
    assert len(tracks) >= 6
    ids = {t["id"] for t in tracks}
    assert "suspense_dark" in ids
    assert "revenge_climax" in ids
    for t in tracks:
        assert t.get("preview_url")
        assert str(t.get("license") or "").startswith("catalog:")
