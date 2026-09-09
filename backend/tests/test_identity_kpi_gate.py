"""Episode identity KPI hard gate (studio publish bar)."""

from __future__ import annotations

from tools.drama_produce_gates import (
    dirty_identity_kpi_fails,
    identity_kpi,
    identity_kpi_blocker,
    produce_blockers,
)


def _doc_with_identity(statuses: list[tuple[str, bool | None]]) -> dict:
    """statuses: (status, pass|None). pass ignored when status != ok."""
    shots = []
    for i, (status, ok) in enumerate(statuses, start=1):
        ident: dict = {"status": status}
        if status == "ok":
            ident["pass"] = bool(ok)
        shots.append({"n": i, "identity": ident})
    return {"shots": shots}


def test_identity_kpi_ok_streak():
    # 5 scored, all pass → ok
    doc = _doc_with_identity([("ok", True)] * 5)
    kpi = identity_kpi(doc)
    assert kpi["ok"] is True
    assert kpi["pass_rate"] == 1.0
    assert kpi["consecutive_pass"] == 5
    assert identity_kpi_blocker(doc) == ""


def test_identity_kpi_fail_rate():
    # 5 scored, 3 pass 2 fail → rate 0.6 < 0.8
    doc = _doc_with_identity(
        [("ok", True), ("ok", True), ("ok", False), ("ok", True), ("ok", False)]
    )
    kpi = identity_kpi(doc)
    assert kpi["ok"] is False
    assert kpi["failed"] == [3, 5]
    msg = identity_kpi_blocker(doc)
    assert "身份 KPI" in msg
    assert "3" in msg


def test_identity_kpi_cold_start_no_blocker():
    # only 2 scored → not yet a hard gate
    doc = _doc_with_identity([("ok", False), ("ok", True)])
    assert identity_kpi(doc)["scored"] == 2
    assert identity_kpi_blocker(doc) == ""


def test_dirty_identity_kpi_fails():
    doc = _doc_with_identity(
        [("ok", True), ("ok", False), ("ok", True), ("ok", False), ("ok", True)]
    )
    touched = dirty_identity_kpi_fails(doc)
    assert touched == [2, 4]
    assert "scene" in doc["shots"][1]["dirty"]
    assert "clip" in doc["shots"][3]["dirty"]


def test_produce_blockers_include_kpi(monkeypatch):
    doc = _doc_with_identity(
        [("ok", True), ("ok", False), ("ok", True), ("ok", False), ("ok", True)]
    )
    monkeypatch.setattr("tools.drama_shots.load_doc", lambda *a, **k: doc)
    monkeypatch.setattr(
        "tools.drama_audio.load_mix",
        lambda *a, **k: {"bgm_intent": "悬疑", "tracks": [{"role": "bgm"}]},
    )
    monkeypatch.setattr("tools.drama_audio.has_bgm", lambda mix: True)
    monkeypatch.setattr(
        "tools.drama_studio.load_project_file",
        lambda slug: {"episodes": [{"n": 1, "path": "x.md"}]},
    )
    monkeypatch.setattr("tools.drama_studio._read_text", lambda rel: "剧本")
    blockers = produce_blockers("demo", 1, doc=doc, force=False)
    assert any("身份 KPI" in b for b in blockers)
    assert produce_blockers("demo", 1, doc=doc, force=True) == []
