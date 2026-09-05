"""P3：历史通过帧记忆检索。"""

from __future__ import annotations

from tools.drama_frame_memory import (
    add_passed_frame,
    load_frame_index,
    memory_prompt_clause,
    search_similar_frames,
)


def test_frame_memory_add_and_search(tmp_path, monkeypatch):
    import tools.drama_frame_memory as fm

    monkeypatch.setattr(fm, "frames_index_path", lambda slug: tmp_path / "index.json")

    # resolve_safe for scene existence: point to a real tiny file
    scene = tmp_path / "shot.png"
    scene.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)

    def _resolve(rel: str):
        if str(rel).endswith("shot.png") or "scene" in str(rel):
            return scene
        return tmp_path / "x"

    monkeypatch.setattr(fm, "resolve_safe", _resolve)

    shot = {
        "n": 1,
        "assets": {"scene": "dramas/demo/videos/ep01/shot01_scene.png"},
        "spatial_plan": {"hash": "abc", "identity_subject_id": "c1", "slots": []},
    }
    identity = {
        "pass": True,
        "character_id": "c1",
        "cosine": 0.9,
        "matches": [{"character_id": "c1", "matched": True}, {"character_id": "c2", "matched": True}],
    }
    assert add_passed_frame("demo", episode=1, shot=shot, identity=identity)
    hits = search_similar_frames(
        "demo",
        character_ids=["c1", "c2"],
        plan_hash="abc",
        identity_subject_id="c1",
        exclude_episode=1,
        exclude_shot=2,
        limit=2,
    )
    assert hits and hits[0]["plan_hash"] == "abc"
    assert "构图记忆参考" in memory_prompt_clause(hits)
    assert load_frame_index("demo")["frames"]
