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
KINDS = frozenset({"rerender_dirty", "rerender_shot", "export", "render_episode", "i2v_shot", "lip_shot", "keys_shot"})


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
    idem_key: str = ""
    status: str = "pending"
    progress: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    discarded: bool = False

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
    def __init__(self, *, max_workers: int | None = None) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, DramaJob] = {}
        self._pending: queue.Queue[str] = queue.Queue()
        self._workers: list[threading.Thread] = []
        self._slug_busy: dict[str, str] = {}
        # S4: worker 池。同 slug:episode 由 _slug_busy 互斥，跨集/跨项目并行出图。
        try:
            from config import config

            default_workers = int(getattr(config, "DRAMA_MAX_WORKERS", 2) or 2)
        except Exception:
            default_workers = 2
        self.max_workers = max(1, int(max_workers or default_workers))

    def _persist(self, job: DramaJob) -> None:
        if job.discarded:
            return
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

    def _idem_key(self, kind: str, slug: str, episode: int, params: dict[str, Any] | None) -> str:
        """S5: stable key for exactly-once submit dedupe."""
        from hashlib import sha256

        raw = json.dumps(
            {"kind": kind, "slug": slug, "episode": int(episode), "params": params or {}},
            ensure_ascii=False,
            sort_keys=True,
        )
        return sha256(raw.encode("utf-8")).hexdigest()

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
        idem = self._idem_key(kind, slug, int(episode), params)
        key = f"{slug}:ep{int(episode):02d}"
        with self._lock:
            busy = self._slug_busy.get(key)
            if busy:
                cur = self._jobs.get(busy)
                if cur and cur.status in ("pending", "running"):
                    # S5: same idempotent request reuses the in-flight job.
                    if cur.idem_key == idem:
                        return public_job(cur)
                    raise RuntimeError(f"该项目集已有进行中的任务：{busy}")
                self._slug_busy.pop(key, None)
            # S5: dedupe against a recent identical terminal job too.
            for job in self._jobs.values():
                if job.idem_key == idem and job.status == "done":
                    return public_job(job)

        job = DramaJob(
            job_id=uuid.uuid4().hex[:12],
            kind=kind,
            slug=slug,
            episode=int(episode),
            params=dict(params or {}),
            idem_key=idem,
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

    def remove_slug(self, slug: str) -> int:
        """Cancel and drop in-memory jobs for a slug and remove persisted records.

        Running workers keep a reference to their job; marking it discarded makes
        the worker skip the trailing _persist, so no orphan file is re-created.
        """
        with self._lock:
            jobs = [j for j in self._jobs.values() if j.slug == slug]
            for j in jobs:
                self._jobs.pop(j.job_id, None)
        removed = len(jobs)
        for j in jobs:
            j.cancel_event.set()
            j.discarded = True
            if j.status == "pending":
                j.touch(status="cancelled", error=None)
            self._release_busy(j)
        for path in _queue_dir().glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("slug") == slug:
                try:
                    path.unlink()
                except OSError:
                    pass
        return removed

    def _release_busy(self, job: DramaJob) -> None:
        key = f"{job.slug}:ep{int(job.episode):02d}"
        with self._lock:
            if self._slug_busy.get(key) == job.job_id:
                self._slug_busy.pop(key, None)

    def _ensure_worker(self) -> None:
        self._workers = [w for w in self._workers if w.is_alive()]
        need = self.max_workers - len(self._workers)
        for i in range(need):
            t = threading.Thread(
                target=self._worker_loop,
                daemon=True,
                name=f"drama-queue-{i}",
            )
            self._workers.append(t)
            t.start()

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
        if job.kind == "i2v_shot":
            return self._run_i2v_shot(job)
        if job.kind == "lip_shot":
            return self._run_lip_shot(job)
        if job.kind == "keys_shot":
            return self._run_keys_shot(job)
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
        result = export_episode(job.slug, job.episode, background=False)
        self._progress(job, message="导出完成", current=1, total=1)
        return result

    def _run_i2v_shot(self, job: DramaJob) -> dict[str, Any]:
        from tools.drama_i2v import generate_shot_i2v
        from tools.drama_shots import find_shot, load_doc, save_doc
        from tools.drama_video import rerender_shot

        shot_n = int((job.params or {}).get("shot") or 0)
        if shot_n < 1:
            raise ValueError("i2v_shot 需要 shot")
        doc = load_doc(job.slug, job.episode)
        if doc is None:
            raise FileNotFoundError("没有 shots.json")
        shot = find_shot(doc, shot_n)
        if shot is None:
            raise ValueError(f"找不到 Shot {shot_n}")
        self._progress(job, message=f"I2V Shot {shot_n}", current=0, total=2, shot=shot_n)
        job.check_cancel()
        info = generate_shot_i2v(job.slug, job.episode, shot, force=True)
        save_doc(doc)
        job.check_cancel()
        self._progress(job, message=f"合成 Shot {shot_n}", current=1, total=2, shot=shot_n)
        result = rerender_shot(job.slug, job.episode, shot_n, layers=["clip"])
        info["assemble"] = result.get("assemble")
        return info

    def _run_lip_shot(self, job: DramaJob) -> dict[str, Any]:
        from tools.drama_lip import generate_shot_lip
        from tools.drama_shots import find_shot, load_doc, save_doc
        from tools.drama_video import rerender_shot

        shot_n = int((job.params or {}).get("shot") or 0)
        if shot_n < 1:
            raise ValueError("lip_shot 需要 shot")
        doc = load_doc(job.slug, job.episode)
        if doc is None:
            raise FileNotFoundError("没有 shots.json")
        shot = find_shot(doc, shot_n)
        if shot is None:
            raise ValueError(f"找不到 Shot {shot_n}")
        self._progress(job, message=f"口型 Shot {shot_n}", current=0, total=2, shot=shot_n)
        job.check_cancel()
        info = generate_shot_lip(job.slug, job.episode, shot)
        save_doc(doc)
        job.check_cancel()
        self._progress(job, message=f"合成 Shot {shot_n}", current=1, total=2, shot=shot_n)
        result = rerender_shot(job.slug, job.episode, shot_n, layers=["clip"])
        info["assemble"] = result.get("assemble")
        return info

    def _run_keys_shot(self, job: DramaJob) -> dict[str, Any]:
        from tools.drama_i2v import generate_shot_i2v
        from tools.drama_keys import generate_shot_keys
        from tools.drama_shots import find_shot, load_doc, save_doc
        from tools.drama_video import rerender_shot

        shot_n = int((job.params or {}).get("shot") or 0)
        count = (job.params or {}).get("count")
        if shot_n < 1:
            raise ValueError("keys_shot 需要 shot")
        doc = load_doc(job.slug, job.episode)
        if doc is None:
            raise FileNotFoundError("没有 shots.json")
        shot = find_shot(doc, shot_n)
        if shot is None:
            raise ValueError(f"找不到 Shot {shot_n}")
        self._progress(job, message=f"关键帧 Shot {shot_n}", current=0, total=3, shot=shot_n)
        job.check_cancel()
        info = generate_shot_keys(job.slug, job.episode, shot, count=count)
        save_doc(doc)
        job.check_cancel()
        self._progress(job, message=f"补间 Shot {shot_n}", current=1, total=3, shot=shot_n)
        motion = generate_shot_i2v(job.slug, job.episode, shot, force=True)
        save_doc(doc)
        job.check_cancel()
        self._progress(job, message=f"合成 Shot {shot_n}", current=2, total=3, shot=shot_n)
        result = rerender_shot(job.slug, job.episode, shot_n, layers=["clip"])
        info["i2v_source"] = motion.get("i2v_source")
        info["ladder"] = motion.get("ladder") or "L4"
        info["assemble"] = result.get("assemble")
        info["voice_rebuilt"] = False
        return info


drama_jobs = DramaQueue()
