"""Phase B: parallel DAG + provider lanes + agent async defaults."""

from __future__ import annotations

import time

from config import config
from tools.drama_parallel import (
    ProgressClock,
    acquire_lane,
    lane_for_provider,
    parallel_map,
    rpm_for_lane,
    shot_concurrency,
)


def test_shot_concurrency_default():
    assert shot_concurrency() == 8
    assert int(getattr(config, "DRAMA_SHOT_CONCURRENCY", 0) or 0) == 8


def test_provider_lanes():
    assert lane_for_provider("seedance") == "ark"
    assert lane_for_provider("seedream") == "ark"
    assert lane_for_provider("pixverse") == "lip"
    assert lane_for_provider("latentsync") == "lip"
    assert rpm_for_lane("ark") == int(getattr(config, "DRAMA_RPM_ARK", 20) or 20)
    assert rpm_for_lane("lip") == int(getattr(config, "DRAMA_RPM_LIP", 10) or 10)
    assert acquire_lane("ark") == "ark"


def test_parallel_map_preserves_order_and_concurrency():
    started: list[float] = []

    def work(n: int) -> int:
        started.append(time.monotonic())
        time.sleep(0.05)
        return n * 2

    out = parallel_map([1, 2, 3, 4], work, max_workers=4)
    assert out == [2, 4, 6, 8]
    # Wall clock should be closer to one sleep than four serial sleeps.
    assert (time.monotonic() - started[0]) < 0.18


def test_parallel_map_fail_fast():
    def work(n: int) -> int:
        if n == 2:
            raise RuntimeError("boom")
        time.sleep(0.02)
        return n

    try:
        parallel_map([1, 2, 3], work, max_workers=3)
        assert False, "expected boom"
    except RuntimeError as exc:
        assert "boom" in str(exc)


def test_progress_clock_waterfall():
    clock = ProgressClock()
    clock.start("cast")
    time.sleep(0.01)
    clock.end("cast")
    snap = clock.snapshot()
    assert snap["elapsed_sec"] >= 0.01
    assert any(m.get("stage") == "cast" and m.get("event") == "end" for m in snap["marks"])
