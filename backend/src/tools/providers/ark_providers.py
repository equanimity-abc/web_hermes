"""火山方舟 Ark adapters — Seedream 生图 / Seedance 视频 / Seed Audio 配音。"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import httpx

from config import config
from tools.providers.registry import register

log = logging.getLogger("drama.ark")


def _ark_key() -> str:
    return str(getattr(config, "ARK_API_KEY", "") or "").strip()


def _ark_base() -> str:
    return str(
        getattr(config, "ARK_BASE_URL", "") or "https://ark.cn-beijing.volces.com/api/v3"
    ).rstrip("/")


def _is_agent_plan() -> bool:
    """Agent Plan 使用 /api/plan/v3；与按量 /api/v3 权益不同。"""
    return "/api/plan/" in _ark_base().lower()


def _resolve_seedream_model(raw: str | None = None) -> str:
    """Normalize Seedream IDs → 官方 dated API model ID（默认 Pro）。"""
    model = str(
        raw or getattr(config, "ARK_IMAGE_MODEL", "") or "doubao-seedream-5-0-pro-260628"
    ).strip()
    aliases = {
        "doubao-seedream-5.0-lite": "doubao-seedream-5-0-pro-260628",
        "doubao-seedream-5.0": "doubao-seedream-5-0-pro-260628",
        "seedream-5.0": "doubao-seedream-5-0-pro-260628",
        "doubao-seedream-5-0": "doubao-seedream-5-0-pro-260628",
        "doubao-seedream-5-0-260128": "doubao-seedream-5-0-pro-260628",
        "doubao-seedream-5-0-lite-260128": "doubao-seedream-5-0-pro-260628",
        "doubao-seedream-5.0-pro": "doubao-seedream-5-0-pro-260628",
        "doubao-seedream-5-0-pro": "doubao-seedream-5-0-pro-260628",
        "doubao-seedream-5-0-pro-260628": "doubao-seedream-5-0-pro-260628",
    }
    return aliases.get(model, model) or "doubao-seedream-5-0-pro-260628"


def resolve_ark_text_model(raw: str | None = None) -> str:
    """Normalize chat model for Ark. Agent Plan 不含 Seed Character。"""
    model = str(
        raw or getattr(config, "ARK_TEXT_MODEL", "") or "glm-5-2-260617"
    ).strip()
    aliases = {
        "doubao-seed-2.0-lite": "doubao-seed-2-0-lite-260215",
        "doubao-seed-2-0-lite": "doubao-seed-2-0-lite-260215",
        "doubao-seed-2.0-pro": "doubao-seed-2-0-pro-260215",
        "doubao-seed-2-0-pro": "doubao-seed-2-0-pro-260215",
        "doubao-seed-2.0-mini": "doubao-seed-2-0-mini-260215",
        "doubao-seed-2-0-mini": "doubao-seed-2-0-mini-260215",
        "glm-5.2": "glm-5-2-260617",
        "glm-5-2": "glm-5-2-260617",
    }
    model = aliases.get(model, model)
    if not _is_agent_plan():
        return model or "doubao-seed-character-260628"
    # Agent Plan 文本：Seed Character / 旧角色模型不可用
    low = model.lower()
    if "seed-character" in low or "character-250" in low or "character-260" in low:
        alt = str(getattr(config, "ARK_TEXT_MODEL_ALT", "") or "").strip() or "glm-5-2-260617"
        alt = aliases.get(alt, alt)
        log.warning(
            "Agent Plan 不支持文本模型 %s → 改用 %s（可在 .env 设 ARK_TEXT_MODEL）",
            model,
            alt,
        )
        return alt
    return model or "glm-5-2-260617"


def _resolve_seedance_model(raw: str | None = None) -> str:
    """Normalize Seedance marketing names → official dated API model IDs.

    Tier note (Agent Plan): Medium 不含 Seedance 2.x；Large/Max 可用 2.5 / 2.0。
    不在此按套餐降级——由 ``ARK_VIDEO_MODEL`` 显式配置。
    """
    model = str(
        raw or getattr(config, "ARK_VIDEO_MODEL", "") or "doubao-seedance-2-5-260628"
    ).strip()
    aliases = {
        "doubao-seedance-2.5": "doubao-seedance-2-5-260628",
        "doubao-seedance-2-5": "doubao-seedance-2-5-260628",
        "seedance-2.5": "doubao-seedance-2-5-260628",
        "doubao-seedance-2.0": "doubao-seedance-2-0-260128",
        "doubao-seedance-2-0": "doubao-seedance-2-0-260128",
        "seedance-2.0": "doubao-seedance-2-0-260128",
        "doubao-seedance-2.0-fast": "doubao-seedance-2-0-fast-260128",
        "doubao-seedance-2-0-fast": "doubao-seedance-2-0-fast-260128",
        "seedance-2.0-fast": "doubao-seedance-2-0-fast-260128",
        "doubao-seedance-1.5-pro": "doubao-seedance-1-5-pro-251215",
        "doubao-seedance-1-5-pro": "doubao-seedance-1-5-pro-251215",
        "seedance-1.5-pro": "doubao-seedance-1-5-pro-251215",
    }
    return aliases.get(model, model) or "doubao-seedance-2-5-260628"


def format_ark_http_error(status: int, body: str, *, model: str = "") -> str:
    """Human-readable Ark HTTP error; specially handle UnsupportedModel on Agent Plan."""
    detail = str(body or "")[:400]
    if "UnsupportedModel" in detail or "does not support the agent plan" in detail.lower():
        hint = (
            "当前 ARK_BASE_URL 是 Agent Plan（/api/plan/v3），该模型不在套餐内。"
            "文本请用 glm-5-2-260617 或 doubao-seed-2-0-lite-260215；"
            "出图请用 doubao-seedream-5-0-pro-260628；"
            "视频 Seedance 2.5 需 Large/Max，Medium 请改 doubao-seedance-1-5-pro-251215。"
        )
        if model:
            return f"模型 {model} 不支持 Agent Plan。{hint} 原始：{detail[:180]}"
        return f"模型不支持 Agent Plan。{hint} 原始：{detail[:180]}"
    return f"HTTP {status}: {detail[:240]}"


def _ark_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_ark_key()}",
        "Content-Type": "application/json",
        "User-Agent": "my-tiktok-video-agent/1.0",
    }


def _download(url: str, dest: Path) -> bool:
    try:
        with httpx.Client(timeout=180.0, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
        return dest.is_file() and dest.stat().st_size > 0
    except Exception as e:
        log.warning("ark download failed: %s", e)
        return False


# Seedream：Ark 大头+全身(+环境) 最多 4；再多会稀释身份。
_MAX_SEEDREAM_REFS = 4
# Seedance：首帧之外额外挂的角色 reference_image（大头+全身）
_MAX_SEEDANCE_IDENTITY_REFS = 2


def _classify_ref_role(rel: str) -> str:
    """粗分参考图角色：face / body / env / other。"""
    path = str(rel or "").replace("\\", "/").lower()
    name = path.rsplit("/", 1)[-1]
    if "_face." in name or name.endswith("_face.png") or name.endswith("_face.jpg"):
        return "face"
    if "_plate." in name or name.endswith("_plate.png") or name.endswith("_plate.jpg"):
        return "env"
    if "/characters/" in path and name.endswith((".png", ".jpg", ".jpeg", ".webp")):
        return "body"
    return "other"


def _image_path_to_data_uri(path: Path, *, max_side: int = 1536) -> str | None:
    """本地图片 → JPEG data URI（压缩边长，避免 Seedream/Seedance 请求体过大）。"""
    import base64
    from io import BytesIO

    from PIL import Image

    if not path.is_file() or path.stat().st_size < 32:
        return None
    try:
        img = Image.open(path).convert("RGB")
        w, h = img.size
        long_side = max(w, h)
        if long_side > max_side:
            scale = max_side / float(long_side)
            img = img.resize(
                (max(1, int(w * scale)), max(1, int(h * scale))),
                Image.Resampling.LANCZOS,
            )
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=90, optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
    except Exception as e:
        log.warning("ark image encode failed (%s): %s", path, e)
        return None


def _local_ref_to_data_uri(rel: str, *, max_side: int = 1536) -> str | None:
    """把工作区内的定妆/参考图编成 Seedream ``image`` 可用的 data URI。"""
    from tools.workspace import resolve_safe

    rel = str(rel or "").strip().replace("\\", "/")
    if not rel:
        return None
    if rel.startswith(("http://", "https://", "data:image/")):
        return rel
    try:
        path = resolve_safe(rel)
    except ValueError:
        return None
    return _image_path_to_data_uri(path, max_side=max_side)


def _seedance_duration(seconds: float | int | None) -> int:
    """Seedance 2.x 要求整数秒且最短 4s（2.5: 4–30；2.0: 4–15）。

    管线 ``i2v_seconds`` 默认 2.5 → round 成 2/3，原逻辑会提交 duration=2 被 API 400。
    """
    try:
        raw = float(seconds if seconds is not None else 5)
    except (TypeError, ValueError):
        raw = 5.0
    sec = int(round(raw)) if raw > 0 else 5
    return max(4, min(sec, 15))


def _audio_path_to_data_uri(path: Path, *, max_bytes: int = 14 * 1024 * 1024) -> str | None:
    """本地 TTS → Seedance ``audio_url`` data URI（mp3/wav，单段 ≤15MB）。"""
    import base64

    if not path.is_file():
        return None
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size < 64 or size > max_bytes:
        return None
    suffix = path.suffix.lower()
    mime = {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
    }.get(suffix)
    if not mime:
        return None
    try:
        b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError as e:
        log.warning("ark audio encode failed (%s): %s", path, e)
        return None
    return f"data:{mime};base64,{b64}"


def _shot_voice_path(shot: Any) -> Path | None:
    """Resolve shot assets.voice to a local file, if present."""
    if not isinstance(shot, dict):
        return None
    rel = str((shot.get("assets") or {}).get("voice") or "").strip()
    if not rel:
        return None
    try:
        from tools.workspace import resolve_safe

        path = resolve_safe(rel)
    except Exception:
        return None
    if path.is_file() and path.stat().st_size > 64:
        return path
    return None


def _manual_voice_enabled(shot: Any) -> bool:
    """仅「手动配音」开启时才挂 TTS reference_audio；默认走 Seedance 自带声。"""
    if not isinstance(shot, dict):
        return False
    if "manual_voice" in shot:
        return bool(shot.get("manual_voice"))
    slug = str(shot.get("_slug") or "").strip()
    if not slug:
        return False
    try:
        from tools.drama_studio import project_manual_voice

        return bool(project_manual_voice(slug))
    except Exception:
        return False


def _seedance_want_ref_audio(shot: Any) -> bool:
    """手动配音 + 对白镜：把 TTS 作为 Seedance reference_audio，驱动口型/节奏。"""
    if not isinstance(shot, dict):
        return False
    if not _manual_voice_enabled(shot):
        return False
    if _shot_voice_path(shot) is None:
        return False
    dialogue = str(shot.get("字幕") or shot.get("对白") or "").strip()
    if dialogue:
        return True
    try:
        from tools.drama_models import infer_kind

        return infer_kind(shot) in ("dialogue", "reaction")
    except Exception:
        return False


def _probe_voice_seconds(path: Path) -> float:
    try:
        from tools.drama_video import _probe_duration

        return float(_probe_duration(path) or 0)
    except Exception:
        return 0.0


def _seedream_image_payload(refs: tuple[str, ...]) -> str | list[str] | None:
    """官方契约：单张 ``image=url``，多张 ``image=[url, ...]``（最多 10，我们限 3）。"""
    uris: list[str] = []
    for rel in refs:
        if len(uris) >= _MAX_SEEDREAM_REFS:
            break
        uri = _local_ref_to_data_uri(str(rel or ""))
        if uri:
            uris.append(uri)
    if not uris:
        return None
    if len(uris) == 1:
        return uris[0]
    return uris


def _prompt_with_identity_refs(
    prompt: str,
    *,
    ref_count: int,
    env_ref_count: int = 0,
    lock_mode: str = "",
    refs: tuple[str, ...] | list[str] | None = None,
) -> str:
    """参考图分工（Ark）：大头照锁脸、全身照锁妆造体型、环境底板锁场景。"""
    base = str(prompt or "").strip()
    if ref_count <= 0:
        return base
    mode = str(lock_mode or "").strip().lower()
    if mode == "face_from_body":
        clause = (
            "参考图为同一角色的全身定妆立绘：必须生成该人肩上以上的正脸大头照特写，"
            "精确裁剪到人脸区域，尽量少带颈部肩部与背景；"
            "严格保持同一性别、年龄感、五官、发型发色与妆面；"
            "禁止换成另一张脸（如把青年男改成老翁或女生），禁止三视图/多视角，禁止手持道具，"
            "不要复刻全身站姿与定妆背景，只改景别为面部近景"
        )
        return f"{base}。{clause}" if base else clause

    roles = [_classify_ref_role(r) for r in (refs or ())[: max(0, int(ref_count or 0))]]
    if roles and len(roles) == int(ref_count or 0):
        bits: list[str] = [f"参考图共{ref_count}张（按编号认领，禁止拼贴叠印）"]
        face_idxs = [i + 1 for i, r in enumerate(roles) if r == "face"]
        body_idxs = [i + 1 for i, r in enumerate(roles) if r == "body"]
        env_idxs = [i + 1 for i, r in enumerate(roles) if r == "env"]
        if face_idxs:
            bits.append(
                "图"
                + "、".join(str(i) for i in face_idxs)
                + "为大头照：严格锁定面部五官与发型妆面，禁止换脸与双胞胎"
            )
        if body_idxs:
            bits.append(
                "图"
                + "、".join(str(i) for i in body_idxs)
                + "为全身照：严格锁定服装体型妆造与整体形象"
            )
        if env_idxs:
            bits.append(
                "图"
                + "、".join(str(i) for i in env_idxs)
                + "为地点/环境底板：保持同一建筑轮廓、主光与地面材质，禁止换成无关背景"
            )
        other_idxs = [i + 1 for i, r in enumerate(roles) if r == "other"]
        if other_idxs and not (face_idxs or body_idxs or env_idxs):
            bits.append("严格保持与参考图同一主体外形，禁止另造新人")
        bits.append("生成本镜全新构图、景别与姿势，不要复制定妆立绘站姿与背景")
        clause = "；".join(bits)
        return f"{base}。{clause}" if base else clause

    # 无路径时的回退（单测 / 旧调用）
    env_n = max(0, min(int(env_ref_count or 0), ref_count))
    face_n = max(0, ref_count - env_n)
    if env_n >= 1 and face_n >= 1:
        clause = (
            f"参考图共{ref_count}张：含环境底板与角色定妆；"
            "环境图保持同一建筑轮廓、主光与地面材质；"
            "角色图按大头照锁脸、全身照锁服装体型；禁止三视图与双胞胎；"
            "不要复制定妆立绘站姿与背景"
        )
    elif env_n >= 1:
        clause = (
            f"参考图共{ref_count}张环境底板：保持同一地点建筑轮廓、主光方向与地面材质，"
            "可调整景别与构图，禁止换成无关场景，禁止凭空加人脸抢戏"
        )
    elif ref_count == 1:
        clause = (
            "参考图为角色定妆立绘：严格保持同一张脸、同一发型发色与同一套服装配饰；"
            "生成本镜全新构图、景别与姿势，不要复制定妆立绘的站姿与背景"
        )
    else:
        clause = (
            f"参考图共{ref_count}张：优先大头照锁面部、全身照锁服装体型；"
            "禁止三视图/多视角与双胞胎；禁止把多张定妆图拼贴叠印；"
            "生成本镜全新构图与姿势，不要复制定妆立绘构图"
        )
    if not base:
        return clause
    return f"{base}。{clause}"


def _seedream_gen_size(width: int, height: int) -> str:
    """Map canvas to Seedream ``size`` (WxH string).

    Seedream **5.0 lite**（Agent Plan 默认）：
      总像素 ∈ [3_686_400, ~10_404_496]，宽高比 ∈ [1/16, 16]
    过小的 1024² / 1080×1920 会被抬升；过大则等比缩小。
    方形统一落到 ``2048x2048``（官方 2K 1:1，且稳过下限）。
    """
    w = max(64, int(width or 2048))
    h = max(64, int(height or 2048))
    # lite 上限约 3072²×1.1025；勿用过紧的 4.6M（会错误压扁 1600×2848 / 1620×2880）
    max_px = 10_404_496
    min_px = 3_686_400  # API: image size must be at least 3686400 pixels
    pixels = w * h
    if pixels > max_px:
        scale = (max_px / float(pixels)) ** 0.5
        w = max(64, int(w * scale))
        h = max(64, int(h * scale))
    elif pixels < min_px:
        scale = (min_px / float(pixels)) ** 0.5
        w = max(64, int(w * scale))
        h = max(64, int(h * scale))
    w = max(64, (w // 8) * 8)
    h = max(64, (h // 8) * 8)
    # 对齐后可能再次略低于下限
    if w * h < min_px:
        scale = (min_px / float(max(1, w * h))) ** 0.5
        w = max(64, int(w * scale))
        h = max(64, int(h * scale))
        w = max(64, (w // 8) * 8)
        h = max(64, (h // 8) * 8)
        while w * h < min_px:
            w += 8
            h += 8
    if abs(w - h) <= 16:
        # 方形：禁止再回落到 1024/1536（低于 API 下限）
        return "2048x2048"
    return f"{w}x{h}"


def _ark_image(
    prompt: str,
    dest,
    *,
    seed: int = 0,
    slug: str = "",
    shot: Any = None,
    width: int = 0,
    height: int = 0,
    refs: tuple[str, ...] = (),
) -> bool:
    """Seedream 文生图 / 图生图（带定妆 ``image`` 参考）→ PNG。

    官方示例：
      - 单参考：``image="https://..."``
      - 多参考：``image=["url1", "url2"]``
    本地定妆无 data URI，免公网上传。
    """
    key = _ark_key()
    if not key:
        if isinstance(shot, dict):
            shot["_image_error"] = "缺少 ARK_API_KEY"
        return False
    try:
        from tools.drama_parallel import acquire_lane

        acquire_lane("ark")
    except Exception:
        pass

    from PIL import Image

    # Model：shot 路由 → env；统一经 _resolve_seedream_model（Agent Plan 禁 pro）
    model = ""
    if isinstance(shot, dict):
        model = str(
            shot.get("_image_model")
            or shot.get("ref_image_model")
            or shot.get("image_model")
            or ""
        ).strip()
    if not model:
        model = str(getattr(config, "ARK_IMAGE_MODEL", "") or "").strip()
    model = _resolve_seedream_model(model)
    # Prefer portrait for drama; clamp into Seedream pixel budget.
    w = int(width or 1440)
    h = int(height or 2560)
    size = _seedream_gen_size(w, h) if w and h else "2048x2048"

    image_payload = _seedream_image_payload(tuple(refs or ()))
    ref_count = (
        0
        if image_payload is None
        else (len(image_payload) if isinstance(image_payload, list) else 1)
    )
    env_ref_count = 0
    if isinstance(shot, dict):
        try:
            env_ref_count = int(shot.get("_env_ref_count") or 0)
        except (TypeError, ValueError):
            env_ref_count = 0
    if env_ref_count <= 0 and refs:
        env_ref_count = sum(1 for r in refs if "_plate" in str(r).replace("\\", "/").lower())
        if env_ref_count <= 0 and isinstance(shot, dict) and str(shot.get("location_id") or "").strip():
            first = str(refs[0]).replace("\\", "/").lower()
            if "_face.png" not in first:
                env_ref_count = 1
    final_prompt = _prompt_with_identity_refs(
        str(prompt),
        ref_count=ref_count,
        env_ref_count=env_ref_count,
        lock_mode=str((shot or {}).get("ref_lock_mode") or "") if isinstance(shot, dict) else "",
        refs=tuple(refs or ()),
    )

    # Content-addressed cache (skip network when prompt/seed/model unchanged).
    if slug:
        try:
            from tools.drama_gen_cache import lookup as cache_lookup, store as cache_store

            hit = cache_lookup(
                slug,
                kind="image",
                prompt=final_prompt,
                seed=seed,
                provider="ark",
                model=model,
                suffix=".png",
            )
            if hit is not None:
                dest = Path(dest)
                dest.parent.mkdir(parents=True, exist_ok=True)
                import shutil

                shutil.copy2(hit, dest)
                try:
                    from tools.drama_observability import append_cost_log

                    append_cost_log(
                        slug,
                        capability="image",
                        provider="ark",
                        model=model,
                        cost=0.0,
                        ok=True,
                        detail="cache_hit",
                    )
                except Exception:
                    pass
                return dest.is_file() and dest.stat().st_size > 0
        except Exception:
            pass

    body: dict[str, Any] = {
        "model": model,
        "prompt": final_prompt,
        # 官方图生图示例用 size="2K"；带参考图时跟官方走，像素串易削弱锁脸。
        "size": "2K" if image_payload is not None else size,
        "response_format": "url",
        "output_format": "png",
        "watermark": False,
        "n": 1,
    }
    if image_payload is not None:
        body["image"] = image_payload
        log.info("ark seedream i2i refs=%s size=2K", ref_count)
    if seed:
        body["seed"] = int(seed) % 2147483647

    try:
        with httpx.Client(timeout=180.0, follow_redirects=True) as client:
            resp = client.post(
                f"{_ark_base()}/images/generations",
                headers=_ark_headers(),
                json=body,
            )
            if resp.status_code >= 400:
                detail = format_ark_http_error(resp.status_code, resp.text or "", model=model)
                log.warning("ark image %s", detail)
                if isinstance(shot, dict):
                    shot["_image_error"] = f"Seedream {detail[:280]}"
                if slug:
                    try:
                        from tools.drama_observability import append_cost_log

                        append_cost_log(
                            slug,
                            capability="image",
                            provider="ark",
                            model=model,
                            cost=0.0,
                            ok=False,
                            detail=f"HTTP {resp.status_code}: {detail[:160]}",
                        )
                    except Exception:
                        pass
                return False
            resp.raise_for_status()
            data = resp.json()
            items = data.get("data") or []
            if not items:
                log.warning("ark image empty response: %s", data)
                if isinstance(shot, dict):
                    shot["_image_error"] = "Seedream 返回空结果"
                return False
            item = items[0]
            url = item.get("url") or ""
            b64 = item.get("b64_json") or ""
            dest = Path(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if url:
                if not _download(url, dest):
                    return False
            elif b64:
                import base64

                dest.write_bytes(base64.b64decode(b64))
            else:
                return False

            # Normalize to target canvas for non-character_ref shots
            from tools.providers.image_providers import _is_character_ref_shot, _save_provider_image

            img = Image.open(dest).convert("RGB")
            tw = int(width or 1600)
            th = int(height or 2848)
            _save_provider_image(img, dest, shot=shot, target_w=tw, target_h=th)
            ok = dest.is_file() and dest.stat().st_size > 0
            if ok and slug:
                try:
                    from tools.drama_gen_cache import store as cache_store
                    from tools.drama_observability import append_cost_log, estimate_provider_cost

                    cache_store(
                        slug,
                        dest,
                        kind="image",
                        prompt=final_prompt,
                        seed=seed,
                        provider="ark",
                        model=model,
                        suffix=".png",
                    )
                    append_cost_log(
                        slug,
                        capability="image",
                        provider="ark",
                        model=model,
                        cost=estimate_provider_cost(slug, "ark"),
                        ok=True,
                    )
                except Exception:
                    pass
            return ok
    except Exception as e:
        log.warning("ark image failed: %s", e)
        if isinstance(shot, dict):
            shot["_image_error"] = str(e)[:240]
        if slug:
            try:
                from tools.drama_observability import append_cost_log

                append_cost_log(
                    slug,
                    capability="image",
                    provider="ark",
                    model=model,
                    cost=0.0,
                    ok=False,
                    detail=str(e)[:160],
                )
            except Exception:
                pass
        return False


def _seedance_identity_ref_rels(shot: Any) -> list[str]:
    """本镜 Seedance 身份参考：主体大头照→全身照（最多 2）。"""
    if not isinstance(shot, dict):
        return []
    cached = shot.get("_seedance_identity_refs")
    if isinstance(cached, (list, tuple)) and cached:
        return [str(x).replace("\\", "/") for x in cached if str(x).strip()][:_MAX_SEEDANCE_IDENTITY_REFS]
    slug = str(shot.get("_slug") or "").strip()
    if not slug:
        return []
    try:
        from tools.drama_characters import (
            character_ark_pair_refs,
            character_requires_face_identity,
            load_characters,
            resolve_shot_characters,
        )
        from tools.drama_spatial import identity_subject_character

        subject = identity_subject_character(slug, shot)
        if subject and character_requires_face_identity(subject):
            pair = character_ark_pair_refs(slug, subject)
            if pair:
                return pair[:_MAX_SEEDANCE_IDENTITY_REFS]
        cast = resolve_shot_characters(shot, load_characters(slug))
        for char in cast:
            if not character_requires_face_identity(char):
                continue
            pair = character_ark_pair_refs(slug, char)
            if pair:
                return pair[:_MAX_SEEDANCE_IDENTITY_REFS]
    except Exception:
        return []
    return []


def _ark_i2v(scene, dest, shot, seconds) -> str:
    """Seedance 图生视频（异步任务）。"""
    key = _ark_key()
    if not key:
        if isinstance(shot, dict):
            shot["i2v_error"] = "missing_ARK_API_KEY"
        return "none"

    try:
        from tools.drama_parallel import acquire_lane

        acquire_lane("ark")
    except Exception:
        pass

    from tools.drama_i2v import _motion_prompt

    model = _resolve_seedance_model(getattr(config, "ARK_VIDEO_MODEL", ""))
    identity_rels = _seedance_identity_ref_rels(shot)
    scene_path = Path(scene)
    if not scene_path.is_file():
        if isinstance(shot, dict):
            shot["i2v_error"] = "missing_scene"
        return "none"

    # 与 Seedream refs 相同：JPEG 压缩，避免 4K PNG base64 撑爆 / 超时。
    image_url = _image_path_to_data_uri(scene_path, max_side=1536)
    if not image_url:
        if isinstance(shot, dict):
            shot["i2v_error"] = "scene_encode_failed"
        return "none"

    # 先编码身份参考，再按实际挂载数写 @图片N（首帧=1）
    identity_uris: list[tuple[str, str]] = []
    for rel in identity_rels[:_MAX_SEEDANCE_IDENTITY_REFS]:
        uri = _local_ref_to_data_uri(rel, max_side=1536)
        if uri:
            identity_uris.append((rel, uri))
    if isinstance(shot, dict):
        shot["_seedance_identity_refs"] = [r for r, _ in identity_uris]
        face_i = 2 if identity_uris else 0
        body_i = 3 if len(identity_uris) >= 2 else (2 if len(identity_uris) == 1 else 0)
        shot["_seedance_face_image_index"] = face_i
        shot["_seedance_body_image_index"] = (
            body_i if len(identity_uris) >= 2 else (face_i if identity_uris else 0)
        )

    prompt = _motion_prompt(shot)
    duration = _seedance_duration(seconds)

    # 默认：Seedance generate_audio 自带声（人声/音效）。
    # 手动配音：先 TTS，再挂 reference_audio，并关闭模型出声，成片 mux TTS。
    used_ref_audio = False
    voice_path = _shot_voice_path(shot) if _seedance_want_ref_audio(shot) else None
    audio_url = _audio_path_to_data_uri(voice_path) if voice_path is not None else None
    if audio_url and voice_path is not None:
        voice_sec = _probe_voice_seconds(voice_path)
        # API：单段参考音频约 2–15s；过短则不强挂，避免 InvalidParameter。
        if 1.8 <= voice_sec <= 15.5 or voice_sec <= 0:
            if voice_sec > 0:
                duration = _seedance_duration(max(float(seconds or 0), voice_sec))
            from tools.drama_ark_prompts import build_seedance_ref_audio_suffix

            prompt = f"{prompt}。{build_seedance_ref_audio_suffix()}"
            used_ref_audio = True
        else:
            audio_url = None
            log.info(
                "ark i2v skip reference_audio: voice_sec=%.2f out of 2–15s window",
                voice_sec,
            )

    content: list[dict[str, Any]] = [
        {"type": "text", "text": prompt},
        {
            "type": "image_url",
            "image_url": {"url": image_url},
            "role": "first_frame",
        },
    ]
    # Ark：首帧后挂大头照+全身照为 reference_image，强化脸/服一致性
    for _rel, uri in identity_uris:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": uri},
                "role": "reference_image",
            }
        )
    if used_ref_audio and audio_url:
        content.append(
            {
                "type": "audio_url",
                "audio_url": {"url": audio_url},
                "role": "reference_audio",
            }
        )

    # 挂了参考音频则关模型出声，避免双音轨；否则默认开原生音频。
    gen_audio = not used_ref_audio
    body = {
        "model": model,
        "content": content,
        "duration": duration,
        # Seedance 2.5 首帧/首尾帧任务强制 ratio=adaptive，传 9:16 会 400。
        "ratio": "adaptive",
        "generate_audio": gen_audio,
    }
    if isinstance(shot, dict):
        shot["i2v_audio_ref"] = bool(used_ref_audio)
        shot["i2v_generate_audio"] = bool(gen_audio)
        shot["manual_voice"] = bool(_manual_voice_enabled(shot))
        shot["i2v_identity_ref_count"] = len(identity_uris)

    def _remember_error(msg: str) -> None:
        if isinstance(shot, dict):
            shot["i2v_error"] = str(msg or "")[:240]
        try:
            from tools.drama_observability import append_cost_log, estimate_provider_cost

            slug = str((shot or {}).get("_slug") or "") if isinstance(shot, dict) else ""
            ep = int((shot or {}).get("_episode") or 0) if isinstance(shot, dict) else 0
            sn = int((shot or {}).get("n") or 0) if isinstance(shot, dict) else 0
            if slug:
                append_cost_log(
                    slug,
                    capability="i2v",
                    provider="ark",
                    model=model,
                    cost=0.0,
                    shot=sn or None,
                    episode=ep or None,
                    ok=False,
                    detail=str(msg or "")[:400],
                )
        except Exception:
            pass

    def _format_http_error(resp: httpx.Response) -> str:
        return format_ark_http_error(resp.status_code, resp.text or "", model=model)

    def _strip_identity_refs_for_retry() -> None:
        """首帧任务若拒收 reference_image：去掉身份图并清掉 @图片认领文案，保留首帧。"""
        nonlocal content, body, prompt
        if not identity_uris:
            return
        content = [
            c
            for c in content
            if not (isinstance(c, dict) and c.get("role") == "reference_image")
        ]
        # 去掉认领句（避免指向不存在的 @图片N）
        for marker in ("角色面部特征严格参考@图片", "角色面部与整体形象严格参考@图片"):
            if marker in prompt:
                parts = prompt.split("。")
                prompt = "。".join(p for p in parts if marker not in p)
                break
        if content and isinstance(content[0], dict) and content[0].get("type") == "text":
            content[0]["text"] = prompt
        body = {**body, "content": content}
        if isinstance(shot, dict):
            shot["i2v_identity_ref_count"] = 0
            shot["_seedance_identity_refs_dropped"] = True
            shot["_seedance_face_image_index"] = 0
            shot["_seedance_body_image_index"] = 0

    try:
        with httpx.Client(timeout=300.0, follow_redirects=True) as client:
            submit = client.post(
                f"{_ark_base()}/contents/generations/tasks",
                headers=_ark_headers(),
                json=body,
            )
            if submit.status_code >= 400 and identity_uris:
                err_txt = (submit.text or "").lower()
                if any(
                    k in err_txt
                    for k in (
                        "reference_image",
                        "invalidparameter",
                        "invalid_parameter",
                        "role",
                        "content",
                    )
                ):
                    log.warning(
                        "ark i2v retry without identity reference_image: %s",
                        submit.text[:300],
                    )
                    _strip_identity_refs_for_retry()
                    submit = client.post(
                        f"{_ark_base()}/contents/generations/tasks",
                        headers=_ark_headers(),
                        json=body,
                    )
            if submit.status_code >= 400:
                _remember_error(f"model={model}; {_format_http_error(submit)}")
                log.warning("ark i2v submit failed model=%s: %s", model, submit.text[:500])
                return "none"
            job = submit.json()
            task_id = str(job.get("id") or job.get("task_id") or "").strip()
            if not task_id:
                # Some responses return result inline
                video_url = (
                    ((job.get("content") or {}) if isinstance(job.get("content"), dict) else {}).get("video_url")
                    or job.get("video_url")
                    or ""
                )
                if video_url and _download(video_url, Path(dest)):
                    if isinstance(shot, dict):
                        shot.pop("i2v_error", None)
                        if used_ref_audio or gen_audio:
                            shot["seedance_lip"] = True
                    return "ai"
                log.warning("ark i2v no task id: %s", job)
                _remember_error("no_task_id")
                return "none"

            deadline = time.monotonic() + float(getattr(config, "I2V_POLL_TIMEOUT", 300) or 300)
            while time.monotonic() < deadline:
                # 其它镜失败 / 用户取消：立刻退出轮询，避免空等数分钟收尾
                cancel = shot.get("_cancel_check") if isinstance(shot, dict) else None
                if callable(cancel):
                    try:
                        cancel()
                    except Exception as exc:
                        # PeerAbort / JobCancelled：立刻结束轮询，交给上层收尾
                        name = type(exc).__name__
                        if name in ("PeerAbort", "JobCancelled") or "加速收尾" in str(exc) or "已取消" in str(exc):
                            _remember_error(f"cancelled:{exc}"[:240])
                            log.info("ark i2v poll aborted task=%s err=%s", task_id, exc)
                            raise
                        _remember_error(f"cancelled:{exc}"[:240])
                        log.info("ark i2v poll aborted task=%s err=%s", task_id, exc)
                        return "none"
                time.sleep(float(getattr(config, "I2V_POLL_INTERVAL", 2.0) or 2.0))
                poll = client.get(
                    f"{_ark_base()}/contents/generations/tasks/{task_id}",
                    headers=_ark_headers(),
                )
                if poll.status_code >= 400:
                    _remember_error(_format_http_error(poll))
                    return "none"
                info = poll.json()
                status = str(info.get("status") or info.get("task_status") or "").lower()
                if status in ("succeeded", "success", "completed", "done"):
                    content = info.get("content") if isinstance(info.get("content"), dict) else {}
                    video_url = (
                        (content or {}).get("video_url")
                        or info.get("video_url")
                        or ((info.get("result") or {}) if isinstance(info.get("result"), dict) else {}).get("video_url")
                        or ""
                    )
                    if video_url and _download(str(video_url), Path(dest)):
                        if isinstance(shot, dict):
                            shot.pop("i2v_error", None)
                            if used_ref_audio or gen_audio:
                                shot["seedance_lip"] = True
                        try:
                            from tools.drama_observability import append_cost_log, estimate_provider_cost

                            slug = str((shot or {}).get("_slug") or "") if isinstance(shot, dict) else ""
                            ep = int((shot or {}).get("_episode") or 0) if isinstance(shot, dict) else 0
                            sn = int((shot or {}).get("n") or 0) if isinstance(shot, dict) else 0
                            if slug:
                                append_cost_log(
                                    slug,
                                    capability="i2v",
                                    provider="ark",
                                    model=model,
                                    cost=estimate_provider_cost(slug, "ark"),
                                    shot=sn or None,
                                    episode=ep or None,
                                    ok=True,
                                    detail="seedance_ref_audio" if used_ref_audio else "",
                                )
                        except Exception:
                            pass
                        return "ai"
                    _remember_error("succeeded_but_no_video_url")
                    return "none"
                if status in ("failed", "error", "cancelled"):
                    err = info.get("error") or info.get("message") or info
                    log.warning("ark i2v task failed: %s", info)
                    _remember_error(f"task_{status}: {err}"[:240])
                    return "none"
            log.warning("ark i2v timeout task=%s", task_id)
            _remember_error(f"timeout task={task_id}")
            return "none"
    except Exception as e:
        log.warning("ark i2v failed: %s", e)
        # 保留已解析的 HTTP 业务错误，不被通用异常文案覆盖。
        if isinstance(shot, dict) and not shot.get("i2v_error"):
            _remember_error(str(e))
        return "none"


def _ark_tts(text, dest, *, voice=None) -> bool:
    """Seed Audio TTS（OpenAI 兼容 audio/speech）。"""
    from tools.drama_tts_policy import refuse_or_edge

    key = _ark_key()
    if not key:
        return refuse_or_edge(text, dest, voice=voice, reason="未配置 ARK_API_KEY")

    try:
        from tools.drama_parallel import acquire_lane
        acquire_lane("ark")
    except Exception:
        pass

    model = str(getattr(config, "ARK_AUDIO_MODEL", "") or "doubao-seed-audio-1-0").strip()
    body = {
        "model": model,
        "input": str(text),
        "voice": str(voice or "zh_female_vv_uranus_bigtts"),
        "response_format": "mp3",
    }
    try:
        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            resp = client.post(
                f"{_ark_base()}/audio/speech",
                headers=_ark_headers(),
                json=body,
            )
            resp.raise_for_status()
            dest = Path(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
        return dest.is_file() and dest.stat().st_size > 0
    except Exception as e:
        log.warning("ark tts failed: %s", e)
        return refuse_or_edge(text, dest, voice=voice, reason=f"Ark TTS 失败: {e}")


register("image", "ark", _ark_image)
register("image", "seedream", _ark_image)
register("image", "doubao-image", _ark_image)
register("i2v", "ark", _ark_i2v)
register("i2v", "seedance", _ark_i2v)
register("i2v", "doubao-video", _ark_i2v)
register("tts", "ark", _ark_tts)
register("tts", "seed-audio", _ark_tts)
register("tts", "doubao-audio", _ark_tts)
