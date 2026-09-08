"""Freesound BGM fetch unit tests (mocked HTTP)."""

from __future__ import annotations

from pathlib import Path

from tools.drama_freesound_bgm import install_track_from_row, search_freesound


def _patch_ws(monkeypatch, tmp_path: Path):
    from tools import workspace as ws

    def _resolve(rel: str):
        return tmp_path / Path(rel)

    monkeypatch.setattr(ws, "workspace_root", lambda: tmp_path)
    monkeypatch.setattr(ws, "resolve_safe", _resolve)


class _Resp:
    def __init__(self, status_code=200, payload=None, content=b""):
        self.status_code = status_code
        self._payload = payload or {}
        self.content = content
        self.text = str(payload or "")

    def json(self):
        return self._payload


def test_search_freesound_parses_results(monkeypatch):
    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params=None, headers=None):
            return _Resp(
                200,
                {
                    "results": [
                        {
                            "id": 1,
                            "name": "Dark Drone",
                            "duration": 60,
                            "license": "http://creativecommons.org/publicdomain/zero/1.0/",
                            "previews": {"preview-hq-mp3": "https://example.com/a.mp3"},
                            "username": "tester",
                            "url": "https://freesound.org/s/1/",
                            "tags": ["ambient"],
                        }
                    ]
                },
            )

    monkeypatch.setattr("tools.drama_freesound_bgm.httpx.Client", _Client)
    rows = search_freesound("dark", token="tok")
    assert len(rows) == 1
    assert rows[0]["id"] == 1


def test_install_track_clears_procedural_marker(monkeypatch, tmp_path):
    _patch_ws(monkeypatch, tmp_path)
    dest_dir = tmp_path / "shared" / "audio" / "bgm"
    dest_dir.mkdir(parents=True)
    dest = dest_dir / "suspense_dark.mp3"
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

        def get(self, url, headers=None):
            return _Resp(200, content=b"m" * 4000)

    monkeypatch.setattr("tools.drama_freesound_bgm.httpx.Client", _Client)
    row = {
        "id": 99,
        "name": "Suspense Loop",
        "license": "Creative Commons 0",
        "username": "u",
        "url": "https://freesound.org/s/99/",
        "duration": 45,
        "tags": ["dark"],
        "previews": {"preview-hq-mp3": "https://example.com/x.mp3"},
    }
    out = install_track_from_row("suspense_dark", row, token="tok")
    assert out["ok"] is True
    assert not marker.is_file()
    assert dest.is_file() and dest.stat().st_size > 2000
    assert dest.with_suffix(dest.suffix + ".freesound.json").is_file()
