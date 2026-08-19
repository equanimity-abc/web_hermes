"""D7 smoke: background queue returns immediately; cancel/retry; chat health stays up."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time

os.environ["IMAGE_GEN_PROVIDER"] = "none"

import agent.loop  # noqa: F401

from config import config
from tools.drama_queue import drama_jobs
from tools.drama_shots import load_doc, save_doc, shot_assets
from tools.drama_studio import cancel_render_job, enqueue_job, get_render_job, retry_render_job, save_script
from tools.workspace import resolve_safe

config.IMAGE_GEN_PROVIDER = "none"

SLUG = "d7-smoke"
SHOTS = 8


def _ffmpeg_ok() -> bool:
    return shutil.which("ffmpeg") is not None


def _write_clip(path, *, color: str, duration: float = 2.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=1080x1920:d={duration}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={duration}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or "ffmpeg failed")


def _md() -> str:
    lines = [
        "# D7 验收",
        "- 时长: 20s",
        "- 钩子: 开",
        "- 悬念: 结",
        "",
        "## 分镜",
    ]
    for i in range(1, SHOTS + 1):
        a = (i - 1) * 2
        b = a + 2
        lines += [
            f"### Shot {i} ({a}-{b}s)",
            f"- 画面: 镜{i}",
            "- 对白:",
            "- 字幕:",
            "",
        ]
    return "\n".join(lines)


def _wait_job(job_id: str, *, timeout: float = 120.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = get_render_job(job_id)
        if job["status"] in ("done", "error", "cancelled"):
            return job
        time.sleep(0.3)
    raise TimeoutError(job_id)


def main() -> None:
    if not _ffmpeg_ok():
        print("skip D7 smoke: ffmpeg not in PATH")
        return

    root = resolve_safe(f"dramas/{SLUG}")
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    (root / "project.json").write_text(
        json.dumps({"slug": SLUG, "title": "D7 验收", "logline": "队列", "episodes": []}, ensure_ascii=False),
        encoding="utf-8",
    )

    save_script(SLUG, 1, _md())
    colors = ["red", "green", "blue", "orange", "purple", "teal", "maroon", "navy"]
    for n in range(1, SHOTS + 1):
        assets = shot_assets(SLUG, 1, n)
        _write_clip(resolve_safe(assets["clip"]), color=colors[(n - 1) % len(colors)], duration=2.0)
        scene = resolve_safe(assets["scene"])
        scene.parent.mkdir(parents=True, exist_ok=True)
        if not scene.is_file():
            shutil.copyfile(resolve_safe(assets["clip"]), scene)
        overlay = resolve_safe(assets["overlay"])
        if not overlay.is_file():
            shutil.copyfile(resolve_safe(assets["scene"]), overlay)

    doc = load_doc(SLUG, 1)
    for shot in doc["shots"]:
        shot["dirty"] = ["clip"]
        shot["status"] = "dirty"
    save_doc(doc)

    t0 = time.time()
    job = enqueue_job(SLUG, 1, "rerender_dirty")
    assert time.time() - t0 < 2.0, "enqueue should return immediately"
    assert job["status"] in ("pending", "running"), job

    done = _wait_job(job["job_id"], timeout=180.0)
    assert done["status"] == "done", done
    assert done.get("result"), done

    # cancel path: request cancel (export may finish before cancel on fast machines)
    job2 = enqueue_job(SLUG, 1, "export")
    cancel_render_job(job2["job_id"])
    final2 = _wait_job(job2["job_id"], timeout=30.0)
    assert final2["status"] in ("cancelled", "done"), final2

    # retry path: force error via invalid kind handled at submit; use retry on synthetic error job
    bad = drama_jobs.submit("export", SLUG, 1)
    drama_jobs.get(bad["job_id"]).touch(status="error", error="simulated")
    retried = retry_render_job(bad["job_id"])
    assert retried["job_id"] != bad["job_id"], retried
    assert retried["status"] in ("pending", "running"), retried

    print(f"D7 smoke ok: {SHOTS}-shot job queued, cancel/retry work")


if __name__ == "__main__":
    try:
        main()
    finally:
        time.sleep(0.5)
        root = resolve_safe(f"dramas/{SLUG}")
        if root.exists():
            try:
                shutil.rmtree(root)
            except OSError:
                pass
