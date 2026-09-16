"""锁定前定妆校验（单次生成，无自动重抽）。"""

from __future__ import annotations

import pytest

from tools.drama_models import default_models
from tools.drama_qc import validate_character_ref


def test_qc_defaults_have_no_auto_retry_knobs():
    qc = default_models()["qc"]
    assert "identity_ref_retries" not in qc
    assert "identity_scene_retries" not in qc


def test_validate_character_ref_missing_file_not_ok():
    res = validate_character_ref(None)
    assert res["ok"] is False
    assert res["reason"] == "missing_ref"


def test_validate_character_ref_no_insightface(tmp_path, monkeypatch):
    png = tmp_path / "ref.png"
    png.write_bytes(b"x" * 64)
    monkeypatch.setattr("tools.drama_qc._arcface_ready", lambda: False)
    res = validate_character_ref(png)
    assert res["ok"] is False
    assert res["reason"] == "no_insightface"


def test_validate_character_ref_no_face(tmp_path, monkeypatch):
    png = tmp_path / "ref.png"
    png.write_bytes(b"x" * 64)
    monkeypatch.setattr("tools.drama_qc._arcface_ready", lambda: True)
    monkeypatch.setattr("tools.drama_qc._arcface_faces", lambda path: ([], "no_face"))
    res = validate_character_ref(png)
    assert res["ok"] is False
    assert res["reason"] == "no_face"
    assert res["face_count"] == 0
    assert "InsightFace" in res["hint"]
    assert "0 张脸" in res["hint"]


def test_validate_character_ref_arcface_error(tmp_path, monkeypatch):
    png = tmp_path / "ref.png"
    png.write_bytes(b"x" * 64)
    monkeypatch.setattr("tools.drama_qc._arcface_ready", lambda: True)
    monkeypatch.setattr("tools.drama_qc._arcface_faces", lambda path: ([], "arcface_error"))
    res = validate_character_ref(png)
    assert res["ok"] is False
    assert res["reason"] == "arcface_error"


def test_validate_character_ref_ok(tmp_path, monkeypatch):
    png = tmp_path / "ref.png"
    png.write_bytes(b"x" * 64)
    monkeypatch.setattr("tools.drama_qc._arcface_ready", lambda: True)
    monkeypatch.setattr(
        "tools.drama_qc._arcface_faces",
        lambda path: ([{"emb": [0.1] * 512, "area": 100.0}], "arcface"),
    )
    res = validate_character_ref(png)
    assert res["ok"] is True
    assert res["method"] == "arcface"
    assert res["dims"] == 512
    assert res["face_count"] == 1


def test_validate_character_cast_ready_face_fail_body_ok(tmp_path, monkeypatch):
    from tools.drama_qc import validate_character_cast_ready

    face = tmp_path / "c1_face.png"
    body = tmp_path / "c1.png"
    face.write_bytes(b"x" * 64)
    body.write_bytes(b"y" * 64)
    monkeypatch.setattr("tools.drama_qc._arcface_ready", lambda: True)
    monkeypatch.setattr(
        "tools.drama_qc.identity_enforcement",
        lambda slug="", models=None: "advisory",
    )

    def _faces(path):
        if path.name.endswith("_face.png"):
            return [], "no_face"
        return [{"emb": [0.2] * 512, "area": 80.0}], "arcface"

    monkeypatch.setattr("tools.drama_qc._arcface_faces", _faces)
    monkeypatch.setattr(
        "tools.workspace.resolve_safe",
        lambda rel: face if "face" in rel.replace("\\", "/") else body,
    )
    char = {
        "id": "c1",
        "name": "愚公",
        "ref": "dramas/demo/characters/c1.png",
        "ref_face": "dramas/demo/characters/c1_face.png",
    }
    res = validate_character_cast_ready("demo", char)
    # QC 永久关闭：有全身定妆文件即放行
    assert res["ok"] is True
    assert res["identity_anchor"] == "body"
    assert res["reason"] == "qc_disabled"


def test_validate_character_cast_ready_both_fail(tmp_path, monkeypatch):
    from tools.drama_qc import validate_character_cast_ready

    face = tmp_path / "c1_face.png"
    body = tmp_path / "c1.png"
    face.write_bytes(b"x" * 64)
    body.write_bytes(b"y" * 64)
    monkeypatch.setattr("tools.drama_qc._arcface_ready", lambda: True)
    monkeypatch.setattr(
        "tools.drama_qc.identity_enforcement",
        lambda slug="", models=None: "advisory",
    )
    monkeypatch.setattr("tools.drama_qc._arcface_faces", lambda path: ([], "no_face"))
    monkeypatch.setattr(
        "tools.workspace.resolve_safe",
        lambda rel: face if "face" in rel.replace("\\", "/") else body,
    )
    char = {
        "id": "c1",
        "name": "愚公",
        "ref": "dramas/demo/characters/c1.png",
        "ref_face": "dramas/demo/characters/c1_face.png",
    }
    res = validate_character_cast_ready("demo", char)
    assert res["ok"] is True
    assert res["identity_anchor"] == "body"
    assert res["reason"] == "qc_disabled"


def test_validate_character_cast_ready_enforce_body_fail(tmp_path, monkeypatch):
    from tools.drama_qc import validate_character_cast_ready

    face = tmp_path / "c1_face.png"
    body = tmp_path / "c1.png"
    face.write_bytes(b"x" * 64)
    body.write_bytes(b"y" * 64)
    monkeypatch.setattr("tools.drama_qc._arcface_ready", lambda: True)
    monkeypatch.setattr(
        "tools.drama_qc.identity_enforcement",
        lambda slug="", models=None: "enforce",
    )
    monkeypatch.setattr("tools.drama_qc._arcface_faces", lambda path: ([], "no_face"))
    monkeypatch.setattr(
        "tools.workspace.resolve_safe",
        lambda rel: face if "face" in rel.replace("\\", "/") else body,
    )
    char = {
        "id": "c1",
        "name": "愚公",
        "ref": "dramas/demo/characters/c1.png",
        "ref_face": "dramas/demo/characters/c1_face.png",
    }
    res = validate_character_cast_ready("demo", char)
    # enforce 也被总闸关闭：有全身文件仍放行
    assert res["ok"] is True
    assert res["reason"] == "qc_disabled"


def test_identity_scene_retryable_removed():
    import tools.drama_produce as drama_produce

    assert not hasattr(drama_produce, "_identity_scene_retryable")


def _patch_ref_pipeline(monkeypatch, char, *, parallel=True):
    """同步化 parallel_map 并 stub 出定妆管线依赖，便于断言 ensure_character_refs。"""
    monkeypatch.setattr("tools.drama_characters.load_characters", lambda slug: [char])
    monkeypatch.setattr("tools.drama_characters.find_character", lambda cards, cid: char)
    monkeypatch.setattr("tools.drama_characters.ref_exists", lambda slug, rec: False)
    monkeypatch.setattr("tools.drama_characters.ref_rel", lambda slug, cid: f"dramas/{slug}/refs/{cid}.png")
    monkeypatch.setattr("tools.drama_characters.set_ref_locked", lambda slug, cid, locked: char)
    if parallel:
        monkeypatch.setattr(
            "tools.drama_parallel.parallel_map",
            lambda items, worker, max_workers=None: [worker(i) for i in items],
        )
        monkeypatch.setattr("tools.drama_parallel.shot_concurrency", lambda: 2)


def test_ensure_character_refs_raises_on_generation_failure(monkeypatch):
    from tools import drama_produce

    char = {"id": "c1", "name": "悟空", "category": "character", "look": "外形描述", "ref_locked": False}
    _patch_ref_pipeline(monkeypatch, char)

    def boom(slug, cid, *, lock=False, seed=None):
        raise RuntimeError("图像模型不可用")

    monkeypatch.setattr("tools.drama_studio.generate_character_ref", boom)

    with pytest.raises(RuntimeError, match="定妆生成失败"):
        drama_produce.ensure_character_refs("demo")


def test_ensure_character_refs_raises_when_ref_never_validates(monkeypatch, tmp_path):
    from tools import drama_produce

    char = {"id": "c1", "name": "悟空", "category": "character", "look": "外形描述", "ref_locked": False}
    _patch_ref_pipeline(monkeypatch, char)
    monkeypatch.setattr("tools.drama_studio.generate_character_ref", lambda slug, cid, lock=False, seed=None: None)
    monkeypatch.setattr("tools.drama_series.invalidate_character_embedding", lambda slug, cid: None)
    monkeypatch.setattr("tools.drama_characters.ref_face_exists", lambda slug, rec: True)
    monkeypatch.setattr(
        "tools.drama_qc.validate_character_cast_ready",
        lambda slug, rec: {
            "ok": False,
            "reason": "no_face",
            "hint": (
                "角色「悟空」定妆身份校验失败（InsightFace 检脸）。"
                "正脸特写[失败] file=c1_face.png reason=no_face method=no_face faces=0 size=1024x1024 bytes=100；"
                "全身定妆[失败] file=c1.png reason=no_face method=no_face faces=0 size=1024x1024 bytes=100"
            ),
            "detail": (
                "正脸特写[失败] file=c1_face.png reason=no_face method=no_face faces=0 size=1024x1024 bytes=100；"
                "全身定妆[失败] file=c1.png reason=no_face method=no_face faces=0 size=1024x1024 bytes=100"
            ),
        },
    )

    with pytest.raises(RuntimeError, match="缺少可用定妆图"):
        drama_produce.ensure_character_refs("demo")


def test_ensure_character_refs_accepts_body_anchor_when_face_misses(monkeypatch, tmp_path):
    from tools import drama_produce

    char = {
        "id": "c1",
        "name": "愚公",
        "category": "character",
        "look": "外形描述",
        "ref_locked": False,
        "ref": "dramas/demo/characters/c1.png",
        "ref_face": "dramas/demo/characters/c1_face.png",
    }
    _patch_ref_pipeline(monkeypatch, char)
    monkeypatch.setattr("tools.drama_studio.generate_character_ref", lambda slug, cid, lock=False, seed=None: None)
    monkeypatch.setattr("tools.drama_series.invalidate_character_embedding", lambda slug, cid: None)
    monkeypatch.setattr("tools.drama_characters.ref_face_exists", lambda slug, rec: True)
    upserts: list[dict] = []

    def _upsert(slug, patch):
        upserts.append(dict(patch))
        char.update(patch)
        return char

    monkeypatch.setattr("tools.drama_characters.upsert_character", _upsert)
    monkeypatch.setattr(
        "tools.drama_qc.validate_character_cast_ready",
        lambda slug, rec: {
            "ok": True,
            "identity_anchor": "body",
            "reason": "face_undetected_body_ok",
            "hint": "正脸漏检，全身可用",
            "detail": "正脸特写[失败]；全身定妆[通过]",
        },
    )

    out = drama_produce.ensure_character_refs("demo")
    assert out == ["c1"]
    assert any(p.get("identity_anchor") == "body" for p in upserts)
