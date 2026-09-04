"""Download + extract the insightface buffalo_l model (ArcFace identity lock).

Run once when you have network access::

    python backend/scripts/fetch_arcface_model.py

``drama_qc._arcface_singleton`` will then pick it up automatically and enable the
best solution (identity lock) for multi-person lip sync. Until the model is
cached, lip sync degrades gracefully to the color heuristic and records a warning
instead of hanging on the download.

GitHub releases are often unreachable in CN; this script tries official URL first,
then common mirrors (ghproxy / HuggingFace / hf-mirror).
"""

from __future__ import annotations

import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

URLS = (
    "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip",
    "https://ghproxy.net/https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip",
    "https://ghfast.top/https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip",
    "https://hf-mirror.com/vladmandic/insightface-faceanalysis/resolve/main/buffalo_l.zip",
    "https://huggingface.co/vladmandic/insightface-faceanalysis/resolve/main/buffalo_l.zip",
)
MODEL_ROOT = Path.home() / ".insightface" / "models"
TARGET = MODEL_ROOT / "buffalo_l"
REQUIRED = ("det_10g.onnx", "w600k_r50.onnx")
# Official pack is ~275MB; reject truncated downloads early.
MIN_ZIP_BYTES = 200 * 1024 * 1024


def _already_ready() -> bool:
    return all((TARGET / name).is_file() for name in REQUIRED)


def _download(url: str, zip_path: Path) -> None:
    print(f"downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "my-tiktok-video-agent/1.0"})
    with urllib.request.urlopen(req, timeout=900) as resp, zip_path.open("wb") as fh:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        last_pct = -1
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            if total:
                pct = done * 100 // total
                if pct != last_pct and pct % 10 == 0:
                    last_pct = pct
                    print(f"  {pct}% ({done // 1024 // 1024}MB/{total // 1024 // 1024}MB)")
    size = zip_path.stat().st_size
    if size < MIN_ZIP_BYTES:
        raise RuntimeError(f"incomplete download: {size} bytes (need >= {MIN_ZIP_BYTES})")


def _extract(zip_path: Path) -> None:
    print("extracting ...")
    if TARGET.exists():
        shutil.rmtree(TARGET)
    TARGET.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(TARGET)
    # Some zips nest files under buffalo_l/buffalo_l/
    nested = TARGET / "buffalo_l"
    if nested.is_dir() and not (TARGET / "det_10g.onnx").is_file():
        for child in nested.iterdir():
            dest = TARGET / child.name
            if not dest.exists():
                shutil.move(str(child), str(dest))
        shutil.rmtree(nested, ignore_errors=True)


def main() -> int:
    if _already_ready():
        print(f"[ok] buffalo_l already present at {TARGET}")
        return 0

    MODEL_ROOT.mkdir(parents=True, exist_ok=True)
    zip_path = MODEL_ROOT / "buffalo_l.zip"
    last_err: Exception | None = None
    for url in URLS:
        try:
            zip_path.unlink(missing_ok=True)
            _download(url, zip_path)
            _extract(zip_path)
            break
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"[warn] {e}", file=sys.stderr)
            try:
                zip_path.unlink(missing_ok=True)
            except OSError:
                pass
            if TARGET.exists():
                shutil.rmtree(TARGET, ignore_errors=True)
    else:
        print(f"[fail] download failed: {last_err}", file=sys.stderr)
        return 1

    try:
        zip_path.unlink(missing_ok=True)
    except OSError:
        pass

    if _already_ready():
        print(f"[ok] buffalo_l ready at {TARGET}")
        return 0
    print("[fail] extraction incomplete", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
