"""Week3 tests: gen cache + rpm defaults + failure heat."""

from __future__ import annotations

from pathlib import Path

from tools.drama_gen_cache import lookup, store
from tools.drama_observability import bump_failure_heat, load_failure_heat
from tools.drama_parallel import rpm_for_lane


def test_rpm_for_lane_never_unlimited_by_default(monkeypatch):
    monkeypatch.setattr("tools.drama_parallel.config.DRAMA_RPM_ARK", 0, raising=False)
    monkeypatch.setattr("tools.drama_parallel.config.DRAMA_RPM_DEFAULT", 0, raising=False)
    assert rpm_for_lane("ark") > 0


def test_gen_cache_roundtrip(tmp_path, monkeypatch):
    from tools import workspace as ws

    monkeypatch.setattr(ws, "workspace_root", lambda: tmp_path)
    monkeypatch.setattr(
        ws,
        "resolve_safe",
        lambda rel: tmp_path / str(rel).replace("/", "\\") if "\\" in str(tmp_path) else tmp_path / rel,
    )
    # Simpler: patch resolve_safe to join under tmp_path
    def _resolve(rel: str):
        p = tmp_path / Path(rel)
        return p

    monkeypatch.setattr(ws, "resolve_safe", _resolve)
    src = tmp_path / "src.png"
    src.write_bytes(b"x" * 64)
    store("demo", src, kind="image", prompt="hello", seed=1, provider="ark", model="m")
    hit = lookup("demo", kind="image", prompt="hello", seed=1, provider="ark", model="m")
    assert hit is not None
    assert hit.read_bytes() == src.read_bytes()


def test_failure_heat_bumps(tmp_path, monkeypatch):
    from tools import workspace as ws

    def _resolve(rel: str):
        return tmp_path / Path(rel)

    monkeypatch.setattr(ws, "resolve_safe", _resolve)
    bump_failure_heat("demo", 1, layer="shot", provider="ark")
    bump_failure_heat("demo", 1, layer="shot", provider="ark")
    heat = load_failure_heat("demo", 1)
    assert heat["by_layer"]["shot"] == 2
    assert heat["by_provider"]["ark"] == 2
