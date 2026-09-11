"""Backend entry: configure PYTHONPATH and run uvicorn."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
SRC = BACKEND / "src"
for path in (SRC, BACKEND):
    entry = str(path)
    if entry not in sys.path:
        sys.path.insert(0, entry)

import uvicorn  # noqa: E402

from config import config  # noqa: E402


def main() -> None:
    uvicorn.run(
        "main:app",
        host=config.HOST,
        port=config.PORT,
        reload=config.RELOAD,
    )


if __name__ == "__main__":
    main()
