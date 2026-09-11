"""Step contracts: step1_script / step2_character / step3_scene."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image


def _patch_ws(monkeypatch, tmp_path: Path):
    from tools import workspace as ws

    def _resolve(rel: str):
        return tmp_path / Path(str(rel).replace("\\", "/"))

    monkeypatch.setattr(ws, "workspace_root", lambda: tmp_path)
    monkeypatch.setattr(ws, "resolve_safe", _resolve)
    monkeypatch.setattr("tools.drama_step_contract.resolve_safe", _resolve)


def _seed_step1(tmp_path: Path, slug: str = "demo", episode: int = 1):
    from tools import drama_step_contract as sc

    root = tmp_path / f"dramas/{slug}/step1_script"
    (root / f"ep{episode:02d}").mkdir(parents=True)
    script = root / f"ep{episode:02d}.md"
    shots = root / f"ep{episode:02d}/shots.json"
    script.write_text("# ep\n\n### Shot 1 (0-3s)\n画面：测试\n角色：阿明\n", encoding="utf-8")
    shots.write_text(
        '{"slug":"demo","episode":1,"shots":[{"n":1,"角色":["阿明"],"画面":"测试"}]}',
        encoding="utf-8",
    )
    sc.write_step_ok(
        slug,
        episode,
        "script",
        paths=[
            f"dramas/{slug}/step1_script/ep{episode:02d}.md",
            f"dramas/{slug}/step1_script/ep{episode:02d}/shots.json",
        ],
    )
    return script, shots


def test_publish_script_freezes_step1(tmp_path, monkeypatch):
    from tools import drama_step_contract as sc

    _patch_ws(monkeypatch, tmp_path)
    script = tmp_path / "dramas/demo/episodes/ep01.md"
    shots = tmp_path / "dramas/demo/videos/ep01/shots.json"
    script.parent.mkdir(parents=True)
    shots.parent.mkdir(parents=True)
    script.write_text("# ep01\n\n## Shot 1\n你好世界这是剧本\n", encoding="utf-8")
    shots.write_text('{"episode":1,"shots":[{"n":1,"画面":"A","角色":["阿明"]}]}', encoding="utf-8")

    out = sc.publish_script_step(
        "demo",
        1,
        script_rel="dramas/demo/episodes/ep01.md",
        shots_rel="dramas/demo/videos/ep01/shots.json",
        doc={"slug": "demo", "episode": 1, "shots": [{"n": 1, "画面": "A", "角色": ["阿明"], "assets": {"x": 1}}]},
    )
    assert out["frozen"] is True
    assert (tmp_path / "dramas/demo/step1_script/ep01.md").is_file()
    assert (tmp_path / "dramas/demo/step1_script/ep01/shots.json").is_file()
    sc.require_step1("demo", 1)

    # automation must not overwrite
    script.write_text("# CHANGED BY AUTOMATION\n\n## Shot 1\nxxx\n", encoding="utf-8")
    again = sc.publish_script_step(
        "demo",
        1,
        script_rel="dramas/demo/episodes/ep01.md",
        shots_rel="dramas/demo/videos/ep01/shots.json",
        from_ui=False,
    )
    assert again.get("skipped_write") is True
    text = (tmp_path / "dramas/demo/step1_script/ep01.md").read_text(encoding="utf-8")
    assert "CHANGED BY AUTOMATION" not in text

    # UI may overwrite
    sc.publish_script_step(
        "demo",
        1,
        script_rel="dramas/demo/episodes/ep01.md",
        shots_rel="dramas/demo/videos/ep01/shots.json",
        from_ui=True,
    )
    text2 = (tmp_path / "dramas/demo/step1_script/ep01.md").read_text(encoding="utf-8")
    assert "CHANGED BY AUTOMATION" in text2


def test_publish_and_require_cast_step2(tmp_path, monkeypatch):
    from tools import drama_step_contract as sc

    _patch_ws(monkeypatch, tmp_path)
    _seed_step1(tmp_path)
    body = tmp_path / "dramas/demo/characters/a.png"
    face = tmp_path / "dramas/demo/characters/a_face.png"
    body.parent.mkdir(parents=True)
    Image.new("RGB", (64, 64), (10, 20, 30)).save(body)
    Image.new("RGB", (64, 64), (40, 50, 60)).save(face)

    cards = [
        {
            "id": "a",
            "name": "阿明",
            "category": "character",
            "ref": "dramas/demo/characters/a.png",
            "ref_face": "dramas/demo/characters/a_face.png",
            "ref_locked": True,
        }
    ]
    monkeypatch.setattr("tools.drama_characters.load_characters", lambda s: cards)
    monkeypatch.setattr(
        "tools.drama_characters.find_character",
        lambda cards_, role: cards_[0] if role in ("a", "阿明") else None,
    )
    monkeypatch.setattr("tools.drama_characters.character_requires_face_identity", lambda c: True)
    monkeypatch.setattr("tools.drama_characters.ref_exists", lambda s, c: True)
    monkeypatch.setattr("tools.drama_characters.ref_face_exists", lambda s, c: True)
    monkeypatch.setattr("tools.drama_characters.normalize_category", lambda c: "character")
    monkeypatch.setattr("tools.drama_characters.ref_rel", lambda s, cid: f"dramas/{s}/characters/{cid}.png")
    monkeypatch.setattr(
        "tools.drama_characters.ref_face_rel",
        lambda s, cid: f"dramas/{s}/characters/{cid}_face.png",
    )
    monkeypatch.setattr("tools.drama_shots.normalize_roles", lambda x: list(x or []))

    doc = {"episode": 1, "shots": [{"n": 1, "角色": ["阿明"]}]}
    out = sc.publish_cast_step("demo", doc)
    assert out["count"] == 1
    assert (tmp_path / "dramas/demo/step2_character/output/a.png").is_file()
    assert (tmp_path / "dramas/demo/step2_character/output/a_face.png").is_file()
    sc.require_cast_for_shot("demo", {"n": 1, "角色": ["阿明"]})
    sc.require_step_ok("demo", 1, "cast")


def test_require_cast_fails_loud(tmp_path, monkeypatch):
    from tools import drama_step_contract as sc

    _patch_ws(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "tools.drama_characters.load_characters",
        lambda s: [{"id": "a", "name": "阿明", "category": "character"}],
    )
    monkeypatch.setattr("tools.drama_characters.find_character", lambda cards, role: cards[0])
    monkeypatch.setattr("tools.drama_characters.character_requires_face_identity", lambda c: True)
    monkeypatch.setattr("tools.drama_characters.normalize_category", lambda c: "character")
    monkeypatch.setattr("tools.drama_shots.normalize_roles", lambda x: list(x or []))

    with pytest.raises(sc.StepContractError, match="定妆门禁|缺少正式输出"):
        sc.require_cast_for_shot("demo", {"n": 2, "角色": ["阿明"]})


def test_publish_scene_step3(tmp_path, monkeypatch):
    from tools import drama_step_contract as sc

    _patch_ws(monkeypatch, tmp_path)
    work = tmp_path / "dramas/demo/videos/ep01/shot01_scene.png"
    work.parent.mkdir(parents=True)
    Image.new("RGB", (32, 32), (1, 2, 3)).save(work)
    sc.publish_scene_step("demo", 1, 1, "dramas/demo/videos/ep01/shot01_scene.png")
    sc.require_scene_step("demo", 1, 1)
    assert (tmp_path / "dramas/demo/step3_scene/output/ep01/shot01_scene.png").is_file()
    assert (tmp_path / "dramas/demo/step3_scene/temp/ep01/shot01_scene.png").is_file()


def test_publish_video_audio_final_steps(tmp_path, monkeypatch):
    from tools import drama_step_contract as sc

    _patch_ws(monkeypatch, tmp_path)
    base = tmp_path / "dramas/demo/videos/ep01"
    base.mkdir(parents=True)
    motion = base / "shot01_motion.mp4"
    voice = base / "shot01.mp3"
    clip = base / "shot01.mp4"
    export = tmp_path / "dramas/demo/videos/ep01.mp4"
    for p, size in ((motion, 800), (voice, 200), (clip, 900), (export, 1200)):
        p.write_bytes(b"\x00" * size)

    sc.publish_motion_step("demo", 1, 1, "dramas/demo/videos/ep01/shot01_motion.mp4")
    sc.require_motion_step("demo", 1, 1)
    assert (tmp_path / "dramas/demo/step4_video/output/ep01/shot01_motion.mp4").is_file()
    assert (tmp_path / "dramas/demo/step4_video/temp/ep01/shot01_motion.mp4").is_file()

    sc.publish_voice_step("demo", 1, 1, "dramas/demo/videos/ep01/shot01.mp3")
    sc.require_voice_step("demo", 1, 1)
    assert (tmp_path / "dramas/demo/step5_audio/output/ep01/shot01.mp3").is_file()

    sc.publish_clip_step("demo", 1, 1, "dramas/demo/videos/ep01/shot01.mp4")
    sc.require_clip_step("demo", 1, 1)
    sc.publish_shots_rendered_step("demo", 1, [1])
    sc.require_step_ok("demo", 1, "shots_rendered")

    sc.publish_export_step("demo", 1, "dramas/demo/videos/ep01.mp4")
    sc.require_step_ok("demo", 1, "export")
    assert (tmp_path / "dramas/demo/step6_final/output/ep01/ep01.mp4").is_file()
    assert (tmp_path / "dramas/demo/step6_final/temp/ep01/ep01.mp4").is_file()


def test_require_scene_fails_when_missing(tmp_path, monkeypatch):
    from tools import drama_step_contract as sc

    _patch_ws(monkeypatch, tmp_path)
    with pytest.raises(sc.StepContractError, match="缺少正式输出"):
        sc.require_scene_step("demo", 1, 9)
