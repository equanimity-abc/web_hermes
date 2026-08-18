"""D3 smoke: freeze Shot 1, change ending; frozen shot stays, unlocked updates."""

from __future__ import annotations

import json
import os
import shutil

os.environ["IMAGE_GEN_PROVIDER"] = "none"

import agent.loop  # noqa: F401 — load tools via agent so dispatch exists

from config import config
from tools.drama_shots import load_doc
from tools.drama_studio import patch_shot, preview_script, save_script
from tools.workspace import resolve_safe

config.IMAGE_GEN_PROVIDER = "none"

SLUG = "d3-smoke"
MD = """# D3 验收
- 时长: 12s
- 钩子: 开场钩子
- 悬念: 旧悬念

## 分镜
### Shot 1 (0-3s)
- 画面: 原画面一
- 对白: 第一镜对白
- 字幕: 第一镜字幕

### Shot 2 (3-7s)
- 画面: 原画面二
- 对白: 第二镜对白
- 字幕: 第二镜字幕

### Shot 3 (7-12s)
- 画面: 原画面三
- 对白: 第三镜对白
- 字幕: 旧结尾字幕
"""

MD2 = """# D3 验收
- 时长: 12s
- 钩子: 开场钩子
- 悬念: 新悬念-谁偷了金箍

## 分镜
### Shot 1 (0-3s)
- 画面: 不该覆盖已锁整镜
- 对白: 第一镜对白
- 字幕: 第一镜字幕

### Shot 2 (3-7s)
- 画面: 原画面二
- 对白: 第二镜对白
- 字幕: 第二镜字幕

### Shot 3 (7-12s)
- 画面: 原画面三
- 对白: 第三镜对白
- 字幕: 新悬念字幕
"""


def _shot(doc: dict, n: int) -> dict:
    return next(s for s in doc["shots"] if int(s["n"]) == n)


def main() -> None:
    root = resolve_safe(f"dramas/{SLUG}")
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    (root / "project.json").write_text(
        json.dumps(
            {
                "slug": SLUG,
                "title": "D3 验收",
                "logline": "锁整镜后改结局",
                "episodes": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    first = save_script(SLUG, 1, MD)
    assert first["count"] == 3, first
    assert _shot(load_doc(SLUG, 1), 1)["画面"] == "原画面一"

    locked = patch_shot(SLUG, 1, 1, {"lock": ["shot"]})
    assert "shot" in locked["locked"], locked

    ignored = patch_shot(SLUG, 1, 1, {"画面": "检查器也不能改整镜"})
    assert ignored["shot"]["画面"] == "原画面一", ignored

    preview = preview_script(SLUG, 1, MD2)
    impact = preview["impact"]
    assert 1 in impact["frozen"], impact
    assert 3 in impact["affected"], impact
    assert 2 not in impact["affected"], impact
    assert "悬念" in impact["meta_changed"], impact

    saved = save_script(SLUG, 1, MD2)
    impact = saved["impact"]
    doc = load_doc(SLUG, 1)
    assert _shot(doc, 1)["画面"] == "原画面一", doc
    assert _shot(doc, 3)["字幕"] == "新悬念字幕", doc
    assert 1 in impact["frozen"], impact
    assert 3 in impact["affected"], impact
    assert 2 not in impact["affected"], impact
    assert 1 not in impact["affected"], impact
    assert not _shot(doc, 1).get("dirty"), _shot(doc, 1)
    assert "overlay" in (_shot(doc, 3).get("dirty") or []), _shot(doc, 3)
    on_disk = (root / "episodes" / "ep01.md").read_text(encoding="utf-8")
    assert "原画面一" in on_disk, on_disk
    assert "不该覆盖已锁整镜" not in on_disk, on_disk
    assert "新悬念-谁偷了金箍" in on_disk, on_disk
    print("D3 smoke ok:", impact["summary"])


if __name__ == "__main__":
    try:
        main()
    finally:
        root = resolve_safe(f"dramas/{SLUG}")
        if root.exists():
            shutil.rmtree(root)
