"""Seedance I2V：duration 下限与首帧 payload。"""

from __future__ import annotations

from pathlib import Path

from PIL import Image


def test_resolve_seedance_model_aliases():
    from tools.providers import ark_providers as ap

    assert ap._resolve_seedance_model("doubao-seedance-2.0") == (
        "doubao-seedance-2-0-260128"
    )
    assert ap._resolve_seedance_model("doubao-seedance-2.0-fast") == (
        "doubao-seedance-2-0-fast-260128"
    )
    assert ap._resolve_seedance_model("doubao-seedance-2-0-260128") == (
        "doubao-seedance-2-0-260128"
    )
    assert ap._resolve_seedance_model("doubao-seedance-1.5-pro") == (
        "doubao-seedance-1-5-pro-251215"
    )


def test_resolve_seedance_model_agent_plan_keeps_2_0(monkeypatch):
    """Large/Max 可用 2.0；解析层不得因 /api/plan/ 强行降级。"""
    from tools.providers import ark_providers as ap

    monkeypatch.setattr(
        ap, "_ark_base", lambda: "https://ark.cn-beijing.volces.com/api/plan/v3"
    )
    assert ap._resolve_seedance_model("doubao-seedance-2-0-260128") == (
        "doubao-seedance-2-0-260128"
    )
    assert ap._resolve_seedance_model("doubao-seedance-2.0") == (
        "doubao-seedance-2-0-260128"
    )


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
    monkeypatch.setattr(ap.config, "ARK_I2V_REFERENCE_ONLY", "0")  # 走图生视频首帧路径
    monkeypatch.setattr(ap.httpx, "Client", _Client)
    monkeypatch.setattr(di2v, "_motion_prompt", lambda shot: "idle")

    shot: dict = {}
    assert ap._ark_i2v(scene, dest, shot, 2.5) == "none"
    body = captured["body"]
    assert body["duration"] == 4
    assert body["ratio"] == "adaptive"
    assert body["generate_audio"] is True
    assert "watermark" not in body
    img = body["content"][1]
    assert img["role"] == "first_frame"
    assert img["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert not any(c.get("role") == "reference_audio" for c in body["content"])
    assert not any(c.get("role") == "reference_image" for c in body["content"])
    assert "i2v_error" in shot
    assert shot.get("i2v_generate_audio") is True
    assert shot.get("i2v_audio_ref") is False


def test_ark_i2v_attaches_face_body_reference_images(tmp_path, monkeypatch):
    """Ark：首帧后挂大头照+全身照 reference_image，prompt 认领 @图片2/3。"""
    from tools.providers import ark_providers as ap
    import tools.drama_i2v as di2v

    scene = tmp_path / "scene.png"
    face = tmp_path / "hero_face.png"
    body = tmp_path / "hero.png"
    Image.new("RGB", (540, 960), (40, 40, 80)).save(scene)
    Image.new("RGB", (512, 512), (200, 100, 80)).save(face)
    Image.new("RGB", (540, 960), (80, 120, 160)).save(body)
    dest = tmp_path / "out.mp4"
    captured: dict = {}

    class _Resp:
        status_code = 200
        text = "{}"

        def json(self):
            return {"id": "task-1"}

    class _Poll:
        status_code = 200
        text = "{}"

        def json(self):
            return {"status": "failed", "error": "stop"}

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):
            captured["body"] = json
            return _Resp()

        def get(self, url, headers=None):
            return _Poll()

    monkeypatch.setattr(ap, "_ark_key", lambda: "test-key")
    monkeypatch.setattr(ap.config, "ARK_I2V_REFERENCE_ONLY", "0")  # 旧路径：首帧 + 大头/全身 reference_image
    monkeypatch.setattr(ap.httpx, "Client", _Client)
    monkeypatch.setattr(
        di2v,
        "_motion_prompt",
        lambda shot: (
            f"idle face={shot.get('_seedance_face_image_index')} "
            f"body={shot.get('_seedance_body_image_index')}"
        ),
    )
    monkeypatch.setattr(
        ap,
        "_local_ref_to_data_uri",
        lambda rel, max_side=1536: f"data:image/jpeg;base64,{Path(rel).name}",
    )

    face_rel = str(face).replace("\\", "/")
    body_rel = str(body).replace("\\", "/")
    shot: dict = {"_seedance_identity_refs": [face_rel, body_rel]}
    assert ap._ark_i2v(scene, dest, shot, 4) == "none"
    content = captured["body"]["content"]
    roles = [c.get("role") for c in content if isinstance(c, dict)]
    assert roles.count("first_frame") == 1
    assert roles.count("reference_image") == 2
    assert shot.get("_seedance_face_image_index") == 2
    assert shot.get("_seedance_body_image_index") == 3
    assert shot.get("i2v_identity_ref_count") == 2
    assert "face=2" in content[0]["text"] and "body=3" in content[0]["text"]


def test_ark_i2v_reference_only_drops_first_frame(tmp_path, monkeypatch):
    """方案 A：不传首帧（含人脸图生图分镜），只用大头照 reference_image 锁脸。"""
    from tools.providers import ark_providers as ap
    import tools.drama_i2v as di2v

    face = tmp_path / "hero_face.png"
    Image.new("RGB", (512, 512), (200, 100, 80)).save(face)
    dest = tmp_path / "out.mp4"
    captured: dict = {}

    class _Resp:
        status_code = 200
        text = "{}"

        def json(self):
            return {"id": "task-1"}

    class _Poll:
        status_code = 200
        text = "{}"

        def json(self):
            return {"status": "failed", "error": "stop"}

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):
            captured["body"] = json
            return _Resp()

        def get(self, url, headers=None):
            return _Poll()

    monkeypatch.setattr(ap, "_ark_key", lambda: "test-key")
    monkeypatch.setattr(ap.config, "ARK_I2V_REFERENCE_ONLY", "1")  # 方案 A
    monkeypatch.setattr(ap.httpx, "Client", _Client)
    monkeypatch.setattr(
        di2v,
        "_motion_prompt",
        lambda shot: (
            f"idle face={shot.get('_seedance_face_image_index')} "
            f"body={shot.get('_seedance_body_image_index')}"
        ),
    )
    monkeypatch.setattr(
        ap,
        "_local_ref_to_data_uri",
        lambda rel, max_side=1536: f"data:image/jpeg;base64,{Path(rel).name}",
    )

    face_rel = str(face).replace("\\", "/")
    shot: dict = {"_seedance_identity_refs": [face_rel]}
    assert ap._ark_i2v(tmp_path / "scene.png", dest, shot, 4) == "none"
    content = captured["body"]["content"]
    roles = [c.get("role") for c in content if isinstance(c, dict)]
    assert roles.count("first_frame") == 0
    assert roles.count("reference_image") == 1
    assert shot.get("_seedance_face_image_index") == 1
    assert shot.get("_seedance_body_image_index") == 0
    assert shot.get("_seedance_reference_only") is True
    assert shot.get("i2v_identity_ref_count") == 1
    assert "face=1" in content[0]["text"] and "body=0" in content[0]["text"]


def test_ark_i2v_marks_safety_retry_on_sensitive_poll(tmp_path, monkeypatch):
    """输出侧内容安全（疑似真人）→ 标记 _safety_retry_needed，供上层降级方案 A 重试。"""
    from tools.providers import ark_providers as ap
    import tools.drama_i2v as di2v

    scene = tmp_path / "scene.png"
    face = tmp_path / "hero_face.png"
    Image.new("RGB", (540, 960), (40, 40, 80)).save(scene)
    Image.new("RGB", (512, 512), (200, 100, 80)).save(face)
    dest = tmp_path / "out.mp4"

    class _Resp:
        status_code = 200
        text = "{}"

        def json(self):
            return {"id": "task-1"}

    class _Poll:
        status_code = 200
        text = "{}"

        def json(self):
            return {"status": "failed", "error": "OutputVideoSensitiveContentDetected: blocked"}

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):
            return _Resp()

        def get(self, url, headers=None):
            return _Poll()

    monkeypatch.setattr(ap, "_ark_key", lambda: "test-key")
    monkeypatch.setattr(ap.config, "ARK_I2V_REFERENCE_ONLY", "0")  # 原流程
    monkeypatch.setattr(ap.httpx, "Client", _Client)
    monkeypatch.setattr(di2v, "_motion_prompt", lambda shot: "idle")
    monkeypatch.setattr(
        ap,
        "_local_ref_to_data_uri",
        lambda rel, max_side=1536: f"data:image/jpeg;base64,{Path(rel).name}",
    )

    face_rel = str(face).replace("\\", "/")
    shot: dict = {"_seedance_identity_refs": [face_rel]}
    assert ap._ark_i2v(scene, dest, shot, 4) == "none"
    assert shot.get("_safety_retry_needed") is True
    assert shot.get("_force_reference_only") is not True


def test_format_ark_http_error_429_quota():
    from tools.providers import ark_providers as ap

    msg = ap.format_ark_http_error(429, '{"error":{"code":"QuotaExceeded","message":"quota"}}')
    assert "429" in msg and "配额" in msg


def test_ark_i2v_429_quota_fails_fast_with_clear_error(tmp_path, monkeypatch):
    """429 配额硬满：不重试，快速失败并报清晰错误（避免拖延「加速收尾」连累其它镜）。"""
    from tools.providers import ark_providers as ap
    import tools.drama_i2v as di2v

    scene = tmp_path / "scene.png"
    Image.new("RGB", (540, 960), (40, 40, 80)).save(scene)
    dest = tmp_path / "out.mp4"
    posts = {"n": 0}

    class _Resp429:
        status_code = 429
        text = '{"error":{"code":"QuotaExceeded","message":"quota","type":"TooManyRequests"}}'

        def json(self):
            return {"error": {"code": "QuotaExceeded"}}

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):
            posts["n"] += 1
            return _Resp429()

        def get(self, url, headers=None):
            return _Resp429()

    monkeypatch.setattr(ap, "_ark_key", lambda: "test-key")
    monkeypatch.setattr(ap.config, "ARK_I2V_REFERENCE_ONLY", "0")
    monkeypatch.setattr(ap.httpx, "Client", _Client)
    monkeypatch.setattr(di2v, "_motion_prompt", lambda shot: "idle")

    shot: dict = {}
    assert ap._ark_i2v(scene, dest, shot, 4) == "none"
    assert posts["n"] == 1  # 不再退避重试，快速失败
    assert "配额" in shot.get("i2v_error", "")


def test_ark_i2v_attaches_tts_as_reference_audio(tmp_path, monkeypatch):
    """手动配音：TTS 作为 Seedance reference_audio，generate_audio=False。"""
    from tools.providers import ark_providers as ap
    import tools.drama_i2v as di2v

    scene = tmp_path / "scene.png"
    Image.new("RGB", (540, 960), (40, 40, 80)).save(scene)
    voice = tmp_path / "voice.mp3"
    # Minimal valid-sized mp3-ish blob (not decoded by Seedance in this unit test)
    voice.write_bytes(b"ID3" + b"\x00" * 200)
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
            captured["body"] = json
            return _Resp()

        def get(self, url, headers=None):
            return _Poll()

    monkeypatch.setattr(ap, "_ark_key", lambda: "test-key")
    monkeypatch.setattr(ap.config, "ARK_I2V_REFERENCE_ONLY", "0")  # 首帧 + TTS reference_audio 路径
    monkeypatch.setattr(ap.httpx, "Client", _Client)
    monkeypatch.setattr(di2v, "_motion_prompt", lambda shot: "idle talk")
    monkeypatch.setattr(ap, "_probe_voice_seconds", lambda path: 4.2)
    monkeypatch.setattr(
        ap,
        "_shot_voice_path",
        lambda shot: voice if isinstance(shot, dict) else None,
    )
    monkeypatch.setattr(ap, "_seedance_want_ref_audio", lambda shot: True)

    shot: dict = {"对白": "你好", "assets": {"voice": "voice.mp3"}, "manual_voice": True}
    assert ap._ark_i2v(scene, dest, shot, 3.0) == "none"
    body = captured["body"]
    assert body["generate_audio"] is False
    assert body["duration"] == 4
    roles = [c.get("role") for c in body["content"] if isinstance(c, dict)]
    assert "first_frame" in roles
    assert "reference_audio" in roles
    audio = next(c for c in body["content"] if c.get("role") == "reference_audio")
    assert audio["type"] == "audio_url"
    assert audio["audio_url"]["url"].startswith("data:audio/mpeg;base64,")
    assert "口型" in body["content"][0]["text"]
    assert shot.get("i2v_audio_ref") is True
    assert shot.get("i2v_generate_audio") is False
    assert shot.get("i2v_audio_ref") is True


def test_ark_i2v_marks_seedance_lip_on_success(tmp_path, monkeypatch):
    from tools.providers import ark_providers as ap
    import tools.drama_i2v as di2v

    scene = tmp_path / "scene.png"
    Image.new("RGB", (540, 960), (10, 10, 10)).save(scene)
    voice = tmp_path / "voice.mp3"
    voice.write_bytes(b"ID3" + b"\x00" * 200)
    dest = tmp_path / "out.mp4"
    video_bytes = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64

    class _Resp:
        status_code = 200
        text = "{}"

        def raise_for_status(self):
            return None

        def json(self):
            return {"id": "task-ok"}

    class _Poll:
        status_code = 200
        text = "{}"

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "status": "succeeded",
                "content": {"video_url": "https://example.com/v.mp4"},
            }

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):
            return _Resp()

        def get(self, url, headers=None):
            return _Poll()

    def _fake_download(url, path):
        Path(path).write_bytes(video_bytes)
        return True

    monkeypatch.setattr(ap, "_ark_key", lambda: "test-key")
    monkeypatch.setattr(ap.httpx, "Client", _Client)
    monkeypatch.setattr(di2v, "_motion_prompt", lambda shot: "talk")
    monkeypatch.setattr(ap, "_download", _fake_download)
    monkeypatch.setattr(ap, "_probe_voice_seconds", lambda path: 5.0)
    monkeypatch.setattr(ap, "_shot_voice_path", lambda shot: voice)
    monkeypatch.setattr(ap, "_seedance_want_ref_audio", lambda shot: True)

    shot: dict = {"对白": "在吗", "assets": {"voice": "voice.mp3"}}
    assert ap._ark_i2v(scene, dest, shot, 5) == "ai"
    assert shot.get("seedance_lip") is True
    assert shot.get("i2v_audio_ref") is True
    assert dest.is_file()


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


def test_generate_shot_lip_soft_skips_when_seedance_lip(tmp_path, monkeypatch):
    """Seedance 已口型时跳过 PixVerse，直接复制 motion → lip。"""
    from tools import drama_lip as dl

    motion = tmp_path / "motion.mp4"
    motion.write_bytes(b"m" * 2000)
    voice = tmp_path / "voice.mp3"
    voice.write_bytes(b"v" * 500)
    lip_dest = tmp_path / "lip.mp4"

    shot = {
        "n": 1,
        "seedance_lip": True,
        "对白": "你好",
        "assets": {
            "motion": str(motion),
            "voice": str(voice),
            "scene": str(tmp_path / "scene.png"),
        },
    }

    monkeypatch.setattr(
        dl,
        "lip_eligible",
        lambda shot, models=None: {"ok": True, "reason": ""},
    )
    monkeypatch.setattr(
        "tools.drama_models.models_with_overrides",
        lambda *a, **k: {"lip": {"provider": "pixverse"}},
    )
    monkeypatch.setattr(dl, "lip_rel", lambda slug, ep, n: str(lip_dest))
    monkeypatch.setattr(dl, "resolve_safe", lambda p: __import__("pathlib").Path(p))
    monkeypatch.setattr(
        "tools.drama_video._probe_duration",
        lambda path: 3.5,
    )

    called = {"lip": False}

    def _no_pixverse(*a, **k):
        called["lip"] = True
        return "pixverse"

    monkeypatch.setattr(dl, "try_generate_lip", _no_pixverse)

    info = dl.generate_shot_lip("demo", 1, shot)
    assert info["lip_source"] == "seedance"
    assert shot["lip_source"] == "seedance"
    assert called["lip"] is False
    assert lip_dest.is_file()
    assert lip_dest.read_bytes() == motion.read_bytes()
