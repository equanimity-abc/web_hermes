"""Mixkit BGM fetch unit tests (mocked HTTP)."""

from __future__ import annotations

from pathlib import Path

from tools.drama_mixkit_bgm import install_track


def _patch_ws(monkeypatch, tmp_path: Path):
    from tools import workspace as ws

    def _resolve(rel: str):
        return tmp_path / Path(rel)

    monkeypatch.setattr(ws, "workspace_root", lambda: tmp_path)
    monkeypatch.setattr(ws, "resolve_safe", _resolve)


class _Resp:
    def __init__(self, status_code=200, text="", content=b""):
        self.status_code = status_code
        self.text = text
        self.content = content


def test_search_mixkit_maps_keyword(monkeypatch):
    html = """
    data-audio-player-item-id-value="839"
    <h2 class="item-grid-card__title">
          Tears of Joy
      </h2>
          <p class="item-grid-music-preview__author">
      by Michael Ramir C.
    </p>
    """

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url):
            return _Resp(200, text=html)

    monkeypatch.setattr("tools.drama_mixkit_bgm.httpx.Client", _Client)
    from tools.drama_mixkit_bgm import search_mixkit

    found = search_mixkit("happy", limit=5)
    assert found["ok"] is True
    assert found["results"][0]["id"] == 839
    assert found["results"][0]["title"] == "Tears of Joy"


def test_install_track_clears_procedural(monkeypatch, tmp_path):
    _patch_ws(monkeypatch, tmp_path)
    dest = tmp_path / "shared" / "audio" / "bgm" / "suspense_dark.mp3"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"x" * 100)
    marker = dest.with_suffix(".mp3.procedural")
    marker.write_text("lavfi\n", encoding="utf-8")

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url):
            return _Resp(200, content=b"m" * 12000)

    monkeypatch.setattr("tools.drama_mixkit_bgm.httpx.Client", _Client)
    out = install_track(
        "suspense_dark",
        {
            "id": 140,
            "mood": "dark",
            "download_url": "https://assets.mixkit.co/music/140/140.mp3",
            "page_url": "https://mixkit.co/free-stock-music/mood/dark/",
            "license": "Mixkit Stock Music Free License",
            "license_url": "https://mixkit.co/license/#musicFree",
        },
    )
    assert out["ok"] is True
    assert not marker.is_file()
    assert dest.stat().st_size > 8000
