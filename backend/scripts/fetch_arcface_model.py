"""Download + extract the insightface buffalo_l model (ArcFace identity lock).

Run once when you have network access to the GitHub release server::

    python backend/scripts/fetch_arcface_model.py

``drama_qc._arcface_singleton`` will then pick it up automatically and enable the
best solution (identity lock) for multi-person lip sync. Until the model is
cached, lip sync degrades gracefully to the color heuristic and records a warning
instead of hanging on the download.
"""

from __future__ import annotations

import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

URL = "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip"
MODEL_ROOT = Path.home() / ".insightface" / "models"
TARGET = MODEL_ROOT / "buffalo_l"
REQUIRED = ("det_10g.onnx", "w600k_r50.onnx")


def main() -> int:
    if all((TARGET / name).is_file() for name in REQUIRED):
        print(f"[ok] buffalo_l already present at {TARGET}")
        return 0

    MODEL_ROOT.mkdir(parents=True, exist_ok=True)
    zip_path = MODEL_ROOT / "buffalo_l.zip"
    print(f"downloading {URL}")
    try:
        req = urllib.request.Request(URL, headers={"User-Agent": "my-tiktok-video-agent/1.0"})
        with urllib.request.urlopen(req, timeout=900) as resp, zip_path.open("wb") as fh:
            shutil.copyfileobj(resp, fh)
    except Exception as e:  # noqa: BLE001
        print(f"[fail] download failed: {e}", file=sys.stderr)
        try:
            zip_path.unlink(missing_ok=True)
        except OSError:
            pass
        return 1

    print("extracting ...")
    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(TARGET)
    finally:
        try:
            zip_path.unlink(missing_ok=True)
        except OSError:
            pass

    if all((TARGET / name).is_file() for name in REQUIRED):
        print(f"[ok] buffalo_l ready at {TARGET}")
        return 0
    print("[fail] extraction incomplete", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
