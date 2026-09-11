"""Search Mixkit music in realtime and optionally download into shared catalog.

Examples::

    python backend/scripts/search_mixkit_bgm.py 悬疑
    python backend/scripts/search_mixkit_bgm.py piano --limit 10
    python backend/scripts/search_mixkit_bgm.py mysterious --download 871 --slot suspense_dark
    python backend/scripts/search_mixkit_bgm.py happy --download 839
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (SRC, ROOT):
    entry = str(path)
    if entry not in sys.path:
        sys.path.insert(0, entry)

import agent  # noqa: E402,F401


def main() -> int:
    parser = argparse.ArgumentParser(description="Realtime Mixkit music search / download")
    parser.add_argument("query", help="关键词 / mood / tag，如：悬疑、piano、mysterious")
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--download", type=int, default=0, help="按 Mixkit id 下载")
    parser.add_argument(
        "--slot",
        default="",
        help="写入内置曲库槽位 id（如 suspense_dark）；不填则存为 mixkit_{id}.mp3",
    )
    args = parser.parse_args()

    from tools.drama_mixkit_bgm import download_by_id, search_mixkit

    found = search_mixkit(args.query, limit=max(1, args.limit))
    print(json.dumps(found, ensure_ascii=False, indent=2))
    if not found.get("ok"):
        return 1

    if args.download:
        result = download_by_id(args.download, catalog_id=str(args.slot or "").strip())
        print("\n# downloaded")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1

    print("\n# 下一步：加 --download <id> [--slot suspense_dark] 下载")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
