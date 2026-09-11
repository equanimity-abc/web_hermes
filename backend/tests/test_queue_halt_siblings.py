"""Queue: one job failure cancels pending siblings for the same slug."""

from __future__ import annotations

import threading
import time

from tools.drama_queue import DramaQueue


def test_stop_siblings_after_failure_cancels_pending(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.drama_queue._queue_dir", lambda: tmp_path)
    q = DramaQueue(max_workers=1)

    started = threading.Event()
    release = threading.Event()

    def _run_job(job):
        if job.kind == "produce_episode" and job.episode == 1:
            started.set()
            # Hold until test signals, then fail.
            release.wait(timeout=5)
            raise RuntimeError("ep1 boom")
        job.check_cancel()
        time.sleep(0.01)
        return {"ok": True, "episode": job.episode}

    monkeypatch.setattr(q, "_run_job", _run_job)

    j1 = q.submit("produce_episode", "halt-demo", 1)
    j2 = q.submit("produce_episode", "halt-demo", 2)
    assert j1["status"] == "pending" or j1["status"] == "running"
    assert j2["status"] == "pending"

    assert started.wait(timeout=3)
    release.set()

    # Wait for ep1 to error and sibling halt.
    deadline = time.time() + 5
    while time.time() < deadline:
        a = q.get(j1["job_id"])
        b = q.get(j2["job_id"])
        if a and a.status == "error" and b and b.status == "cancelled":
            break
        time.sleep(0.05)
    else:
        a = q.get(j1["job_id"])
        b = q.get(j2["job_id"])
        raise AssertionError(f"expected error+cancelled, got {a and a.status}, {b and b.status}")

    assert "boom" in (a.error or "")
    assert "不再开启" in (b.error or "") or b.cancelled()
