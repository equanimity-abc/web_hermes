"""Fill shared BGM catalog with Mixkit free stock music (no API key).

Usage::

    python backend/scripts/fetch_mixkit_bgm.py
    python backend/scripts/fetch_mixkit_bgm.py --force
    python backend/scripts/fetch_mixkit_bgm.py --id suspense_dark

License: https://mixkit.co/license/#musicFree
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Match tests/conftest: import agent before tools to avoid circular import.
import agent  # noqa: E402,F401


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch free BGM from Mixkit into shared catalog")
    parser.add_argument("--force", action="store_true", help="Replace existing non-procedural files")
    parser.add_argument("--id", default="", help="Only fetch one catalog id")
    args = parser.parse_args()

    from tools.drama_mixkit_bgm import fetch_all_catalog_bgm, fetch_one_mood

    if args.id:
        result = fetch_one_mood(args.id.strip(), force=args.force)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1

    result = fetch_all_catalog_bgm(force=args.force)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(
        f"\n完成：真曲 {result.get('real_tracks')}/{result.get('total')}；"
        f"署名/来源见 workspace/{result.get('attribution_index')}"
    )
    if result.get("errors"):
        print("部分失败：", file=sys.stderr)
        for e in result["errors"]:
            print(f"  - {e}", file=sys.stderr)
        return 1 if int(result.get("real_tracks") or 0) == 0 else 0
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
