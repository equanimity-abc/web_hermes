"""Thorough project delete / quarantine."""

from __future__ import annotations

import json


def test_force_rmtree_quarantines_locked_tree(tmp_path, monkeypatch):
    from tools import drama_studio as ds
    import time as _time

    root = tmp_path / "dramas"
    proj = root / "locked-proj"
    proj.mkdir(parents=True)
    (proj / "project.json").write_text('{"slug":"locked-proj","title":"锁"}', encoding="utf-8")
    busy = proj / "videos"
    busy.mkdir()
    (busy / "ep01.mp4").write_bytes(b"x" * 100)

    def flaky_rmtree(path, onerror=None):
        raise OSError("file in use")

    monkeypatch.setattr(ds.shutil, "rmtree", flaky_rmtree)
    monkeypatch.setattr(_time, "sleep", lambda *_: None)

    mode = ds._force_rmtree(proj, retries=3)
    assert mode == "quarantined"
    assert not proj.exists()
    trash = list((root / "_trash").iterdir())
    assert trash and trash[0].name.startswith("locked-proj__")
    assert (trash[0] / "project.json").is_file()


def test_remove_project_wipes_real_tree(tmp_path, monkeypatch):
    from tools import drama_studio as ds
    from tools import drama_queue as dq

    root = tmp_path / "dramas"
    slug = "fresh-kill"
    proj = root / slug
    proj.mkdir(parents=True)
    (proj / "project.json").write_text(
        json.dumps({"slug": slug, "title": "可删", "logline": "一段足够长的梗概文字"}),
        encoding="utf-8",
    )
    (proj / "characters").mkdir()
    (proj / "characters" / "a.png").write_bytes(b"png")

    monkeypatch.setattr(ds, "resolve_safe", lambda rel: tmp_path / str(rel).replace("\\", "/"))
    monkeypatch.setattr(ds, "_rel", lambda *p: "dramas/" + "/".join(p) if p else "dramas")
    monkeypatch.setattr(
        ds,
        "load_project_file",
        lambda s: (
            json.loads((root / s / "project.json").read_text(encoding="utf-8"))
            if (root / s / "project.json").is_file()
            else None
        ),
    )
    monkeypatch.setattr(ds, "find_project_slug_by_title", lambda t: None)
    monkeypatch.setattr(ds, "find_project_slug_by_logline", lambda t: None)

    class _Jobs:
        def remove_slug(self, _s, wait_s=2.5):
            return 0

    monkeypatch.setattr(dq, "drama_jobs", _Jobs())
    monkeypatch.setattr("agent.memory_store.scrub_memory_terms", lambda *a: "")

    out = ds.remove_project(slug)
    assert out["ok"]
    assert slug in out["removed"]
    assert not proj.exists()
