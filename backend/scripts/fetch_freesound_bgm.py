"""Fill shared BGM catalog with free Freesound previews (CC0 / CC-BY).

Usage::

    set FREESOUND_API_KEY=your_key
    python backend/scripts/fetch_freesound_bgm.py
    python backend/scripts/fetch_freesound_bgm.py --force   # overwrite existing real files

Get a key: https://freesound.org/apiv2/apply/
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import agent  # noqa: E402,F401


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch free BGM from Freesound into shared catalog")
    parser.add_argument("--force", action="store_true", help="Replace existing non-procedural files")
    parser.add_argument("--id", default="", help="Only fetch one catalog id (e.g. suspense_dark)")
    args = parser.parse_args()

    if not os.getenv("FREESOUND_API_KEY", "").strip():
        # Load .env if present
        env_path = ROOT / ".env"
        if env_path.is_file():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                if k.strip() == "FREESOUND_API_KEY" and v.strip() and not os.getenv("FREESOUND_API_KEY"):
                    os.environ["FREESOUND_API_KEY"] = v.strip().strip('"').strip("'")

    from tools.drama_freesound_bgm import fetch_all_catalog_bgm, fetch_one_mood, freesound_api_key

    if not freesound_api_key():
        print("ERROR: 请先设置 FREESOUND_API_KEY（https://freesound.org/apiv2/apply/）", file=sys.stderr)
        return 2

    if args.id:
        result = fetch_one_mood(args.id.strip(), force=args.force)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1

    result = fetch_all_catalog_bgm(force=args.force)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        return 1
    print(
        f"\n完成：真曲 {result.get('real_tracks')}/{result.get('total')}；"
        f"署名见 workspace/{result.get('attribution_index')}"
    )
    if result.get("errors"):
        print("部分失败：", file=sys.stderr)
        for e in result["errors"]:
            print(f"  - {e}", file=sys.stderr)
        return 1 if result.get("real_tracks", 0) == 0 else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
