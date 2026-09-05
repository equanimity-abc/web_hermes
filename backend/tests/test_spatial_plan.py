"""P0：角色–空间预规划与多人脸一对一匹配。"""

from __future__ import annotations

from tools.drama_qc import _cosine, match_faces_to_refs
from tools.drama_spatial import (
    build_spatial_plan,
    rewrite_scene_for_plan,
    spatial_prompt_clause,
)


def test_dual_shot_spatial_plan_and_rewrite():
    shot = {
        "n": 4,
        "kind": "dialogue",
        "speaker": "玉兔",
        "identity_subject": "",
        "画面": "竖屏远景，嫦娥拎着玉兔站在广寒宫边",
        "角色": ["嫦娥", "玉兔"],
    }
    # 无真实项目卡时 build 用空 cast → slots 可能空；用最小 stub 测 rewrite + clause
    plan = {
        "version": 1,
        "identity_subject_id": "yutu",
        "speaker_id": "yutu",
        "slots": [
            {
                "character_id": "yutu",
                "character_name": "玉兔",
                "role": "identity",
                "anchor": "right_front",
                "bbox_norm": [0.28, 0.12, 0.92, 0.80],
                "min_face_ratio": 0.08,
            },
            {
                "character_id": "ce",
                "character_name": "嫦娥",
                "role": "support",
                "anchor": "left_mid",
                "bbox_norm": [0.05, 0.18, 0.48, 0.78],
                "min_face_ratio": 0.04,
            },
        ],
    }
    rewritten = rewrite_scene_for_plan(shot["画面"], plan)
    assert "中近景" in rewritten
    assert "远景" not in rewritten.replace("中近景", "")
    assert "玉兔" in rewritten
    clause = spatial_prompt_clause(plan)
    assert "构图预规划" in clause
    assert "玉兔" in clause and "嫦娥" in clause


def test_match_faces_greedy_one_to_one():
    def vec(i: int) -> list[float]:
        v = [0.0] * 16
        v[i] = 1.0
        return v

    refs = [
        {"character_id": "a", "character_name": "A", "role": "identity", "emb": vec(0)},
        {"character_id": "b", "character_name": "B", "role": "support", "emb": vec(1)},
    ]
    faces = [
        {"emb": vec(1), "bbox": [0, 0, 10, 10], "area": 100, "img_w": 100, "img_h": 100},
        {"emb": vec(0), "bbox": [20, 20, 50, 50], "area": 900, "img_w": 100, "img_h": 100},
    ]
    rows = match_faces_to_refs(refs, faces, match_floor=0.35)
    by_id = {r["character_id"]: r for r in rows}
    assert by_id["a"]["matched"] and by_id["a"]["face_index"] == 1
    assert by_id["b"]["matched"] and by_id["b"]["face_index"] == 0
    assert _cosine(faces[1]["emb"], refs[0]["emb"]) > 0.99
