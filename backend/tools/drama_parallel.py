"""Phase B: shot-parallel DAG helpers + provider token-bucket lanes."""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Any, Callable, TypeVar

from config import config
from tools.drama_retry import rate_limiter_for

T = TypeVar("T")
R = TypeVar("R")

# Logical lanes shared by related commercial providers.
LANE_ARK = "ark"
LANE_DASHSCOPE = "dashscope"
LANE_LIP = "lip"
LANE_DEFAULT = "default"

_PROVIDER_LANE: dict[str, str] = {
    "ark": LANE_ARK,
    "seedream": LANE_ARK,
    "seedance": LANE_ARK,
    "seed-audio": LANE_ARK,
    "doubao": LANE_ARK,
    "dashscope": LANE_DASHSCOPE,
    "qwen": LANE_DASHSCOPE,
    "wanx": LANE_DASHSCOPE,
    "pixverse": LANE_LIP,
    "pixverse-lipsync": LANE_LIP,
    "latentsync": LANE_LIP,
    "musetalk": LANE_LIP,
    "wav2lip": LANE_LIP,
}


def shot_concurrency() -> int:
    return max(1, int(getattr(config, "DRAMA_SHOT_CONCURRENCY", 8) or 8))


def lane_for_provider(provider_id: str) -> str:
    pid = str(provider_id or "").strip().lower()
    if not pid:
        return LANE_DEFAULT
    if pid in _PROVIDER_LANE:
        return _PROVIDER_LANE[pid]
    if pid.startswith("seed") or "ark" in pid or "doubao" in pid:
        return LANE_ARK
    if "dash" in pid or "qwen" in pid:
        return LANE_DASHSCOPE
    if any(x in pid for x in ("lip", "pixverse", "latent", "muse", "wav2")):
        return LANE_LIP
    return LANE_DEFAULT


def rpm_for_lane(lane: str) -> int:
    lane = str(lane or LANE_DEFAULT).strip().lower() or LANE_DEFAULT
    mapping = {
        LANE_ARK: int(getattr(config, "DRAMA_RPM_ARK", 0) or 0),
        LANE_DASHSCOPE: int(getattr(config, "DRAMA_RPM_DASHSCOPE", 0) or 0),
        LANE_LIP: int(getattr(config, "DRAMA_RPM_LIP", 0) or 0),
        LANE_DEFAULT: int(getattr(config, "DRAMA_RPM_DEFAULT", 0) or 0),
    }
    rpm = mapping.get(lane, mapping[LANE_DEFAULT])
    if rpm <= 0:
        rpm = int(getattr(config, "DRAMA_RPM_DEFAULT", 0) or 0)
    return max(0, rpm)


def acquire_lane(lane_or_provider: str) -> str:
    """Block until a token is available for the lane. Returns lane id."""
    raw = str(lane_or_provider or "").strip().lower()
    lane = raw if raw in (LANE_ARK, LANE_DASHSCOPE, LANE_LIP, LANE_DEFAULT) else lane_for_provider(raw)
    rpm = rpm_for_lane(lane)
    rate_limiter_for(lane, rpm).acquire()
    return lane


def acquire_provider_lanes_for_shot(slug: str, shot: dict[str, Any] | None = None) -> list[str]:
    """Acquire lanes for the providers this shot is likely to hit (image/motion/tts/lip)."""
    from tools.drama_models import infer_kind, load_models, models_with_overrides

    models = models_with_overrides(slug, shot=shot) if shot else load_models(slug)
    kind = infer_kind(shot) if shot else "dialogue"
    providers: list[str] = []
    img = ((models.get("image") or {}).get(kind) or {})
    if isinstance(img, dict) and img.get("provider"):
        providers.append(str(img["provider"]))
    motion = ((models.get("motion") or {}).get(kind) or {})
    if isinstance(motion, dict) and motion.get("provider"):
        providers.append(str(motion["provider"]))
    tts = models.get("tts") if isinstance(models.get("tts"), dict) else {}
    if tts.get("provider"):
        providers.append(str(tts["provider"]))
    lip = models.get("lip") if isinstance(models.get("lip"), dict) else {}
    if lip.get("provider"):
        providers.append(str(lip["provider"]))

    acquired: list[str] = []
    seen: set[str] = set()
    for pid in providers:
        lane = lane_for_provider(pid)
        if lane in seen:
            continue
        seen.add(lane)
        acquire_lane(lane)
        acquired.append(lane)
    return acquired


def parallel_map(
    items: list[T],
    worker: Callable[[T], R],
    *,
    max_workers: int | None = None,
    cancel_check: Callable[[], None] | None = None,
    on_done: Callable[[int, T, R | BaseException], None] | None = None,
) -> list[R]:
    """Run worker over items with a bounded thread pool; fail-fast on first error."""
    if not items:
        return []
    workers = max(1, int(max_workers if max_workers is not None else shot_concurrency()))
    if workers <= 1 or len(items) == 1:
        out: list[R] = []
        for i, item in enumerate(items):
            if cancel_check:
                cancel_check()
            try:
                result = worker(item)
            except BaseException as exc:  # noqa: BLE001 — propagate after callback
                if on_done:
                    on_done(i, item, exc)
                raise
            if on_done:
                on_done(i, item, result)
            out.append(result)
        return out

    results: list[R | None] = [None] * len(items)
    error: list[BaseException] = []
    futures: dict[Future[R], int] = {}
    with ThreadPoolExecutor(max_workers=min(workers, len(items))) as pool:
        for i, item in enumerate(items):
            if cancel_check:
                cancel_check()
            futures[pool.submit(worker, item)] = i
        for fut in as_completed(futures):
            i = futures[fut]
            item = items[i]
            if error:
                fut.cancel()
                continue
            if cancel_check:
                try:
                    cancel_check()
                except BaseException as exc:  # noqa: BLE001
                    error.append(exc)
                    continue
            try:
                result = fut.result()
            except BaseException as exc:  # noqa: BLE001
                error.append(exc)
                if on_done:
                    on_done(i, item, exc)
                continue
            results[i] = result
            if on_done:
                on_done(i, item, result)
    if error:
        raise error[0]
    return list(results)  # type: ignore[return-value]


class ProgressClock:
    """Thread-safe stage timing waterfall for progress SSE / produce stages."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._t0 = time.monotonic()
        self._marks: list[dict[str, Any]] = []
        self._current: dict[str, float] = {}

    def start(self, stage: str, **extra: Any) -> None:
        with self._lock:
            self._current[stage] = time.monotonic()
            self._marks.append(
                {
                    "event": "start",
                    "stage": stage,
                    "t": round(time.monotonic() - self._t0, 3),
                    **extra,
                }
            )

    def end(self, stage: str, **extra: Any) -> None:
        with self._lock:
            started = self._current.pop(stage, None)
            elapsed = round(time.monotonic() - started, 3) if started is not None else None
            self._marks.append(
                {
                    "event": "end",
                    "stage": stage,
                    "t": round(time.monotonic() - self._t0, 3),
                    "elapsed_sec": elapsed,
                    **extra,
                }
            )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "elapsed_sec": round(time.monotonic() - self._t0, 3),
                "marks": list(self._marks),
            }
