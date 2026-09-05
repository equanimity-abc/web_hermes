"""Seedance I2V：duration 下限与首帧 payload。"""

from __future__ import annotations

from PIL import Image


def test_seedance_duration_floors_pipeline_default():
    from tools.providers.ark_providers import _seedance_duration

    # 管线默认 i2v_seconds=2.5 → round 2；旧逻辑会 400。
    assert _seedance_duration(2.5) == 4
    assert _seedance_duration(2) == 4
    assert _seedance_duration(3.2) == 4
    assert _seedance_duration(4) == 4
    assert _seedance_duration(5) == 5
    assert _seedance_duration(20) == 12
    assert _seedance_duration(None) == 5


def test_ark_i2v_payload_uses_first_frame_and_min_duration(tmp_path, monkeypatch):
    from tools.providers import ark_providers as ap
    import tools.drama_i2v as di2v

    scene = tmp_path / "scene.png"
    Image.new("RGB", (540, 960), (40, 40, 80)).save(scene)
    dest = tmp_path / "out.mp4"
    captured: dict = {}

    class _Resp:
        status_code = 200
        text = "{}"

        def raise_for_status(self):
            return None

        def json(self):
            return {"id": "task-1"}

    class _Poll:
        status_code = 200
        text = "{}"

        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "failed", "error": "stop_after_submit"}

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["body"] = json
            return _Resp()

        def get(self, url, headers=None):
            return _Poll()

    monkeypatch.setattr(ap, "_ark_key", lambda: "test-key")
    monkeypatch.setattr(ap.httpx, "Client", _Client)
    monkeypatch.setattr(di2v, "_motion_prompt", lambda shot: "idle")

    shot: dict = {}
    assert ap._ark_i2v(scene, dest, shot, 2.5) == "none"
    body = captured["body"]
    assert body["duration"] == 4
    assert body["ratio"] == "adaptive"
    assert body["generate_audio"] is False
    assert "watermark" not in body
    img = body["content"][1]
    assert img["role"] == "first_frame"
    assert img["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert "i2v_error" in shot


def test_ark_i2v_keeps_api_error_body(tmp_path, monkeypatch):
    from tools.providers import ark_providers as ap
    import tools.drama_i2v as di2v

    scene = tmp_path / "scene.png"
    Image.new("RGB", (540, 960), (10, 10, 10)).save(scene)
    dest = tmp_path / "out.mp4"

    class _Resp:
        status_code = 400
        text = '{"error":{"code":"InvalidParameter","message":"ratio must be adaptive"}}'

        def json(self):
            return {"error": {"code": "InvalidParameter", "message": "ratio must be adaptive"}}

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):
            return _Resp()

    monkeypatch.setattr(ap, "_ark_key", lambda: "test-key")
    monkeypatch.setattr(ap.httpx, "Client", _Client)
    monkeypatch.setattr(di2v, "_motion_prompt", lambda shot: "idle")

    shot: dict = {}
    assert ap._ark_i2v(scene, dest, shot, 4) == "none"
    assert "InvalidParameter" in shot.get("i2v_error", "")
    assert "adaptive" in shot.get("i2v_error", "")
