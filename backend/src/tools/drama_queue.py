"""Background render queue for drama workbench (D7).

Runs heavy ffmpeg / TTS work off the FastAPI event loop. Jobs are process-local
with optional persistence under workspace/dramas/_queue/.
"""

from __future__ import annotations

import json
import queue
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from tools.workspace import resolve_safe, workspace_root

TERMINAL = frozenset({"done", "error", "cancelled"})
KINDS = frozenset({"rerender_dirty", "rerender_shot", "export", "render_episode", "produce_episode", "i2v_shot", "lip_shot", "keys_shot"})
# 镜头级任务可同集并行；整集级任务独占。
SHOT_KINDS = frozenset({"i2v_shot", "lip_shot", "keys_shot", "rerender_shot"})
EXCLUSIVE_KINDS = frozenset({"rerender_dirty", "export", "render_episode", "produce_episode"})


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
        # slug:ep -> set of active job_ids (pending/running)
        self._slug_busy: dict[str, set[str]] = {}
        # S4: worker 池。整集任务互斥；镜头级任务按 DRAMA_SHOT_CONCURRENCY 并行。
        try:
            from config import config

            default_workers = int(getattr(config, "DRAMA_MAX_WORKERS", 4) or 4)
            shot_conc = int(getattr(config, "DRAMA_SHOT_CONCURRENCY", 3) or 3)
        except Exception:
            default_workers = 4
            shot_conc = 3
        self.max_workers = max(1, int(max_workers or default_workers))
        self.shot_concurrency = max(1, shot_conc)
        # 启动时从磁盘回载失败/中断任务，历史会话可「继续渲染」而无需再踩一次失败
        self._restore_from_disk()

    def _persist(self, job: DramaJob) -> None:
        if job.discarded:
            return
        path = _queue_dir() / f"{job.job_id}.json"
        payload = public_job(job)
        payload.pop("cancel_event", None)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _job_from_payload(self, data: dict[str, Any]) -> DramaJob | None:
        jid = str(data.get("job_id") or "").strip()
        kind = str(data.get("kind") or "").strip()
        slug = str(data.get("slug") or "").strip()
        if not jid or kind not in KINDS or not slug:
            return None
        try:
            episode = int(data.get("episode") or 0)
        except (TypeError, ValueError):
            return None
        if episode < 1:
            return None
        status = str(data.get("status") or "pending").strip() or "pending"
        error = data.get("error")
        # 进程重启后：内存里的 running/pending 实际已中断，标成 error 以便 retry
        if status in ("pending", "running"):
            status = "error"
            error = str(error or "服务重启，任务中断；可继续渲染").strip()
        params = data.get("params") if isinstance(data.get("params"), dict) else {}
        progress = dict(data.get("progress") or {}) if isinstance(data.get("progress"), dict) else {}
        if status == "error" and "服务重启" in str(error or ""):
            progress["resumable"] = True
            progress["message"] = progress.get("message") or str(error)
        return DramaJob(
            job_id=jid,
            kind=kind,
            slug=slug,
            episode=episode,
            params=dict(params),
            idem_key=str(data.get("idem_key") or ""),
            status=status,
            progress=progress,
            result=data.get("result") if isinstance(data.get("result"), dict) else None,
            error=str(error) if error else None,
            created_at=str(data.get("created_at") or utc_now()),
            updated_at=str(data.get("updated_at") or utc_now()),
        )

    def _hydrate_locked(self, job_id: str) -> DramaJob | None:
        """Caller must hold self._lock. Load one job json into memory if missing."""
        jid = str(job_id or "").strip()
        if not jid:
            return None
        hit = self._jobs.get(jid)
        if hit is not None:
            return hit
        path = _queue_dir() / f"{jid}.json"
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        job = self._job_from_payload(data)
        if job is None:
            return None
        self._jobs[job.job_id] = job
        # 写回中断标记，避免下次启动仍显示 running
        if job.status == "error" and str(data.get("status") or "") in ("pending", "running"):
            try:
                self._persist(job)
            except OSError:
                pass
        return job

    def _restore_from_disk(self) -> None:
        try:
            root = _queue_dir()
        except Exception:
            return
        for path in root.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            with self._lock:
                if data.get("job_id") in self._jobs:
                    continue
                job = self._job_from_payload(data)
                if job is None:
                    continue
                self._jobs[job.job_id] = job
                if job.status == "error" and str(data.get("status") or "") in ("pending", "running"):
                    try:
                        self._persist(job)
                    except OSError:
                        pass
        import os

        if os.getenv("DRAMA_AUTO_RESUME", "").strip().lower() in ("1", "true", "yes"):
            try:
                self.resume_interrupted(limit=10)
            except Exception:
                pass

    def get(self, job_id: str) -> DramaJob | None:
        with self._lock:
            hit = self._jobs.get(job_id)
            if hit is not None:
                return hit
            return self._hydrate_locked(job_id)

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
            active = self._active_jobs(key)
            for cur in active:
                if cur.idem_key == idem:
                    return public_job(cur)

            has_exclusive = any(j.kind in EXCLUSIVE_KINDS for j in active)
            shot_count = sum(1 for j in active if j.kind in SHOT_KINDS)

            if kind in EXCLUSIVE_KINDS:
                if active:
                    raise RuntimeError(f"该项目集已有进行中的任务：{active[0].job_id}")
            else:
                if has_exclusive:
                    excl = next(j for j in active if j.kind in EXCLUSIVE_KINDS)
                    raise RuntimeError(f"该项目集已有进行中的任务：{excl.job_id}")
                if shot_count >= self.shot_concurrency:
                    raise RuntimeError(
                        f"该集镜头任务并发已满（{self.shot_concurrency}），请稍后再试"
                    )

            # S5: dedupe against a recent identical terminal job too.
            # Explicit smart_resume / continue-render must not reuse a stale "done"
            # job — otherwise the UI ends immediately while nothing new runs.
            reuse_done = not bool((params or {}).get("smart_resume"))
            if reuse_done:
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
            self._jobs[job.job_id] = job
            self._slug_busy.setdefault(key, set()).add(job.job_id)

        self._persist(job)
        self._pending.put(job.job_id)
        self._ensure_worker()
        return public_job(job)

    def _active_jobs(self, key: str) -> list[DramaJob]:
        ids = list(self._slug_busy.get(key) or ())
        out: list[DramaJob] = []
        stale: list[str] = []
        for jid in ids:
            cur = self._jobs.get(jid)
            if cur and cur.status in ("pending", "running"):
                out.append(cur)
            else:
                stale.append(jid)
        if stale:
            bucket = self._slug_busy.get(key)
            if bucket is not None:
                for jid in stale:
                    bucket.discard(jid)
                if not bucket:
                    self._slug_busy.pop(key, None)
        return out

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

    def retry(self, job_id: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        old = self.get(job_id)
        if old is None:
            raise KeyError(job_id)
        if old.status not in ("error", "cancelled"):
            raise ValueError("只能重试失败或已取消的任务")
        merged = dict(old.params or {})
        if params:
            merged.update(params)
        # 失败/取消后续跑：默认智能从失败点继续（跳过已通过步骤）
        merged.setdefault("smart_resume", True)
        merged.setdefault("force", False)
        return self.submit(old.kind, old.slug, old.episode, params=merged)

    def resume_or_retry(
        self,
        job_id: str = "",
        *,
        kind: str = "",
        slug: str = "",
        episode: int = 0,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """历史会话续跑：优先按 job_id 重试；磁盘/内存都没有时按 slug+episode+kind 新建。

        用户点「继续渲染」必须真正入队新任务（或挂上仍在跑的同一集任务），
        不得把已 done 的旧 job 直接交回前端导致秒结束。
        """
        import time

        merged = dict(params or {})
        merged.setdefault("smart_resume", True)
        if "force" not in merged:
            merged["force"] = False
        # 打破与历史 done 任务的 idem 碰撞；仍可与「进行中」任务去重
        merged["resume_token"] = str(merged.get("resume_token") or f"{time.time_ns()}")
        jid = str(job_id or "").strip()
        if jid:
            try:
                return self.retry(jid, params=merged)
            except KeyError:
                pass
            except ValueError:
                cur = self.get(jid)
                if cur and cur.status in ("pending", "running"):
                    return public_job(cur)
                # done / 其它终态：落到下方按 slug+episode 新建
        kind = str(kind or "").strip() or "produce_episode"
        slug = str(slug or "").strip()
        if not slug:
            raise KeyError(jid or "missing_job")
        try:
            ep = int(episode or 0)
        except (TypeError, ValueError):
            ep = 0
        if ep < 1:
            raise ValueError("续跑需要合法 episode")
        # 同集已有进行中的排他任务：直接返回，让前端继续 poll，不要报错秒退
        key = f"{slug}:ep{ep:02d}"
        with self._lock:
            active = self._active_jobs(key)
            for cur in active:
                if cur.kind in EXCLUSIVE_KINDS or cur.kind == kind:
                    return public_job(cur)
        return self.submit(kind, slug, ep, params=merged)

    def resume_interrupted(self, *, slug: str = "", limit: int = 20) -> list[dict[str, Any]]:
        """Re-queue jobs marked resumable after process restart."""
        import os

        auto = os.getenv("DRAMA_AUTO_RESUME", "").strip().lower() in ("1", "true", "yes")
        # Method always works when called explicitly; auto only if env set.
        _ = auto
        rows = self.list_jobs(slug=slug or None, active_only=False, limit=max(1, int(limit)))
        out: list[dict[str, Any]] = []
        for row in rows:
            if row.get("status") != "error":
                continue
            prog = row.get("progress") if isinstance(row.get("progress"), dict) else {}
            err = str(row.get("error") or "")
            if not (prog.get("resumable") or "服务重启" in err):
                continue
            try:
                out.append(self.retry(str(row.get("job_id") or "")))
            except Exception:
                continue
        return out

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
            bucket = self._slug_busy.get(key)
            if not bucket:
                return
            bucket.discard(job.job_id)
            if not bucket:
                self._slug_busy.pop(key, None)

    def _stop_siblings_after_failure(self, failed: DramaJob) -> None:
        """同项目其他任务：pending 直接取消；running 打取消标记，跑完当前步骤后停。"""
        slug = str(failed.slug or "")
        if not slug:
            return
        with self._lock:
            siblings = [
                j
                for j in self._jobs.values()
                if j.slug == slug
                and j.job_id != failed.job_id
                and j.status in ("pending", "running")
            ]
        for sib in siblings:
            sib.cancel_event.set()
            if sib.status == "pending":
                sib.touch(
                    status="cancelled",
                    error=f"因任务 {failed.job_id} 失败，不再开启新任务",
                )
                self._release_busy(sib)
                self._persist(sib)
            else:
                # running：保留 running，worker 在 check_cancel 处结束并标 cancelled
                prog = dict(sib.progress or {})
                prog["message"] = prog.get("message") or f"因任务 {failed.job_id} 失败，完成当前步骤后停止"
                sib.touch(progress=prog)
                self._persist(sib)

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
                    err = str(e)
                    prog = job.progress or {}
                    if prog.get("shot") and f"Shot {prog['shot']}" not in err and f"第{prog['shot']}镜" not in err:
                        # 整集汇总失败不要再挂「第X镜：」，避免误读成单镜根因
                        if not re.search(r"HQ 有\s*\d+\s*镜失败", err):
                            err = f"第{prog['shot']}镜：{err}"
                    job.touch(status="error", error=err, result=None)
                    self._progress(job, message=err)
                    # 一任务失败：同项目待跑的不再开启；已在跑的收到取消信号，完成当前步骤后停
                    self._stop_siblings_after_failure(job)
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
        if job.kind == "produce_episode":
            return self._run_produce_episode(job)
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
        force = bool((job.params or {}).get("force"))
        result = export_episode(job.slug, job.episode, background=False, force=force)
        self._progress(job, message="导出完成", current=1, total=1)
        return result

    def _run_produce_episode(self, job: DramaJob) -> dict[str, Any]:
        from tools.drama_produce import produce_episode_hq
        from tools.drama_studio import load_project, save_project

        params = job.params or {}
        force = bool(params.get("force"))
        style_id = str(params.get("style_id") or "")
        catalog_bgm = str(params.get("catalog_bgm") or "rebirth_resolve")

        def on_progress(**fields: Any) -> None:
            self._progress(job, **fields)

        result = produce_episode_hq(
            job.slug,
            job.episode,
            force=force,
            style_id=style_id,
            catalog_bgm=catalog_bgm,
            cancel_check=job.check_cancel,
            on_progress=on_progress,
        )
        project = load_project(job.slug)
        if project:
            videos = [v for v in (project.get("videos") or []) if int(v.get("n") or 0) != job.episode]
            videos.append(
                {
                    "n": job.episode,
                    "path": result.get("path") or result.get("video_path"),
                    "play_url": result.get("play_url"),
                    "shots": result.get("count") or result.get("shots"),
                    "bytes": result.get("bytes") or 0,
                    "shots_json": result.get("shots_json"),
                }
            )
            videos.sort(key=lambda v: int(v.get("n") or 0))
            project["videos"] = videos
            save_project(job.slug, project)
        self._progress(job, message="HQ 成片完成", stage="done")
        return result

    def _run_i2v_shot(self, job: DramaJob) -> dict[str, Any]:
        from tools.drama_i2v import generate_shot_i2v
        from tools.drama_shots import find_shot, load_doc, merge_save_shot
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
        info = generate_shot_i2v(job.slug, job.episode, shot, force=True, allow_locked=True)
        merge_save_shot(job.slug, job.episode, shot)
        job.check_cancel()
        self._progress(job, message=f"合成 Shot {shot_n}", current=1, total=2, shot=shot_n)
        result = rerender_shot(job.slug, job.episode, shot_n, layers=["clip"])
        info["assemble"] = result.get("assemble")
        return info

    def _run_lip_shot(self, job: DramaJob) -> dict[str, Any]:
        from tools.drama_lip import generate_shot_lip
        from tools.drama_shots import find_shot, load_doc, merge_save_shot
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
        merge_save_shot(job.slug, job.episode, shot)
        job.check_cancel()
        self._progress(job, message=f"合成 Shot {shot_n}", current=1, total=2, shot=shot_n)
        result = rerender_shot(job.slug, job.episode, shot_n, layers=["clip"])
        info["assemble"] = result.get("assemble")
        return info

    def _run_keys_shot(self, job: DramaJob) -> dict[str, Any]:
        from tools.drama_i2v import generate_shot_i2v
        from tools.drama_keys import generate_shot_keys
        from tools.drama_shots import find_shot, load_doc, merge_save_shot
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
        merge_save_shot(job.slug, job.episode, shot)
        job.check_cancel()
        self._progress(job, message=f"补间 Shot {shot_n}", current=1, total=3, shot=shot_n)
        motion = generate_shot_i2v(job.slug, job.episode, shot, force=True, allow_locked=True)
        merge_save_shot(job.slug, job.episode, shot)
        job.check_cancel()
        self._progress(job, message=f"合成 Shot {shot_n}", current=2, total=3, shot=shot_n)
        result = rerender_shot(job.slug, job.episode, shot_n, layers=["clip"])
        info["i2v_source"] = motion.get("i2v_source")
        info["ladder"] = motion.get("ladder") or "L4"
        info["assemble"] = result.get("assemble")
        info["voice_rebuilt"] = False
        return info


drama_jobs = DramaQueue()
