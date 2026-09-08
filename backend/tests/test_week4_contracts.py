"""Week4 contracts: episode_status card + blueprint voice/bgm materialize."""

from __future__ import annotations

from pathlib import Path

from tools.drama_episode_status import build_episode_status, write_episode_status
from tools.drama_script_blueprint import materialize_script_assets


def _patch_ws(monkeypatch, tmp_path: Path):
    from tools import workspace as ws

    def _resolve(rel: str):
        return tmp_path / Path(rel)

    monkeypatch.setattr(ws, "workspace_root", lambda: tmp_path)
    monkeypatch.setattr(ws, "resolve_safe", _resolve)


def test_build_episode_status_empty_shots():
    text = build_episode_status("demo", 1, {"shots": [], "qc": {"verdict": "待修"}})
    assert "镜头总数: 0" in text
    assert "先生成/保存结构化剧本" in text


def test_build_episode_status_dirty_and_failed():
    doc = {
        "qc": {"verdict": "待修"},
        "shots": [
            {"n": 1, "dirty": ["scene"], "assets": {"scene": "a.png"}},
            {"n": 2, "qc": {"produce_ok": False}, "assets": {}},
            {"n": 3, "assets": {"scene": "b.png", "voice": "c.mp3"}},
        ],
    }
    text = build_episode_status("demo", 1, doc)
    assert "脏镜: 1" in text
    assert "产线失败镜: 2" in text
    assert "rerender_dirty" in text


def test_write_episode_status_file(monkeypatch, tmp_path):
    _patch_ws(monkeypatch, tmp_path)
    rel = write_episode_status("demo", 1, {"shots": [], "qc": {}})
    path = tmp_path / Path(rel)
    assert path.is_file()
    assert "EP01 状态卡" in path.read_text(encoding="utf-8")


def test_materialize_voice_from_timbre_hint(monkeypatch, tmp_path):
    _patch_ws(monkeypatch, tmp_path)
    (tmp_path / "dramas" / "demo" / "episodes").mkdir(parents=True)
    (tmp_path / "dramas" / "demo" / "episodes" / "ep01.md").write_text("# EP01\n", encoding="utf-8")

    from tools.drama_studio import save_project
    from tools.drama_shots import save_doc

    save_project(
        "demo",
        {
            "slug": "demo",
            "title": "demo",
            "episodes": [{"n": 1, "path": "dramas/demo/episodes/ep01.md"}],
        },
    )
    save_doc(
        {
            "slug": "demo",
            "episode": 1,
            "shots": [{"n": 1, "roles": ["林薇"], "assets": {}}],
            "meta": {},
        }
    )

    parsed = {
        "cast": [
            {
                "name": "林薇",
                "外形": "黑长直，冷白皮",
                "性格": "冷静",
                "音色倾向": "女声温柔",
                "口头禅": "",
                "别名": "",
            }
        ],
        "locations": [],
        "props": [],
        "meta": {"配乐": "古风悬疑紧张"},
        "shots": [{"n": 1, "roles": ["林薇"]}],
    }
    out = materialize_script_assets("demo", 1, parsed)
    assert out.get("characters")
    from tools.drama_characters import load_characters
    from tools.drama_audio import load_mix

    cards = load_characters("demo")
    char = next(c for c in cards if c.get("name") == "林薇")
    assert char.get("gender") == "female"
    assert char.get("voice")
    mix = load_mix("demo", 1)
    assert mix.get("bgm_intent") == "古风悬疑紧张"
