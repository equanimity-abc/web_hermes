"""P0/P1 contracts: cost ledger, identity KPI, produce gates, karaoke turns, silence notes."""

from __future__ import annotations

from pathlib import Path

from tools.drama_bgm_catalog import match_bgm_by_intent
from tools.drama_dialogue import apply_turn_timings, infer_turn_timings_from_voice
from tools.drama_director import refresh_coverage
from tools.drama_episode_status import build_episode_status
from tools.drama_karaoke import build_karaoke_from_turns
from tools.drama_produce_gates import identity_kpi, produce_blockers


def _patch_ws(monkeypatch, tmp_path: Path):
    from tools import workspace as ws

    def _resolve(rel: str):
        return tmp_path / Path(rel)

    monkeypatch.setattr(ws, "workspace_root", lambda: tmp_path)
    monkeypatch.setattr(ws, "resolve_safe", _resolve)


def test_match_bgm_prefers_non_procedural():
    tracks = [
        {"id": "lavfi_suspense", "mood": "悬疑", "title": "暗涌", "notes": "紧张", "procedural": True},
        {"id": "real_suspense", "mood": "悬疑", "title": "暗涌真曲", "notes": "紧张", "procedural": False},
    ]
    assert match_bgm_by_intent("古风悬疑紧张", tracks) == "real_suspense"


def test_identity_kpi_consecutive():
    doc = {
        "shots": [
            {"n": 1, "identity": {"status": "ok", "pass": True}},
            {"n": 2, "identity": {"status": "ok", "pass": True}},
            {"n": 3, "identity": {"status": "ok", "pass": False}},
            {"n": 4, "identity": {"status": "skipped"}},
            {"n": 5, "identity": {"status": "ok", "pass": True}},
        ]
    }
    kpi = identity_kpi(doc)
    assert kpi["passed"] == 3
    assert kpi["scored"] == 4
    assert kpi["consecutive_pass"] == 2
    assert 3 in kpi["failed"]


def test_produce_blockers_no_script(monkeypatch, tmp_path):
    _patch_ws(monkeypatch, tmp_path)
    (tmp_path / "dramas" / "demo").mkdir(parents=True)
    blockers = produce_blockers("demo", 1, doc={"shots": []}, force=False)
    assert any("剧本" in b or "分镜" in b for b in blockers)
    assert produce_blockers("demo", 1, doc={"shots": [{"n": 1}]}, force=True) == []


def test_infer_turn_timings_prefers_tts_span():
    track = {
        "turns": [
            {"index": 0, "text": "你好", "start": 0.0, "end": 0.8, "voice": "a"},
            {"index": 1, "text": "再见啦朋友", "start": 0.8, "end": 2.0, "voice": "b"},
        ]
    }
    out = infer_turn_timings_from_voice(track, 2.0)
    assert out["turns"][0]["end"] == 0.8
    assert out["turns"][1]["end"] == 2.0


def test_karaoke_from_turns_uses_segment_durations():
    turns = [
        {"text": "你好", "start": 0.0, "end": 0.5},
        {"text": "世界", "start": 0.5, "end": 1.5},
    ]
    rows = build_karaoke_from_turns(turns)
    assert len(rows) == 2
    assert abs(rows[0][1] - rows[0][0] - 0.5) < 1e-6
    assert abs(rows[1][1] - rows[1][0] - 1.0) < 1e-6


def test_silence_suggestion_in_coverage():
    doc = {
        "shots": [
            {
                "n": 1,
                "duration": 8.0,
                "对白": "嗯。",
                "dialogue_track": {"total_duration": 0.4, "turns": []},
            }
        ],
        "coverage": {"suggestions": []},
    }
    cov = refresh_coverage(doc)
    types = {s.get("type") for s in cov.get("suggestions") or []}
    assert "silence" in types or "hook_3s" in types


def test_episode_status_includes_identity_kpi():
    text = build_episode_status(
        "demo",
        1,
        {
            "shots": [
                {"n": 1, "identity": {"status": "ok", "pass": True}, "assets": {"scene": "a"}},
                {"n": 2, "identity": {"status": "ok", "pass": False}, "dirty": ["scene"]},
            ],
            "qc": {"verdict": "待修"},
            "meta": {"配乐": "悬疑"},
        },
    )
    assert "身份 KPI" in text
    assert "脏镜: 2" in text


def test_actual_cost_prefers_max_ledger(monkeypatch, tmp_path):
    _patch_ws(monkeypatch, tmp_path)
    from tools.drama_models import actual_episode_cost, cost_entry
    from tools.drama_observability import append_cost_log
    from tools.drama_shots import save_doc

    (tmp_path / "dramas" / "demo" / "videos" / "ep01").mkdir(parents=True)
    save_doc(
        {
            "slug": "demo",
            "episode": 1,
            "shots": [{"n": 1}],
            "cost_log": [cost_entry(provider="ark", layer="scene", cost=1.5, shot=1)],
        }
    )
    append_cost_log("demo", capability="i2v", provider="ark", cost=3.0, episode=1, shot=1, ok=True)
    # Dual-write may bump shots.json; actual should be at least journal or doc max.
    spent = actual_episode_cost("demo", 1)
    assert spent >= 3.0
