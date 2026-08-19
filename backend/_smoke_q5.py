"""Q5 smoke: director suggests hook/rhythm/max 2 reactions; never auto-applies or locks."""

from __future__ import annotations

import json
import os
import shutil

os.environ["IMAGE_GEN_PROVIDER"] = "none"

import agent.loop  # noqa: F401

from tools.drama_director import MAX_REACTION_SUGGESTIONS
from tools.drama_shots import load_doc, save_doc
from tools.drama_studio import (
    apply_coverage,
    dismiss_coverage,
    lock_coverage,
    save_character,
    save_script,
    suggest_coverage,
)
from tools.loader import plugin_prompt_hints
from tools.workspace import resolve_safe

SLUG = "q5-smoke"
MD = """# Q5 验收
- 时长: 20s
- 钩子:
- 悬念: 结尾

## 分镜
### Shot 1 (0-4s)
- 画面: 宫殿远景
- 对白:
- 字幕:

### Shot 2 (4-8s)
- 画面: 对白特写
- 对白: 今夜入宫
- 字幕:
- 角色: hero

### Shot 3 (8-12s)
- 画面: 对白特写
- 对白: 你敢拦我
- 字幕:
- 角色: hero

### Shot 4 (12-16s)
- 画面: 对白特写
- 对白: 给我让开
- 字幕:
- 角色: hero

### Shot 5 (16-20s)
- 画面: 对白特写
- 对白: 否则别怪我不客气
- 字幕:
- 角色: hero
"""


def _shot(doc: dict, n: int) -> dict:
    return next(s for s in doc["shots"] if int(s["n"]) == n)


def _open(coverage: dict) -> list[dict]:
    return [s for s in (coverage.get("suggestions") or []) if s.get("status") == "open"]


def main() -> None:
    root = resolve_safe(f"dramas/{SLUG}")
    try:
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True)
        (root / "project.json").write_text(
            json.dumps({"slug": SLUG, "title": "Q5", "logline": "导演建议", "episodes": []}, ensure_ascii=False),
            encoding="utf-8",
        )
        save_character(SLUG, {"id": "hero", "name": "主角", "look": "黑发", "voice": "zh-CN-YunxiNeural"})
        save_script(SLUG, 1, MD)
        doc = load_doc(SLUG, 1)
        _shot(doc, 1)["kind"] = "establishing"
        _shot(doc, 1)["size"] = "WS"
        for n in (2, 3, 4, 5):
            shot = _shot(doc, n)
            shot["kind"] = "dialogue"
            shot["size"] = "CU"
            shot["speaker"] = "hero"
        save_doc(doc)

        kinds_before = {int(s["n"]): s.get("kind") for s in load_doc(SLUG, 1)["shots"]}
        locked_before = {int(s["n"]): list(s.get("locked") or []) for s in load_doc(SLUG, 1)["shots"]}

        result = suggest_coverage(SLUG, 1)
        coverage = result["coverage"]
        doc = load_doc(SLUG, 1)
        kinds_after = {int(s["n"]): s.get("kind") for s in doc["shots"]}
        locked_after = {int(s["n"]): list(s.get("locked") or []) for s in doc["shots"]}
        assert kinds_after == kinds_before, (kinds_before, kinds_after)
        assert locked_after == locked_before, (locked_before, locked_after)
        assert result.get("hint")

        opened = _open(coverage)
        types = {item["type"] for item in opened}
        assert "hook_3s" in types, opened
        reactions = [item for item in opened if item["type"] == "reaction"]
        assert len(reactions) == MAX_REACTION_SUGGESTIONS, reactions
        assert len(reactions) <= 2
        assert any(item["type"] == "size_rhythm" for item in opened), opened

        skill_hints = plugin_prompt_hints()
        assert any("suggest_coverage" in hint for hint in skill_hints), skill_hints

        rid = reactions[0]["id"]
        shot_n = int(reactions[0]["shot"])
        apply_coverage(SLUG, 1, rid)
        applied = _shot(load_doc(SLUG, 1), shot_n)
        assert applied["kind"] == "reaction", applied
        assert "kind" not in (applied.get("locked") or [])
        assert "shot" not in (applied.get("locked") or [])

        hook = next(item for item in opened if item["type"] == "hook_3s")
        dismiss_coverage(SLUG, 1, hook["id"])
        again = suggest_coverage(SLUG, 1)["coverage"]
        hook_again = next(item for item in again["suggestions"] if item["id"] == hook["id"])
        assert hook_again["status"] == "dismissed", hook_again
        assert hook_again["id"] not in {item["id"] for item in _open(again)}

        leftover = next(item for item in _open(again) if item["type"] == "reaction")
        lock_coverage(SLUG, 1, leftover["id"])
        locked_shot = _shot(load_doc(SLUG, 1), int(leftover["shot"]))
        assert "kind" in (locked_shot.get("locked") or []), locked_shot
        assert locked_shot["kind"] != "reaction"
        third = suggest_coverage(SLUG, 1)["coverage"]
        still_open = [item for item in _open(third) if item["id"] == leftover["id"]]
        assert not still_open, still_open
        open_reactions = [item for item in _open(third) if item["type"] == "reaction"]
        assert len(open_reactions) <= MAX_REACTION_SUGGESTIONS, open_reactions

        print("Q5 smoke ok")
    finally:
        if root.exists():
            shutil.rmtree(root)


if __name__ == "__main__":
    main()
