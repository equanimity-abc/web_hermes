"""Background render queue for drama workbench (D7).

Runs heavy ffmpeg / TTS work off the FastAPI event loop. Jobs are process-local
with optional persistence under workspace/dramas/_queue/.
"""

from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from tools.workspace import resolve_safe, workspace_root

TERMINAL = frozenset({"done", "error", "cancelled"})
KINDS = frozenset({"rerender_dirty", "rerender_shot", "export", "render_episode"})


class JobCancelled(Exception):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _queue_dir() -> Path:
    path = workspace_root() / "dramas" / "_queue"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class DramaJob:
    job_id: str
    kind: str
    slug: str
    episode: int
    params: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    progress: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    cancel_event: threading.Event = field(default_factory=threading.Event)

    def touch(self, **patch: Any) -> None:
        for key, value in patch.items():
            setattr(self, key, value)
        self.updated_at = utc_now()

    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def check_cancel(self) -> None:
        if self.cancelled():
            raise JobCancelled("任务已取消")


def public_job(job: DramaJob) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "kind": job.kind,
        "slug": job.slug,
        "episode": job.episode,
        "params": dict(job.params or {}),
        "status": job.status,
        "progress": dict(job.progress or {}),
        "result": job.result,
        "error": job.error,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


class DramaQueue:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, DramaJob] = {}
        self._pending: queue.Queue[str] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._slug_busy: dict[str, str] = {}

    def _persist(self, job: DramaJob) -> None:
        path = _queue_dir() / f"{job.job_id}.json"
        payload = public_job(job)
        payload.pop("cancel_event", None)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def get(self, job_id: str) -> DramaJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(
        self,
        *,
        slug: str | None = None,
        active_only: bool = False,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = list(self._jobs.values())
        if slug:
            rows = [j for j in rows if j.slug == slug]
        if active_only:
            rows = [j for j in rows if j.status in ("pending", "running")]
        rows.sort(key=lambda j: j.created_at, reverse=True)
        return [public_job(j) for j in rows[: max(1, limit)]]

    def submit(
        self,
        kind: str,
        slug: str,
        episode: int,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        kind = str(kind or "").strip()
        if kind not in KINDS:
            raise ValueError(f"未知任务类型：{kind}")
        key = f"{slug}:ep{int(episode):02d}"
        with self._lock:
            busy = self._slug_busy.get(key)
            if busy:
                cur = self._jobs.get(busy)
                if cur and cur.status in ("pending", "running"):
                    raise RuntimeError(f"该项目集已有进行中的任务：{busy}")
                self._slug_busy.pop(key, None)

        job = DramaJob(
            job_id=uuid.uuid4().hex[:12],
            kind=kind,
            slug=slug,
            episode=int(episode),
            params=dict(params or {}),
        )
        with self._lock:
            self._jobs[job.job_id] = job
            self._slug_busy[key] = job.job_id
        self._persist(job)
        self._pending.put(job.job_id)
        self._ensure_worker()
        return public_job(job)

    def cancel(self, job_id: str) -> dict[str, Any]:
        job = self.get(job_id)
        if job is None:
            raise KeyError(job_id)
        job.cancel_event.set()
        if job.status == "pending":
            job.touch(status="cancelled", error=None)
            self._release_busy(job)
            self._persist(job)
        return public_job(job)

    def retry(self, job_id: str) -> dict[str, Any]:
        old = self.get(job_id)
        if old is None:
            raise KeyError(job_id)
        if old.status != "error":
            raise ValueError("只能重试失败的任务")
        return self.submit(old.kind, old.slug, old.episode, params=dict(old.params or {}))

    def _release_busy(self, job: DramaJob) -> None:
        key = f"{job.slug}:ep{int(job.episode):02d}"
        with self._lock:
            if self._slug_busy.get(key) == job.job_id:
                self._slug_busy.pop(key, None)

    def _ensure_worker(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=self._worker_loop, daemon=True, name="drama-queue")
        self._worker.start()

    def _worker_loop(self) -> None:
        while True:
            job_id = self._pending.get()
            job = self.get(job_id)
            if job is None or job.status == "cancelled":
                continue
            if job.cancelled():
                job.touch(status="cancelled")
                self._release_busy(job)
                self._persist(job)
                continue
            job.touch(status="running", progress={"current": 0, "total": 0, "message": "启动中…"})
            self._persist(job)
            try:
                result = self._run_job(job)
                if job.cancelled():
                    job.touch(status="cancelled", result=None, error=None)
                else:
                    job.touch(status="done", result=result, error=None)
            except JobCancelled:
                job.touch(status="cancelled", result=None, error=None)
            except Exception as e:
                if job.cancelled():
                    job.touch(status="cancelled", result=None, error=None)
                else:
                    job.touch(status="error", error=str(e), result=None)
            self._release_busy(job)
            self._persist(job)

    def _progress(self, job: DramaJob, **fields: Any) -> None:
        merged = {**(job.progress or {}), **fields}
        job.touch(progress=merged)
        self._persist(job)

    def _run_job(self, job: DramaJob) -> dict[str, Any]:
        if job.kind == "rerender_dirty":
            return self._run_rerender_dirty(job)
        if job.kind == "render_episode":
            return self._run_render_episode(job)
        if job.kind == "rerender_shot":
            return self._run_rerender_shot(job)
        if job.kind == "export":
            return self._run_export(job)
        raise ValueError(f"未实现的任务：{job.kind}")

    def _run_rerender_dirty(self, job: DramaJob) -> dict[str, Any]:
        from tools.drama_studio import get_episode
        from tools.drama_video import render_episode_video

        ep = get_episode(job.slug, job.episode)
        markdown = ep.get("script")
        if not markdown:
            raise FileNotFoundError("没有分集剧本")

        def on_progress(**fields: Any) -> None:
            self._progress(job, **fields)

        result = render_episode_video(
            job.slug,
            job.episode,
            str(markdown),
            title=str(ep.get("title") or ""),
            cancel_check=job.check_cancel,
            on_progress=on_progress,
        )
        result["impact"] = {
            "rebuilt_shots": result.get("rebuilt_shots") or [],
            "skipped_shots": result.get("skipped_shots") or [],
            "summary": (
                "重渲 Shot "
                + "/".join(str(x) for x in (result.get("rebuilt_shots") or []))
                if result.get("rebuilt_shots")
                else "没有脏镜头需要重渲"
            ),
        }
        return result

    def _run_render_episode(self, job: DramaJob) -> dict[str, Any]:
        from tools.drama_studio import get_episode, load_project, save_project
        from tools.drama_video import render_episode_video

        ep = get_episode(job.slug, job.episode)
        markdown = ep.get("script")
        if not markdown:
            raise FileNotFoundError("没有分集剧本")
        force = bool((job.params or {}).get("force"))

        result = render_episode_video(
            job.slug,
            job.episode,
            str(markdown),
            title=str(ep.get("title") or ""),
            force=force,
            cancel_check=job.check_cancel,
            on_progress=lambda **fields: self._progress(job, **fields),
        )
        project = load_project(job.slug)
        videos = [v for v in (project.get("videos") or []) if int(v.get("n") or 0) != job.episode]
        videos.append(
            {
                "n": job.episode,
                "path": result["path"],
                "play_url": result["play_url"],
                "shots": result["shots"],
                "bytes": result["bytes"],
                "shots_json": result.get("shots_json"),
            }
        )
        videos.sort(key=lambda v: int(v.get("n") or 0))
        project["videos"] = videos
        save_project(job.slug, project)
        return result

    def _run_rerender_shot(self, job: DramaJob) -> dict[str, Any]:
        from tools.drama_video import rerender_shot

        shot_n = int((job.params or {}).get("shot") or 0)
        if shot_n < 1:
            raise ValueError("rerender_shot 需要 shot")
        layers = (job.params or {}).get("layers")
        self._progress(job, message=f"Shot {shot_n}", current=0, total=1, shot=shot_n)
        job.check_cancel()
        result = rerender_shot(
            job.slug,
            job.episode,
            shot_n,
            layers=layers,
        )
        self._progress(job, message=f"Shot {shot_n} 完成", current=1, total=1, shot=shot_n)
        return result

    def _run_export(self, job: DramaJob) -> dict[str, Any]:
        from tools.drama_studio import export_episode

        self._progress(job, message="拼接整集…", current=0, total=1)
        job.check_cancel()
        result = export_episode(job.slug, job.episode)
        self._progress(job, message="导出完成", current=1, total=1)
        return result


drama_jobs = DramaQueue()
