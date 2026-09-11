"""Queue resume_or_retry must enqueue real work, not hand back stale done jobs."""

from __future__ import annotations

from tools.drama_queue import DramaJob, DramaQueue


def test_resume_or_retry_does_not_reuse_done_job(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.drama_queue._queue_dir", lambda: tmp_path)
    q = DramaQueue(max_workers=1)
    # Don't run worker — we only care about enqueue identity
    monkeypatch.setattr(q, "_ensure_worker", lambda: None)

    old = DramaJob(
        job_id="deadbeefcafe",
        kind="produce_episode",
        slug="resume-demo",
        episode=1,
        params={"smart_resume": True, "force": False},
        idem_key="same",
    )
    old.status = "done"
    old.result = {"ok": True, "play_url": "/x.mp4"}
    q._jobs[old.job_id] = old

    nxt = q.resume_or_retry(
        old.job_id,
        kind="produce_episode",
        slug="resume-demo",
        episode=1,
        params={"smart_resume": True, "force": False},
    )
    assert nxt["job_id"] != old.job_id
    assert nxt["status"] in ("pending", "running")
    assert nxt["slug"] == "resume-demo"
    assert nxt["episode"] == 1


def test_resume_or_retry_attaches_to_active_job(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.drama_queue._queue_dir", lambda: tmp_path)
    q = DramaQueue(max_workers=1)
    monkeypatch.setattr(q, "_ensure_worker", lambda: None)

    active = q.submit("produce_episode", "resume-demo", 1, params={"smart_resume": True})
    assert active["status"] in ("pending", "running")

    nxt = q.resume_or_retry(
        "missing-id",
        kind="produce_episode",
        slug="resume-demo",
        episode=1,
        params={"smart_resume": True},
    )
    assert nxt["job_id"] == active["job_id"]


def test_retry_error_job_creates_new(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.drama_queue._queue_dir", lambda: tmp_path)
    q = DramaQueue(max_workers=1)
    monkeypatch.setattr(q, "_ensure_worker", lambda: None)

    first = q.submit("produce_episode", "resume-demo", 2, params={"force": False})
    job = q.get(first["job_id"])
    assert job is not None
    job.touch(status="error", error="boom")
    q._release_busy(job)

    nxt = q.resume_or_retry(
        first["job_id"],
        kind="produce_episode",
        slug="resume-demo",
        episode=2,
    )
    assert nxt["job_id"] != first["job_id"]
    assert nxt["status"] in ("pending", "running")
