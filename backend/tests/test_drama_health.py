"""S0 honest-layer tests: provider name must match the registered adapter."""

from __future__ import annotations

from tools.drama_models import default_models, provider_health


def test_jimeng_gated_without_env():
    """S1: jimeng adapter exists but needs CONSISTENT_IMAGE_URL → gated (honest)."""
    models = default_models()
    models["image"]["dialogue"]["provider"] = "jimeng"
    health = provider_health(models)
    jimeng = next(
        it for it in health["items"]
        if it["capability"] == "image" and it["written"] == "jimeng"
    )
    assert jimeng["status"] == "gated"
    assert "CONSISTENT_IMAGE_URL" in jimeng["reason"]


def test_jimeng_live_with_env(monkeypatch):
    """S1: with the env URL set, jimeng is live (adapter registered)."""
    from config import config as _cfg

    monkeypatch.setattr(_cfg, "CONSISTENT_IMAGE_URL", "https://img.example.com/consist")
    models = default_models()
    models["image"]["dialogue"]["provider"] = "jimeng"
    health = provider_health(models)
    jimeng = next(
        it for it in health["items"]
        if it["capability"] == "image" and it["written"] == "jimeng"
    )
    assert jimeng["status"] == "live"


def test_volcano_gated_without_tts_url():
    """S3: volcano now has a real HTTP TTS gateway — gated until TTS_API_URL is set."""
    models = default_models()
    models["tts"]["provider"] = "volcano"
    health = provider_health(models)
    tts = next(it for it in health["items"] if it["capability"] == "tts")
    assert tts["written"] == "volcano"
    assert tts["status"] == "gated"
    assert "TTS_API_URL" in tts["reason"]


def test_musetalk_gated_without_lip_url():
    """S3: musetalk has a real http lip adapter — gated until LIP_API_URL is set."""
    models = default_models()
    models["lip"]["provider"] = "musetalk"
    health = provider_health(models)
    lip = next(it for it in health["items"] if it["capability"] == "lip")
    assert lip["written"] == "musetalk"
    assert lip["status"] == "gated"
    assert "LIP_API_URL" in lip["reason"]


def test_latentsync_gated_without_replicate_token():
    models = default_models()
    models["lip"]["provider"] = "latentsync"
    health = provider_health(models)
    lip = next(it for it in health["items"] if it["capability"] == "lip")
    assert lip["written"] == "latentsync"
    assert lip["status"] == "gated"
    assert "REPLICATE_API_TOKEN" in lip["reason"]


def test_local_backends_are_live():
    """name-accurate local backends are live, never flagged as degrades."""
    models = default_models()
    # Turn every node onto a genuine local backend so health reports fully live.
    models["lip"]["provider"] = "mock"
    models["tts"]["provider"] = "edge-tts"
    for kind in models["motion"]:
        models["motion"][kind]["provider"] = "l0"
    health = provider_health(models)
    assert health["healthy"] is True
    assert health["degraded_count"] == 0


def test_default_models_reports_pro_promise_degraded():
    """default models promise latentsync (lip) which gates without REPLICATE token."""
    health = provider_health(default_models())
    degraded = {
        it["written"]
        for it in health["items"]
        if it["status"] in ("alias", "missing", "gated")
    }
    assert "latentsync" in degraded


def test_build_asset_ref_prompt_includes_three_view_look():
    from tools.drama_characters import build_asset_ref_prompt

    prompt = build_asset_ref_prompt({"category": "character", "look": "正面黑长发，侧面高马尾，背面白披风"})
    assert "外形：正面黑长发" in prompt
    assert "只有一个" in prompt
    assert "禁止手持" in prompt


def test_build_asset_ref_prompt_injects_face_anchor():
    from tools.drama_characters import build_asset_ref_prompt

    prompt = build_asset_ref_prompt(
        {
            "category": "character",
            "look": "黑金广袖帝袍，头戴冕旒，面容端正",
            "look_face": "宽额方颐，浓眉入鬓，黑须垂胸",
        }
    )
    assert "人脸锚点" in prompt
    assert "宽额方颐，浓眉入鬓，黑须垂胸" in prompt
    assert "禁止另画一张脸" in prompt


def test_character_ref_prompt_single_pose():
    from tools.drama_characters import build_asset_ref_prompt, character_ref_negative_prompt

    prompt = build_asset_ref_prompt({"category": "character", "look": "测试角色", "ref_size": 1024})
    assert "只有一个" in prompt
    assert "多视角" in prompt or "三视图" in prompt
    assert "禁止手持" in prompt
    tall = build_asset_ref_prompt({"category": "character", "look": "测试角色", "ref_size": 1440})
    assert "9:16" in tall
    assert "三视图" in tall
    neg = character_ref_negative_prompt()
    assert "多视角" in neg
    assert "锄头" in neg


def test_sanitize_character_look_strips_props():
    from tools.drama_characters import sanitize_character_look_for_portrait

    look = sanitize_character_look_for_portrait("青年男子，短发，手持锄头开山，粗布短打")
    assert "锄头" not in look
    assert "青年男子" in look


def test_face_ref_prompt_from_body_locks_identity():
    from tools.drama_characters import build_face_ref_prompt

    prompt = build_face_ref_prompt(
        {"name": "愚公长子", "look": "青年男子，短发，粗布短打", "gender": "male"},
        from_body_ref=True,
    )
    assert "同一人" in prompt
    assert "男性" in prompt
    assert "禁止换成" in prompt

def test_normalize_ref_image_route():
    from tools.drama_characters import REF_IMAGE_OPTIONS, character_ref_shot, normalize_ref_image_route

    p, m = normalize_ref_image_route("wanx", "qwen-image-plus")
    assert p == "wanx" and m == "qwen-image-plus"
    p, m = normalize_ref_image_route("kling-image", "")
    assert p == "kling-image"
    assert m == REF_IMAGE_OPTIONS[0]["model"]
    p, m = normalize_ref_image_route("pollinations", "flux")
    assert p == "kling-image"
    assert m == REF_IMAGE_OPTIONS[0]["model"]
    shot = character_ref_shot({"ref_image_provider": "kling-image", "ref_image_model": REF_IMAGE_OPTIONS[0]["model"]})
    assert shot["kind"] == "character_ref"
    assert shot["ref_image_provider"] == "kling-image"


def test_ref_canvas_size_by_category():
    from tools.drama_characters import normalize_ref_size, ref_canvas_size

    assert normalize_ref_size(1980, "character") == 1440  # legacy → 竖屏全身默认
    assert normalize_ref_size(640, "scene") == 1440
    assert normalize_ref_size(1024, "scene") == 1440  # 旧角色边长在场景档无效
    assert normalize_ref_size(1536, "character") == 1536
    assert normalize_ref_size(1024, "prop") == 2048  # 旧道具方图 → 现默认 2048
    assert normalize_ref_size(1080, "prop") == 2048  # 旧竖屏键已移除
    assert ref_canvas_size({"category": "character", "ref_size": 1024}) == (1024, 1024)
    assert ref_canvas_size({"category": "character", "ref_size": 2048}) == (2048, 2048)
    assert ref_canvas_size({"category": "character", "ref_size": 1440}) == (1440, 2560)
    assert ref_canvas_size({"category": "character", "ref_size": 1980}) == (1440, 2560)
    assert ref_canvas_size({"category": "prop", "ref_size": 2048}) == (2048, 2048)
    assert ref_canvas_size({"category": "prop", "ref_size": 1440}) == (1440, 2560)
    assert ref_canvas_size({"category": "prop", "ref_size": 1024}) == (2048, 2048)
    assert ref_canvas_size({"category": "scene", "ref_size": 1440}) == (1440, 2560)
    assert ref_canvas_size({"category": "scene", "ref_size": 1600}) == (1600, 2848)
    assert ref_canvas_size({"category": "scene", "ref_size": 1980}) == (1440, 2560)


def test_face_ref_prompt_uses_look_face():
    from tools.drama_characters import build_face_ref_prompt

    prompt = build_face_ref_prompt(
        {
            "name": "林晚",
            "look": "青年女子，黑长直，校服",
            "look_face": "杏眼浅棕瞳，左耳月牙耳坠",
            "gender": "female",
        }
    )
    assert "大头照" in prompt or "人脸特写" in prompt
    assert "杏眼浅棕瞳" in prompt
    assert "少带颈部" in prompt or "少带" in prompt
    assert "三视图" in prompt
    assert "人脸占比要大" in prompt


def test_full_body_prompt_full_frame_and_face_anchor():
    from tools.drama_characters import build_asset_ref_prompt

    prompt = build_asset_ref_prompt(
        {
            "category": "character",
            "look": "黑金广袖帝袍，头戴冕旒",
            "look_face": "宽额方颐，浓眉入鬓，黑须垂胸",
        }
    )
    assert "从头到脚完整入镜" in prompt
    assert "人脸区域清晰可辨" in prompt
    assert "人脸锚点" in prompt


def test_normalize_character_prop_scene_have_no_gender_voice(tmp_path, monkeypatch):
    from tools import workspace as ws
    from tools.drama_characters import normalize_character

    monkeypatch.setattr(ws, "workspace_root", lambda: tmp_path)
    prop = normalize_character(
        "demo",
        {
            "id": "chutou",
            "name": "旧锄头",
            "category": "prop",
            "gender": "male",
            "voice": "zh_male_m191_uranus_bigtts",
        },
    )
    assert prop["gender"] == ""
    assert prop["voice"] == ""
    scene = normalize_character(
        "demo",
        {
            "id": "shan",
            "name": "大山",
            "category": "scene",
            "gender": "female",
            "voice": "zh_female_vv_uranus_bigtts",
        },
    )
    assert scene["gender"] == ""
    assert scene["voice"] == ""


def test_normalize_character_male_gets_male_voice(tmp_path, monkeypatch):
    from tools import workspace as ws
    from tools.drama_characters import normalize_character, voice_gender

    monkeypatch.setattr(ws, "workspace_root", lambda: tmp_path)
    rec = normalize_character(
        "demo",
        {"id": "yugong", "name": "愚公", "category": "character", "gender": "male", "voice": "yugong_voice"},
    )
    assert rec["gender"] == "male"
    assert voice_gender(rec["voice"]) == "male"


def test_normalize_character_male_rejects_female_voice(tmp_path, monkeypatch):
    from tools import workspace as ws
    from tools.drama_characters import normalize_character, voice_gender

    monkeypatch.setattr(ws, "workspace_root", lambda: tmp_path)
    rec = normalize_character(
        "demo",
        {"id": "xiaoyu", "name": "小禹", "category": "character", "gender": "male", "voice": "zh-CN-XiaoyiNeural"},
    )
    assert rec["gender"] == "male"
    assert voice_gender(rec["voice"]) == "male"


def test_prop_ref_prompt_square_vs_portrait():
    from tools.drama_characters import build_asset_ref_prompt

    square = build_asset_ref_prompt({"category": "prop", "look": "玉瓶", "ref_size": 1024})
    assert "正方形" in square
    assert "道具设定图" in square
    tall = build_asset_ref_prompt({"category": "prop", "look": "玉瓶", "ref_size": 1440})
    assert "9:16" in tall
    assert "道具设定图" in tall


def test_trim_letterbox_reads_pixels_with_pillow():
    from PIL import Image

    from tools.drama_video import _prepare_frame, _trim_letterbox

    img = Image.new("RGB", (64, 64), (255, 255, 255))
    # center content so uniform border trim does not collapse the canvas
    for x in range(20, 44):
        for y in range(20, 44):
            img.putpixel((x, y), (120, 80, 200))
    trimmed = _trim_letterbox(img)
    assert trimmed.size[0] >= 20 and trimmed.size[1] >= 20
    out = _prepare_frame(img, 32, 32)
    assert out.size == (32, 32)


def test_qwen_image_plus_size_maps_to_fixed_resolutions():
    from tools.providers.image_providers import _dashscope_gen_size, _kling_aspect_ratio

    assert _dashscope_gen_size(1024, 1024, model="qwen-image-plus") == "1328*1328"
    assert _dashscope_gen_size(1024, 1792, model="qwen-image-plus") == "928*1664"
    assert _kling_aspect_ratio(1024, 1024) == "1:1"
    assert _kling_aspect_ratio(720, 1280) == "9:16"


def test_locked_refs_for_shot_returns_workspace_relative_paths(tmp_path, monkeypatch):
    from tools.drama_characters import ref_rel, save_characters
    from tools.drama_qc import locked_refs_for_shot
    from tools.workspace import resolve_safe, workspace_root

    slug = "ref_path_test"
    root = workspace_root()
    monkeypatch.setattr("config.config.WORKSPACE_DIR", str(root))
    cid = "hero"
    rel = ref_rel(slug, cid)
    dest = resolve_safe(rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    save_characters(slug, [{"id": cid, "name": "Hero", "ref": rel, "ref_locked": True, "category": "character"}])
    shot = {"n": 1, "角色": ["Hero"]}
    refs = locked_refs_for_shot(slug, shot)
    assert refs == [rel]
    assert not refs[0].startswith(str(root))


def test_image_provider_chain_prefers_kling_when_refs_present():
    from tools.drama_video import _image_provider_chain

    chain = _image_provider_chain("flux", {"kind": "dialogue"}, refs=("dramas/s/c.png",))
    assert chain[0] in ("kling-image", "kling")
    assert "flux" in chain
    assert "pollinations" not in chain


def test_image_cache_key_is_content_addressed():
    """S1: cache key is deterministic and sensitive to prompt/seed/refs."""
    from tools.providers.image_providers import _cache_key

    a = _cache_key("wukong faces the sky", seed=1, width=1620, height=2880, model="char-consistent")
    b = _cache_key("wukong faces the sky", seed=1, width=1620, height=2880, model="char-consistent")
    c = _cache_key("wukong faces the sky", seed=2, width=1620, height=2880, model="char-consistent")
    d = _cache_key("wukong faces the sky", seed=1, width=1620, height=2880, model="char-consistent", refs=("dramas/s/shots/p.png",))
    assert a == b
    assert a != c
    assert a != d


def test_kling_gated_without_i2v_url():
    """S2: kling adapter exists but needs I2V_API_URL → gated (honest)."""
    models = default_models()
    models["motion"]["action"]["provider"] = "kling"
    health = provider_health(models)
    kling = next(
        it for it in health["items"]
        if it["capability"] == "i2v" and it["written"] == "kling"
    )
    assert kling["status"] == "gated"
    assert "I2V_API_URL" in kling["reason"]


def test_kling_live_with_i2v_url(monkeypatch):
    """S2: with I2V_API_URL set, kling is live via the gateway adapter."""
    from config import config as _cfg

    monkeypatch.setattr(_cfg, "I2V_API_URL", "https://i2v.example.com/submit")
    models = default_models()
    models["motion"]["action"]["provider"] = "kling"
    health = provider_health(models)
    kling = next(
        it for it in health["items"]
        if it["capability"] == "i2v" and it["written"] == "kling"
    )
    assert kling["status"] == "live"


def test_pollinations_i2v_never_claims_ai():
    """S2: pollinations is an image service, not I2V — honest fallback to still."""
    from pathlib import Path

    from tools.drama_i2v import _provider_pollinations

    ok = _provider_pollinations(Path("scene.png"), Path("out.mp4"), {"画面": "x"}, 2.0)
    assert ok is False


def test_rate_limiter_disabled_when_rpm_zero():
    """S4: rpm=0 means unlimited; acquire() returns immediately."""
    from tools.drama_retry import RateLimiter

    limiter = RateLimiter(rpm=0)
    import time

    start = time.monotonic()
    for _ in range(10):
        limiter.acquire()
    assert (time.monotonic() - start) < 0.5


def test_rate_limiter_enforces_rpm():
    """S4: rpm=1 allows only one acquire per 60s window."""
    from tools.drama_retry import RateLimiter

    limiter = RateLimiter(rpm=1)
    limiter.acquire()  # first is immediate
    assert limiter._hits  # one hit recorded
    assert len(limiter._hits) == 1
