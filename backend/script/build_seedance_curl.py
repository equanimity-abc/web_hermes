#!/usr/bin/env python3
"""Build Seedance I2V curl payload for one shot (manual verify).

Usage (from backend/):
  python script/build_seedance_curl.py --slug 45-1 --episode 1 --shot 2

Then set ARK_API_KEY and run the printed curl.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Print Seedance verify curl for one shot")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--episode", type=int, default=1)
    ap.add_argument("--shot", type=int, required=True)
    args = ap.parse_args()

    from tools.drama_failure_report import write_seedance_verify_payload

    out = write_seedance_verify_payload(args.slug, args.episode, args.shot)
    if not out.get("ok"):
        print(out.get("error") or "failed", file=sys.stderr)
        return 1
    print(f"# Shot {out['shot']} model={out['model']}")
    print(f"# scene={out['scene_rel']}")
    print(f"# payload={out['payload_path']}")
    print()
    print("# bash / Git Bash:")
    print(out["curl_submit"])
    print(out["curl_poll"].replace("TASK_ID", "<paste_task_id>"))
    print()
    print("# PowerShell:")
    print(out["curl_submit_ps"])
    print(out["curl_poll_ps"].replace("TASK_ID", "<paste_task_id>"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
