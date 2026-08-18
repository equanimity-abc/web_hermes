"""D4 smoke: character cards in prompt/seed/voice; locked ref cannot be overwritten."""

from __future__ import annotations

import json
import os
import shutil

os.environ["IMAGE_GEN_PROVIDER"] = "none"

import agent.loop  # noqa: F401

from config import config
from tools.drama_characters import (
    CharacterError,
    character_seed,
    load_characters,
    primary_voice,
    resolve_shot_characters,
    save_character_ref,
    set_ref_locked,
)
from tools.drama_shots import load_doc
from tools.drama_studio import save_character, save_script
from tools.drama_video import _scene_prompt
from tools.workspace import resolve_safe

config.IMAGE_GEN_PROVIDER = "none"

SLUG = "d4-smoke"
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)
MD = """# D4 验收
- 时长: 20s
- 钩子: 开场
- 悬念: 谁丢了金箍

## 分镜
### Shot 1 (0-3s)
- 画面: 悟空特写
- 对白: 悟空：俺老孙来也
- 字幕: 俺老孙来也
- 角色: 悟空

### Shot 2 (3-6s)
- 画面: 悟空举棒
- 对白: 悟空：吃俺一棒
- 字幕: 吃俺一棒
- 角色: 悟空

### Shot 3 (6-9s)
- 画面: 悟空翻筋斗
- 对白: 悟空：走
- 字幕: 走
- 角色: 悟空

### Shot 4 (9-12s)
- 画面: 悟空落地
- 对白: 悟空：何方妖孽
- 字幕: 何方妖孽
- 角色: 悟空

### Shot 5 (12-16s)
- 画面: 悟空回望
- 对白: 悟空：且慢
- 字幕: 且慢

### Shot 6 (16-20s)
- 画面: 唐僧合十
- 对白: 唐僧：悟空，不可伤人
- 字幕: 不可伤人
- 角色: 唐僧
"""


def _shot(doc: dict, n: int) -> dict:
    return next(s for s in doc["shots"] if int(s["n"]) == n)


def main() -> None:
    root = resolve_safe(f"dramas/{SLUG}")
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    (root / "project.json").write_text(
        json.dumps({"slug": SLUG, "title": "D4 验收", "logline": "角色一致", "episodes": []}, ensure_ascii=False),
        encoding="utf-8",
    )

    wu = save_character(
        SLUG,
        {
            "id": "wukong",
            "name": "孙悟空",
            "aliases": "悟空、齐天大圣",
            "look": "golden fillet, fiery eyes, tiger-skin kilt, Ruyi Jingu Bang",
            "colors": "gold, crimson",
            "voice": "zh-CN-YunxiNeural",
        },
    )
    tang = save_character(
        SLUG,
        {
            "id": "tangseng",
            "name": "唐僧",
            "aliases": "唐僧、师傅",
            "look": "bald monk, kasaya robes, prayer beads, calm face",
            "voice": "zh-CN-YunyangNeural",
        },
    )
    assert wu["id"] == "wukong"
    assert tang["voice"] != wu["voice"]

    save_character_ref(SLUG, "wukong", PNG)
    set_ref_locked(SLUG, "wukong", True)
    try:
        save_character_ref(SLUG, "wukong", PNG + b"x")
        raise AssertionError("locked ref should not overwrite")
    except CharacterError:
        pass

    saved = save_script(SLUG, 1, MD)
    assert saved["count"] == 6, saved
    doc = load_doc(SLUG, 1)
    assert _shot(doc, 1)["角色"] == ["wukong"], _shot(doc, 1)
    assert _shot(doc, 5)["角色"] == ["wukong"], _shot(doc, 5)
    assert _shot(doc, 6)["角色"] == ["tangseng"], _shot(doc, 6)

    cards = load_characters(SLUG)
    prompts = []
    seeds = []
    for n in range(1, 6):
        shot = _shot(doc, n)
        cast = resolve_shot_characters(shot, cards)
        prompts.append(_scene_prompt("D4 验收", shot, cast, slug=SLUG))
        seeds.append(character_seed(SLUG, cast, n))
    for prompt in prompts:
        assert "golden fillet" in prompt, prompt
        assert "Sun Wukong gold headband" not in prompt
    bases = [seed - n * 17 for n, seed in enumerate(seeds, start=1)]
    assert len(set(bases)) == 1, bases
    monk = resolve_shot_characters(_shot(doc, 6), cards)
    monk_prompt = _scene_prompt("D4 验收", _shot(doc, 6), monk, slug=SLUG)
    assert "kasaya robes" in monk_prompt
    assert primary_voice(resolve_shot_characters(_shot(doc, 1), cards)) == "zh-CN-YunxiNeural"
    assert primary_voice(monk) == "zh-CN-YunyangNeural"
    print("D4 smoke ok: 5 shots share character seed/prompt; locked ref held")


if __name__ == "__main__":
    try:
        main()
    finally:
        root = resolve_safe(f"dramas/{SLUG}")
        if root.exists():
            shutil.rmtree(root)
