"""Phase D: series-level consistency hooks."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_apply_dual_speaker_notes_sets_strategy():
    from tools.drama_series import apply_dual_speaker_notes

    shot = {
        "n": 1,
        "kind": "dialogue",
        "角色": ["林晚", "顾琛"],
        "字幕": "林晚：「你来了。」",
    }
    out = apply_dual_speaker_notes(shot)
    assert out is shot
    assert shot["dual_speaker"]["strategy"] == "lock_lr"
    assert "L/R" in shot["dual_speaker"]["note"]

    # Idempotent — already set is left alone
    shot["dual_speaker"] = {"strategy": "custom", "note": "x"}
    apply_dual_speaker_notes(shot)
    assert shot["dual_speaker"]["strategy"] == "custom"


def test_sfx_basic_for_kind_action():
    from tools.drama_series import sfx_basic_for_kind

    assert sfx_basic_for_kind("action") == "whoosh"
    assert sfx_basic_for_kind("insert") == "click"
    assert sfx_basic_for_kind("dialogue") is None


def test_series_meta_load_save(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from tools import drama_series

    def fake_resolve(rel: str) -> Path:
        p = tmp_path / rel
        return p

    monkeypatch.setattr(drama_series, "resolve_safe", fake_resolve)

    slug = "demo"
    meta = drama_series.load_series_meta(slug)
    assert meta["palette"] == []
    assert meta["version"] == 1
    assert meta["dual_speaker"]["strategy"] == "lock_lr"

    saved = drama_series.save_series_meta(
        slug,
        {"palette": ["#111"], "lighting": "soft", "dual_speaker": meta["dual_speaker"], "version": 1},
    )
    assert saved["palette"] == ["#111"]
    assert saved["lighting"] == "soft"

    loaded = drama_series.load_series_meta(slug)
    assert loaded["palette"] == ["#111"]
    assert loaded["lighting"] == "soft"


def test_embedding_save_load_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from tools import drama_series

    def fake_resolve(rel: str) -> Path:
        return tmp_path / rel

    monkeypatch.setattr(drama_series, "resolve_safe", fake_resolve)

    slug = "demo"
    cid = "hero"
    emb = [0.1, 0.2, 0.3, 0.4]
    drama_series.save_character_embedding(
        slug, cid, emb, method="arcface", ref_rel=f"dramas/{slug}/characters/{cid}.png"
    )
    loaded = drama_series.load_character_embedding(slug, cid)
    assert loaded == emb
    path = drama_series.embedding_path(slug, cid)
    assert path.is_file()
    assert path.parent.name == "embeddings"
