"""MEMORY.md scrub when drama projects are deleted."""

from __future__ import annotations


def test_scrub_memory_terms_drops_matching_lines(tmp_path, monkeypatch):
    from agent import memory_store

    mem = tmp_path / "MEMORY.md"
    mem.write_text(
        "- 用户喜欢简体中文\n"
        "- 工作区内已有项目 rebirth_heiress、demo\n"
        "- 项目 slug=gone-project 已完成 EP01\n"
        "- 当前为 mock 出图 provider\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(memory_store, "memory_path", lambda: mem)

    out = memory_store.scrub_memory_terms("gone-project", "Gone Title")
    assert "gone-project" not in out.lower()
    assert "用户喜欢简体中文" in out
    assert "mock 出图" in out
    assert "rebirth_heiress" in out
    assert mem.read_text(encoding="utf-8") == out


def test_remove_project_calls_memory_scrub(monkeypatch):
    from tools import drama_studio

    calls: list[tuple] = []

    monkeypatch.setattr(drama_studio, "parse_slug", lambda s: s)
    monkeypatch.setattr(
        drama_studio,
        "load_project",
        lambda s: {"slug": s, "title": "大闹天宫"},
    )

    class _Jobs:
        def remove_slug(self, _s):
            return 2

    import tools.drama_queue as dq

    monkeypatch.setattr(dq, "drama_jobs", _Jobs())

    root = object()
    target = object()

    def fake_resolve(rel):
        if rel == "dramas":
            return root
        return target

    monkeypatch.setattr(drama_studio, "resolve_safe", fake_resolve)
    monkeypatch.setattr(drama_studio, "_rel", lambda *parts: "dramas/" + "/".join(parts))

    class _Target:
        parents = [root]

        def exists(self):
            return True

    # Make `root not in target.parents` false and exists true
    target_path = _Target()

    def fake_resolve2(rel):
        if rel == "dramas":
            return root
        return target_path

    monkeypatch.setattr(drama_studio, "resolve_safe", fake_resolve2)
    monkeypatch.setattr(drama_studio.shutil, "rmtree", lambda p: None)

    def fake_scrub(*terms):
        calls.append(terms)
        return ""

    monkeypatch.setattr(
        "agent.memory_store.scrub_memory_terms",
        fake_scrub,
    )

    result = drama_studio.remove_project("havoc-in-heaven")
    assert result["ok"] is True
    assert result["jobs_removed"] == 2
    assert result["memory_scrubbed"] is True
    assert calls == [("havoc-in-heaven", "大闹天宫")]
