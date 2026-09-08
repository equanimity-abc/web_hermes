"""Week2: parallel_map fail_fast=False keeps successful results."""

from __future__ import annotations

from tools.drama_parallel import parallel_map


def test_parallel_map_fail_fast_false_keeps_successes():
    seen: list[int] = []

    def worker(n: int) -> int:
        seen.append(n)
        if n == 2:
            raise ValueError("boom")
        return n * 10

    failed: list[int] = []

    def on_done(_i, item, result):
        if isinstance(result, BaseException):
            failed.append(item)

    out = parallel_map([1, 2, 3], worker, max_workers=2, on_done=on_done, fail_fast=False)
    assert sorted(out) == [10, 30]
    assert failed == [2]
    assert sorted(seen) == [1, 2, 3]
