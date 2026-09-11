"""Parallel upsert must not lose sibling character patches."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from tools.drama_characters import load_characters, save_characters, upsert_character


def test_parallel_upsert_keeps_all_patches(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    root.mkdir()
    monkeypatch.setattr("config.config.WORKSPACE_DIR", str(root))
    slug = "para-cast"
    (root / "dramas" / slug).mkdir(parents=True)
    save_characters(
        slug,
        [
            {"id": "c1", "name": "甲", "look": "a", "category": "character"},
            {"id": "c2", "name": "乙", "look": "b", "category": "character"},
            {"id": "c3", "name": "丙", "look": "c", "category": "character"},
        ],
    )

    def _patch(cid: str, look: str) -> None:
        upsert_character(slug, {"id": cid, "look": look})

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(
            pool.map(
                lambda pair: _patch(*pair),
                [("c1", "look-1"), ("c2", "look-2"), ("c3", "look-3")],
            )
        )

    cards = {c["id"]: c for c in load_characters(slug)}
    assert cards["c1"]["look"] == "look-1"
    assert cards["c2"]["look"] == "look-2"
    assert cards["c3"]["look"] == "look-3"
