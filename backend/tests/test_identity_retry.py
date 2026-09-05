"""锁定前定妆校验 + 镜头侧只重抽画面（身份失败重试路由）。"""

from __future__ import annotations

import pytest

from tools.drama_models import default_models
from tools.drama_qc import validate_character_ref


def test_qc_defaults_include_identity_retry_limits():
    qc = default_models()["qc"]
    assert qc["identity_ref_retries"] == 2
    assert qc["identity_scene_retries"] == 2


def test_validate_character_ref_missing_file_not_retryable():
    res = validate_character_ref(None)
    assert res["ok"] is False
    assert res["retryable"] is False
    assert res["reason"] == "missing_ref"


def test_validate_character_ref_no_insightface_not_retryable(tmp_path, monkeypatch):
    png = tmp_path / "ref.png"
    png.write_bytes(b"x" * 64)
    monkeypatch.setattr("tools.drama_qc._arcface_ready", lambda: False)
    res = validate_character_ref(png)
    assert res["ok"] is False
    assert res["retryable"] is False
    assert res["reason"] == "no_insightface"


def test_validate_character_ref_no_face_retryable(tmp_path, monkeypatch):
    png = tmp_path / "ref.png"
    png.write_bytes(b"x" * 64)
    monkeypatch.setattr("tools.drama_qc._arcface_ready", lambda: True)
    monkeypatch.setattr("tools.drama_qc._arcface_embedding", lambda path: (None, "no_face"))
    res = validate_character_ref(png)
    assert res["ok"] is False
    assert res["retryable"] is True
    assert res["reason"] == "no_face"


def test_validate_character_ref_arcface_error_not_retryable(tmp_path, monkeypatch):
    png = tmp_path / "ref.png"
    png.write_bytes(b"x" * 64)
    monkeypatch.setattr("tools.drama_qc._arcface_ready", lambda: True)
    monkeypatch.setattr("tools.drama_qc._arcface_embedding", lambda path: (None, "arcface_error"))
    res = validate_character_ref(png)
    assert res["ok"] is False
    assert res["retryable"] is False
    assert res["reason"] == "arcface_error"


def test_validate_character_ref_ok(tmp_path, monkeypatch):
    png = tmp_path / "ref.png"
    png.write_bytes(b"x" * 64)
    monkeypatch.setattr("tools.drama_qc._arcface_ready", lambda: True)
    monkeypatch.setattr(
        "tools.drama_qc._arcface_embedding", lambda path: ([0.1] * 512, "arcface")
    )
    res = validate_character_ref(png)
    assert res["ok"] is True
    assert res["method"] == "arcface"
    assert res["dims"] == 512


def test_identity_scene_retryable_routing():
    from tools.drama_produce import _identity_scene_retryable

    # 分数低 → 重抽 scene
    assert _identity_scene_retryable({"status": "ok", "pass": False}) is True
    assert _identity_scene_retryable({"status": "ok", "pass": True}) is False
    # 画面缺失 / 画面无人脸 → 重抽 scene（锁定前已保证定妆有脸）
    assert _identity_scene_retryable({"status": "skipped", "reason": "no_scene"}) is True
    assert _identity_scene_retryable({"status": "skipped", "reason": "missing_right"}) is True
    assert _identity_scene_retryable({"status": "skipped", "reason": "no_face"}) is True
    assert _identity_scene_retryable({"status": "skipped", "reason": "no_embedding"}) is True
    # 定妆侧 / 依赖 → 不重试（由锁定前校验/前置闸解决）
    assert _identity_scene_retryable({"status": "skipped", "reason": "no_locked_ref"}) is False
    assert _identity_scene_retryable({"status": "skipped", "reason": "missing_left"}) is False
    assert _identity_scene_retryable({"status": "skipped", "reason": "proxy_identity"}) is False
    assert _identity_scene_retryable({"status": "skipped", "reason": "arcface_error"}) is False
    # n/a 不挡关，也不重试
    assert _identity_scene_retryable({"status": "n/a"}) is False


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


def test_ensure_character_refs_raises_on_generation_failure(monkeypatch):
    from tools import drama_produce

    char = {"id": "c1", "name": "悟空", "category": "character", "look": "外形描述", "ref_locked": False}
    _patch_ref_pipeline(monkeypatch, char)

    def boom(slug, cid, *, lock=False, seed=None):
        raise RuntimeError("图像模型不可用")

    monkeypatch.setattr("tools.drama_studio.generate_character_ref", boom)

    with pytest.raises(RuntimeError, match="定妆生成失败"):
        drama_produce.ensure_character_refs("demo", identity_ref_retries=1)


def test_ensure_character_refs_raises_when_ref_never_validates(monkeypatch, tmp_path):
    from tools import drama_produce

    char = {"id": "c1", "name": "悟空", "category": "character", "look": "外形描述", "ref_locked": False}
    _patch_ref_pipeline(monkeypatch, char)
    monkeypatch.setattr("tools.drama_studio.generate_character_ref", lambda slug, cid, lock=False, seed=None: None)
    monkeypatch.setattr("tools.drama_series.invalidate_character_embedding", lambda slug, cid: None)
    monkeypatch.setattr("tools.workspace.resolve_safe", lambda rel: tmp_path / "ref.png")
    monkeypatch.setattr(
        "tools.drama_qc.validate_character_ref",
        lambda path: {"ok": False, "retryable": True, "reason": "no_face", "hint": "定妆图未检测到可用人脸"},
    )

    with pytest.raises(RuntimeError, match="重生成"):
        drama_produce.ensure_character_refs("demo", identity_ref_retries=1)
