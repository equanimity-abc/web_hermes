"""One-shot HQ episode production — no workbench clicks required.

Default profile: pro preset, classify → cast/refs → scene+voice+lip → I2V → export.
Intended for chat agent `produce_episode` and background queue `produce_episode`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tools.drama_models import DEFAULT_PRESET, load_models

HQ_SHOT_LAYERS = ("scene", "overlay", "voice", "lip")
DEFAULT_CATALOG_BGM = "rebirth_resolve"

_DEFAULT_SECONDS = 60
_MIN_SECONDS = 15
_MAX_SECONDS = 90
_MAX_EPISODES = 20


def _progress(cb: Callable[..., None] | None, **fields: Any) -> None:
    if cb:
        cb(**fields)


def shot_range_for_seconds(seconds: int) -> tuple[int, int]:
    """Suggested ### Shot count for a target episode length."""
    sec = max(_MIN_SECONDS, min(int(seconds or _DEFAULT_SECONDS), _MAX_SECONDS))
    lo = max(3, int(round(sec / 12)))
    hi = max(lo, min(14, int(round(sec / 6))))
    return lo, hi


def clamp_episode_seconds(seconds: int | float | None, *, default: int = _DEFAULT_SECONDS) -> int:
    try:
        sec = int(round(float(seconds)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        sec = int(default)
    return max(_MIN_SECONDS, min(sec, _MAX_SECONDS))


def clamp_episode_count(count: int | None, *, default: int = 1) -> int:
    try:
        n = int(count)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        n = int(default)
    return max(1, min(n, _MAX_EPISODES))


def parse_series_spec(
    text: str,
    *,
    episode_count: int | None = None,
    seconds: int | None = None,
) -> dict[str, Any]:
    """Extract episode count + per-episode seconds from user wording / overrides.

    Episode count defaults to **1 only when the user did not clearly state a series size**.
    Phrases like「第2集」mean which episode, not “make 2 episodes”.

    Examples understood:
    - 「共3集，每集60秒」
    - 「3集×60s」
    - 「每集约1分钟」（时长；集数仍默认 1）
    - 「2 episodes, 30 seconds each」
    """
    raw = str(text or "")
    count_from_text = _parse_episode_count_from_text(raw)
    sec_from_text = _parse_seconds_from_text(raw)

    # Explicit tool overrides win, except ignore a bare episode_count=1 when the
    # premise clearly asks for more (agents often pass the schema default 1).
    if episode_count is not None:
        try:
            override = int(episode_count)
        except (TypeError, ValueError):
            override = None
        if (
            override == 1
            and count_from_text is not None
            and count_from_text > 1
        ):
            count = count_from_text
        else:
            count = override
    else:
        count = count_from_text

    if seconds is not None:
        sec = seconds
    else:
        sec = sec_from_text

    ep_n = clamp_episode_count(count, default=1)
    ep_sec = clamp_episode_seconds(sec, default=_DEFAULT_SECONDS)
    lo, hi = shot_range_for_seconds(ep_sec)
    count_explicit = count is not None
    return {
        "episode_count": ep_n,
        "seconds_per_episode": ep_sec,
        "shot_min": lo,
        "shot_max": hi,
        "count_explicit": count_explicit,
        "seconds_explicit": sec is not None,
        "source": (
            "args"
            if episode_count is not None or seconds is not None
            else ("premise" if count_explicit or sec is not None else "default")
        ),
    }


_CN_EP_NUM = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def _parse_episode_count_from_text(raw: str) -> int | None:
    """Return N only when user clearly plans an N-episode series; else None."""
    if not raw:
        return None

    patterns = [
        r"(?:共|一共|总计|合计)\s*(\d+)\s*集",
        r"(?:做|拍|制作|产出|写成|分成|规划)\s*(\d+)\s*集",
        r"(\d+)\s*集\s*[×xX*]",
        r"(\d+)\s*集\s*[，,、]?\s*(?:每集|\d+\s*秒)",
        r"(\d+)\s*episodes?\b",
    ]
    for pat in patterns:
        m = re.search(pat, raw, re.I)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                continue

    # 「三集」「两集」等（需有共/一共/做… 或紧跟每集/秒，避免误伤）
    m = re.search(
        r"(?:共|一共|总计|合计|做|拍|制作|产出|写成|分成|规划)\s*([一二两三四五六七八九十])\s*集",
        raw,
    )
    if m:
        return _CN_EP_NUM.get(m.group(1))

    m = re.search(
        r"([一二两三四五六七八九十])\s*集\s*[，,、]?\s*(?:每集|\d+\s*秒|[一二两三四五六七八九十]\s*分钟)",
        raw,
    )
    if m:
        return _CN_EP_NUM.get(m.group(1))

    # Bare 「3集」 only when not 「第3集」
    for m in re.finditer(r"(\d+)\s*集", raw):
        prefix = raw[max(0, m.start() - 2) : m.start()]
        if prefix.endswith("第") or re.search(r"第\s*$", prefix):
            continue
        try:
            return int(m.group(1))
        except ValueError:
            continue
    return None


def _parse_seconds_from_text(raw: str) -> int | None:
    if not raw:
        return None
    sec = None
    if re.search(r"每集\s*约?\s*一\s*分钟", raw):
        return 60
    m = re.search(
        r"每集\s*约?\s*(\d+(?:\.\d+)?)\s*(分钟|分|秒|s)\b",
        raw,
        re.I,
    )
    if m:
        try:
            val = float(m.group(1))
        except ValueError:
            val = float(_DEFAULT_SECONDS)
        unit = str(m.group(2) or "").lower()
        return int(round(val * 60)) if unit.startswith("分") else int(round(val))
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:秒|s)\s*/\s*集", raw, re.I)
    if m:
        try:
            return int(round(float(m.group(1))))
        except ValueError:
            pass
    m = re.search(
        r"(\d+)\s*(?:seconds?|secs?|s)\s*(?:each|per(?:\s*ep(?:isode)?)?)",
        raw,
        re.I,
    )
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    # 「3集60秒」紧挨写法（无“每集”）
    m = re.search(r"\d+\s*集\s*[，,、]?\s*(\d+)\s*秒", raw)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    m = re.search(r"([一二两三四五六七八九十])\s*集\s*[，,、]?\s*(\d+)\s*秒", raw)
    if m:
        try:
            return int(m.group(2))
        except ValueError:
            pass
    return sec


_EP_HEADER_RE = re.compile(r"^#\s*EP\s*0*(\d+)\b.*$", re.M | re.I)


def extract_single_episode_markdown(text: str, episode: int) -> str:
    """Keep only one `# EPxx` section so multi-ep dumps cannot pollute shots.json."""
    raw = str(text or "").strip()
    if not raw:
        return raw
    n = clamp_episode_count(episode, default=1)
    matches = list(_EP_HEADER_RE.finditer(raw))
    if not matches:
        if not raw.lstrip().startswith("#"):
            return f"# EP{n:02d}\n\n{raw}"
        return raw

    chosen = None
    for i, m in enumerate(matches):
        try:
            ep_no = int(m.group(1))
        except ValueError:
            continue
        if ep_no != n:
            continue
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        chosen = raw[start:end].strip()
        break

    if chosen is None:
        start = matches[0].start()
        end = matches[1].start() if len(matches) > 1 else len(raw)
        chosen = raw[start:end].strip()

    lines = chosen.splitlines()
    if lines and _EP_HEADER_RE.match(lines[0]):
        title_rest = re.sub(r"^#\s*EP\s*0*\d+\s*", "", lines[0], count=1, flags=re.I).strip()
        lines[0] = f"# EP{n:02d}" + (f" {title_rest}" if title_rest else "")
    return "\n".join(lines).strip()


def apply_target_duration_meta(text: str, seconds: int) -> str:
    """Force top-level `- 时长:` to the user/target budget before save."""
    from tools.drama_video import patch_episode_meta_duration

    sec = clamp_episode_seconds(seconds)
    patched = patch_episode_meta_duration(str(text or ""), float(sec))
    if re.search(r"^-\s*\*{0,2}时长\*{0,2}\s*[:：]", patched, re.M):
        return patched
    lines = patched.splitlines()
    if lines and lines[0].startswith("#"):
        return lines[0] + f"\n\n- 时长: {sec}s\n" + "\n".join(lines[1:]).lstrip("\n")
    return f"- 时长: {sec}s\n\n{patched}"


def ensure_hq_preset(slug: str) -> str:
    """Apply default (ark) preset when project is not already on it (profile=studio)."""
    doc = load_models(slug)
    preset = str(doc.get("preset") or "").strip().lower()
    if preset == DEFAULT_PRESET:
        return preset
    from tools.drama_config import apply_preset

    apply_preset(slug, DEFAULT_PRESET)
    return DEFAULT_PRESET


def ensure_characters_from_shots(slug: str, doc: dict[str, Any]) -> list[str]:
    """Create minimal character cards for shot roles that have no card yet."""
    from tools.drama_characters import (
        canonical_role_name,
        infer_roles_from_dialogue,
        load_characters,
        match_character_token,
        normalize_roles,
        role_token_face_exempt,
        upsert_character,
    )

    cards = load_characters(slug)
    cast = [c for c in cards if str(c.get("category") or "character") == "character"]
    needed: list[str] = []
    seen: set[str] = set()
    for shot in doc.get("shots") or []:
        tokens = normalize_roles(shot.get("角色"))
        if not tokens:
            tokens = infer_roles_from_dialogue(str(shot.get("字幕") or ""), cast)
        for token in tokens:
            raw = str(token or "").strip()
            if not raw:
                continue
            # 「后羿（仅影子）」→ 归并到「后羿」，避免再建无人脸卡去撞身份闸。
            t = canonical_role_name(raw)
            if not t or t in seen:
                continue
            seen.add(t)
            if match_character_token(t, cast) or match_character_token(raw, cast):
                continue
            # 收束后仍是剪影说明本身（如角色列只有「剪影」）→ 不成卡
            if role_token_face_exempt(t):
                continue
            needed.append(t)

    created: list[str] = []
    for name in needed:
        look = f"{name}，抖音竖屏漫剧主角/配角，五官清晰，发型与服装符合剧情气质，高质量二次元"
        rec = upsert_character(
            slug,
            {
                "name": name,
                "look": look,
                "category": "character",
                "colors": "主色:#E8E8E8, 点缀:#4A4A4A",
            },
        )
        cast.append(rec)
        created.append(str(rec.get("id") or name))
    return created


def ensure_character_refs(
    slug: str,
    *,
    lock: bool = True,
    on_progress: Callable[..., None] | None = None,
) -> list[str]:
    """Generate a single portrait ref per character (no 4-up wall, no auto-retry).

    生成一次 → 身份就绪校验 → 才锁定。失败则 Fail Loud，由工作台手工重生成/上传。
    锁定后的定妆是稳定的身份锚点，下游不再改动它。
    """
    from tools.drama_characters import (
        character_requires_face_identity,
        find_character,
        identity_ref_rel,
        load_characters,
        ref_exists,
        ref_face_exists,
        ref_rel,
        set_ref_locked,
    )
    from tools.drama_common import parse_slug
    from tools.drama_parallel import parallel_map, shot_concurrency
    from tools.drama_qc import validate_character_ref
    from tools.drama_series import invalidate_character_embedding
    from tools.drama_studio import generate_character_ref
    from tools.drama_video import generate_character_face_portrait
    from tools.workspace import resolve_safe

    slug = parse_slug(slug)
    generated: list[str] = []
    pending: list[tuple[str, str]] = []
    cards = load_characters(slug)
    for rec in cards:
        if str(rec.get("category") or "character") != "character":
            continue
        cid = str(rec.get("id") or "")
        if not cid:
            continue
        # 剪影/仅影子：不做 ArcFace 定妆闸（无人脸是预期，不是失败）。
        if not character_requires_face_identity(rec):
            continue
        if not str(rec.get("look") or "").strip():
            continue
        if rec.get("ref_locked") and ref_exists(slug, rec):
            # 已锁定全身定妆：若缺正脸特写则补生成（不改全身）
            if not ref_face_exists(slug, rec):
                pending.append((cid, str(rec.get("name") or cid)))
            continue  # 已锁定且存在：不可变，跳过全身重生成
        # 已有未锁定定妆：也视为用户资产，流水线不得覆盖（只在完全缺失时生成）
        if ref_exists(slug, rec):
            if not ref_face_exists(slug, rec):
                pending.append((cid, str(rec.get("name") or cid)))
            elif lock and not rec.get("ref_locked"):
                try:
                    set_ref_locked(slug, cid, True)
                except Exception:
                    pass
            else:
                continue
            continue
        pending.append((cid, str(rec.get("name") or cid)))

    def _ref_path(rec: dict[str, Any]) -> Path | None:
        rel = identity_ref_rel(slug, rec)
        if not rel:
            return None
        try:
            return resolve_safe(rel)
        except ValueError:
            return None

    def _lock_if_needed(rec: dict[str, Any]) -> None:
        if lock and not rec.get("ref_locked"):
            try:
                set_ref_locked(slug, str(rec.get("id") or ""), True)
            except Exception:
                pass

    def _ensure_face(rec: dict[str, Any], name: str) -> dict[str, Any]:
        if ref_face_exists(slug, rec):
            return rec
        _progress(on_progress, message=f"正脸特写 {name}")
        face_rel = generate_character_face_portrait(slug, rec, seed=None)
        if not face_rel:
            return rec
        from tools.drama_characters import upsert_character

        cid_local = str(rec.get("id") or "")
        upsert_character(slug, {"id": cid_local, "ref_face": face_rel})
        invalidate_character_embedding(slug, cid_local)
        return find_character(load_characters(slug), cid_local) or rec

    def _one(item: tuple[str, str]) -> str:
        cid, name = item
        rec = find_character(load_characters(slug), cid)
        if rec is None:
            raise RuntimeError(f"角色「{name}」（{cid}）角色卡不存在，无法生成定妆")
        # 已有未锁定的 ref：先补特写，再校验，通过就直接锁，避免无谓重生成。
        if ref_exists(slug, rec):
            rec = _ensure_face(rec, name)
            check = validate_character_ref(_ref_path(rec))
            if check["ok"]:
                _lock_if_needed(rec)
                return cid
            if rec.get("ref_locked"):
                raise RuntimeError(
                    f"角色「{name}」已锁定定妆未通过身份校验："
                    f"{check.get('hint') or check.get('reason')}；请在工作台解锁后重生成正脸特写"
                )
            raise RuntimeError(
                f"角色「{name}」已有定妆未通过锁定前校验："
                f"{check.get('hint') or check.get('reason')}；请在工作台手工重生成或上传"
            )
        _progress(on_progress, message=f"定妆 {name}")
        try:
            generate_character_ref(slug, cid, lock=False, seed=None)
        except Exception as exc:
            raise RuntimeError(f"角色「{name}」定妆生成失败：{exc}") from exc
        invalidate_character_embedding(slug, cid)
        rec = find_character(load_characters(slug), cid)
        if rec is None:
            raise RuntimeError(f"角色「{name}」（{cid}）定妆生成后角色卡丢失")
        if not ref_face_exists(slug, rec):
            rec = _ensure_face(rec, name)
        check = validate_character_ref(_ref_path(rec))
        if check["ok"]:
            _lock_if_needed(rec)
            return cid
        raise RuntimeError(
            f"角色「{name}」定妆未通过身份就绪校验"
            f"（{check.get('hint') or check.get('reason')}）；请在工作台手工重生成或上传"
        )

    if pending:
        for cid in parallel_map(pending, _one, max_workers=min(4, shot_concurrency())):
            if cid:
                generated.append(cid)
    return generated


def ensure_default_bgm(slug: str, episode: int, *, catalog_id: str = DEFAULT_CATALOG_BGM) -> bool:
    """Attach a royalty-free catalog BGM when mix has none (export-safe)."""
    from tools.drama_audio import has_bgm, load_catalog, load_mix, patch_mix

    mix = load_mix(slug, episode)
    if has_bgm(mix):
        return False
    tracks = load_catalog(slug).get("tracks") or []
    ids = {str(t.get("id") or "") for t in tracks}
    cid = catalog_id if catalog_id in ids else (str(tracks[0].get("id") or "") if tracks else "")
    if not cid:
        return False
    patch_mix(slug, episode, {"catalog_id": cid})
    return True


def _assert_identity_deps_ready(slug: str) -> None:
    """专业档身份验收的前置依赖闸（fail-before-burn）。

    存在角色卡（可能需要抽身份）但 ArcFace 未就绪时直接失败，避免白烧图像模型；
    无角色（整集定场/标题，身份全部 n/a）则跳过。
    """
    from tools.drama_characters import character_requires_face_identity, load_characters
    from tools.drama_qc import _arcface_ready

    cards = load_characters(slug)
    needs_identity = any(character_requires_face_identity(c) for c in cards)
    if needs_identity and not _arcface_ready():
        raise RuntimeError(
            "身份模型 ArcFace 未就绪（insightface 未安装或 buffalo_l 模型未缓存），"
            "专业档身份验收无法进行。请先运行 backend/scripts/fetch_arcface_model.py "
            "或安装 insightface 并下载 buffalo_l 后再试。"
        )


def _hq_process_one_shot(
    slug: str,
    episode: int,
    shot_n: int,
    *,
    ep_title: str,
    force: bool,
    cancel_check: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Render one shot end-to-end for HQ produce (thread-safe via merge_save_shot).

    单次出图 + 身份验收；若因构图/脸面积/锁脸失败，自动加强制露脸提示并换种子重抽画面 **至多 1 次**，
    仍失败则 Fail Loud（不再无限重试）。
    """
    import copy

    from tools.drama_i2v import generate_shot_i2v
    from tools.drama_models import effective_motion_ladder, infer_kind, models_with_overrides
    from tools.drama_parallel import acquire_provider_lanes_for_shot
    from tools.drama_qc import qc_shot_identity
    from tools.drama_shots import episode_lock, find_shot, load_doc, merge_save_shot
    from tools.drama_video import render_shot_layers, rerender_shot

    n = int(episode)
    sn = int(shot_n)
    if cancel_check:
        cancel_check()

    with episode_lock(slug, n):
        doc = load_doc(slug, n)
        if doc is None:
            raise FileNotFoundError(f"没有 shots.json：{slug} ep{n:02d}")
        shot = find_shot(doc, sn)
        if shot is None:
            return {"shot": sn, "skipped": True, "reason": "missing"}
        if "shot" in set(shot.get("locked") or []):
            return {"shot": sn, "skipped": True, "reason": "locked"}
        # 续跑：clip+身份通过且无脏层时，再验闪烁；闪烁不过则重做运动，不整镜重跑。
        if not force:
            assets = shot.get("assets") if isinstance(shot.get("assets"), dict) else {}
            identity = shot.get("identity") if isinstance(shot.get("identity"), dict) else {}
            dirty = set(shot.get("dirty") or [])
            if assets.get("clip") and identity.get("pass") and not (dirty & {"motion", "clip", "scene"}):
                from tools.drama_qc import check_allows_pass, qc_shot_flicker

                flicker = shot.get("qc_flicker") if isinstance(shot.get("qc_flicker"), dict) else {}
                if str(flicker.get("status") or "") != "ok":
                    flicker = qc_shot_flicker(slug, shot, apply=False)
                if check_allows_pass(flicker):
                    return {"shot": sn, "skipped": True, "reason": "already_ok"}
                # 闪烁未过：只走运动/成片重做路径
                shot = copy.deepcopy(shot)
                shot["_flicker_only_repair"] = True
            else:
                shot = copy.deepcopy(shot)
        else:
            shot = copy.deepcopy(shot)

    from tools.drama_series import apply_dual_speaker_notes

    apply_dual_speaker_notes(shot)

    acquire_provider_lanes_for_shot(slug, shot)

    layers = list(HQ_SHOT_LAYERS)
    if force or not (shot.get("assets") or {}).get("clip"):
        layers = list(HQ_SHOT_LAYERS)

    degrades: list[Any] = []
    identity_last: dict[str, Any] = (
        shot.get("identity") if isinstance(shot.get("identity"), dict) else {}
    )
    flicker_only = bool(shot.pop("_flicker_only_repair", None))

    if not flicker_only:
        def _run_scene_and_qc(*, retry: int) -> tuple[dict[str, Any], dict[str, Any]]:
            if cancel_check:
                cancel_check()
            local_layers = list(layers)
            if retry > 0:
                # 身份失败只重抽画面相关层，避免重复烧 TTS
                local_layers = ["scene", "overlay", "clip"]
                shot["_identity_retry"] = retry
                shot["_identity_framing_boost"] = True
                dirty = list(shot.get("dirty") or [])
                for layer in ("scene", "clip", "motion"):
                    if layer not in dirty:
                        dirty.append(layer)
                shot["dirty"] = dirty
            info_local = render_shot_layers(
                slug,
                n,
                shot,
                local_layers,
                title=ep_title,
                candidate_count=1,
            )
            merge_save_shot(slug, n, shot)

            from tools.drama_models import apply_shot_class
            from tools.drama_spatial import build_spatial_plan

            apply_shot_class(shot, force=False)
            build_spatial_plan(slug, shot)
            identity_local = qc_shot_identity(slug, n, shot, apply=True)
            merge_save_shot(slug, n, shot)
            return info_local, identity_local

        info, identity_last = _run_scene_and_qc(retry=0)
        degrades = list(info.get("degrades") or [])

        def _identity_needs_retry(identity: dict[str, Any]) -> bool:
            status = str(identity.get("status") or "")
            reason = str(identity.get("reason") or "")
            if status == "ok" and not identity.get("pass"):
                return True
            if status == "skipped" and reason in (
                "no_face",
                "unmatched_face",
                "no_embedding",
                "face_too_small",
            ):
                return True
            return False

        if _identity_needs_retry(identity_last):
            try:
                info, identity_last = _run_scene_and_qc(retry=1)
                degrades = list(info.get("degrades") or [])
            finally:
                shot.pop("_identity_framing_boost", None)
                shot.pop("_identity_retry", None)

        if str(identity_last.get("status") or "") == "skipped":
            identity_reason = str(identity_last.get("reason") or "").strip()
            identity_hint = str(identity_last.get("hint") or "").strip()
            role = str(identity_last.get("character_name") or identity_last.get("character_id") or "").strip() or "未识别角色"
            if identity_reason == "no_locked_ref":
                detail = f"角色「{role}」缺少锁定定妆图（角色卡参考图未锁定）"
            elif identity_reason == "no_scene":
                detail = f"角色「{role}」本镜缺少画面"
            elif identity_reason == "proxy_identity":
                detail = f"角色「{role}」身份模型 ArcFace 不可用，专业档禁止直方图代理过关"
            elif identity_reason == "no_face":
                detail = f"角色「{role}」本镜画面未检测到人脸（定妆已锁定；已自动重抽仍失败）"
            elif identity_reason == "unmatched_face":
                detail = f"角色「{role}」未在画面中匹配到对应人脸（{identity_hint or '已自动重抽仍失败'}）"
            elif identity_reason == "no_embedding":
                detail = f"角色「{role}」本镜画面未能提取人脸嵌入（已自动重抽仍失败）"
            elif identity_reason in ("no_embedder", "no_insightface", "arcface_error"):
                detail = f"角色「{role}」身份嵌入依赖缺失或调用失败"
            elif identity_reason in ("missing_left", "missing_right"):
                detail = f"角色「{role}」定妆参考图或本镜画面文件缺失"
            elif identity_reason == "no_ok_checks":
                detail = f"角色「{role}」无可打分画面（回退参考缺依赖）"
            else:
                detail = identity_hint or f"角色「{role}」缺少定妆或依赖"
            raise RuntimeError(
                f"第{sn}镜身份验收未通过（{detail}），专业档不得记为通过"
            )

        if str(identity_last.get("status") or "") == "ok" and not identity_last.get("pass"):
            role = str(identity_last.get("character_name") or identity_last.get("character_id") or "").strip() or "未识别角色"
            hint = str(identity_last.get("hint") or "")
            raise RuntimeError(
                f"第{sn}镜角色「{role}」身份相似度未达阈值"
                f"（cosine={identity_last.get('cosine', identity_last.get('score', '?'))}"
                f"{('；' + hint) if hint else ''}），已自动重抽画面仍失败"
            )

        # P2：通过后写入跨镜轨迹
        try:
            from tools.drama_track import record_shot_identity_pass

            record_shot_identity_pass(slug, n, shot, identity_last)
        except Exception:
            pass
        # P3：通过帧入库，供后续镜检索构图记忆
        try:
            from tools.drama_frame_memory import add_passed_frame

            add_passed_frame(slug, episode=n, shot=shot, identity=identity_last)
        except Exception:
            pass
        merge_save_shot(slug, n, shot)
        if cancel_check:
            cancel_check()

    models = models_with_overrides(slug, shot=shot, episode=n)
    from tools.drama_motion_floors import assert_motion_floor

    assert_motion_floor(shot, slug=slug, models=models)
    planned = effective_motion_ladder(shot, slug=slug, models=models)

    def _run_i2v() -> dict[str, Any]:
        return generate_shot_i2v(slug, n, shot, force=True, allow_locked=True, strict=True)

    i2v = _run_i2v()
    src = str(i2v.get("i2v_source") or shot.get("i2v_source") or "none")
    kind = infer_kind(shot)
    if planned not in ("L0",) and kind not in ("establishing", "insert", "crowd", "title"):
        if src not in ("ai", "keys"):
            detail = str(shot.get("i2v_error") or i2v.get("reason") or "").strip()
            provider = str(shot.get("i2v_provider") or i2v.get("provider") or "").strip()
            extra = ""
            if provider or detail:
                extra = f"（provider={provider or '?'}{('；' + detail) if detail else ''}）"
            raise RuntimeError(
                f"Shot {sn} 需要真 I2V（计划 {planned}），但得到 {src or 'none'}{extra}；"
                "专业档禁止 Ken Burns/mock 顶替"
            )
    merge_save_shot(slug, n, shot)

    # 闪烁验收：失败则自动换一次运动（不重配音），仍失败则 Fail Loud（避免拖到导出才拦）
    from tools.drama_qc import check_allows_pass, qc_shot_flicker

    flicker = qc_shot_flicker(slug, shot, apply=True)
    merge_save_shot(slug, n, shot)
    if not check_allows_pass(flicker) and src in ("ai", "keys"):
        shot["_flicker_retry"] = 1
        # 解锁后强制重做运动，避免被 auto-lock 挡住
        locked = [x for x in (shot.get("locked") or []) if x != "motion"]
        shot["locked"] = locked
        dirty = list(shot.get("dirty") or [])
        for layer in ("motion", "clip"):
            if layer not in dirty:
                dirty.append(layer)
        shot["dirty"] = dirty
        i2v = _run_i2v()
        src = str(i2v.get("i2v_source") or shot.get("i2v_source") or "none")
        merge_save_shot(slug, n, shot)
        flicker = qc_shot_flicker(slug, shot, apply=True)
        merge_save_shot(slug, n, shot)
        shot.pop("_flicker_retry", None)
    if not check_allows_pass(flicker):
        hint = str(flicker.get("hint") or flicker.get("reason") or "闪烁未通过")
        raise RuntimeError(
            f"第{sn}镜闪烁验收未通过（{hint}），已自动重做运动仍失败"
        )

    if cancel_check:
        cancel_check()
    rerender_shot(slug, n, sn, layers=["clip"])

    return {
        "shot": sn,
        "skipped": False,
        "i2v_tried": bool(i2v.get("tried")),
        "i2v_source": src,
        "degrades": degrades,
        "flicker_ssim": flicker.get("ssim"),
    }


def produce_episode_hq(
    slug: str,
    episode: int,
    *,
    force: bool = False,
    style_id: str = "",
    catalog_bgm: str = DEFAULT_CATALOG_BGM,
    cancel_check: Callable[[], None] | None = None,
    on_progress: Callable[..., None] | None = None,
    allow_qc_fail_export: bool = False,
) -> dict[str, Any]:
    """Run the full HQ pipeline synchronously; returns get_episode() + stages summary.

    Phase A studio profile: Fail Loud — missing keys / identity fail / fake I2V /
    QC fail all raise. Agent must keep allow_qc_fail_export=False.
    身份构图失败至多自动重抽画面 1 次；闪烁失败至多自动重做运动 1 次；定妆仍为单次；
    候选墙供工作台手工微调。

    Phase B: cast refs + shot DAG run under DRAMA_SHOT_CONCURRENCY with provider lanes.
    """
    from tools.drama_parallel import ProgressClock, parallel_map, shot_concurrency
    from tools.drama_profiles import assert_profile_allows_studio_gates, resolve_quality_profile, research_backlog
    from tools.drama_quality import assert_studio_providers
    from tools.drama_shots import load_doc
    from tools.drama_studio import classify_shots, export_episode, get_episode

    slug = str(slug or "").strip()
    n = int(episode)
    clock = ProgressClock()
    preset = ensure_hq_preset(slug)

    profile = resolve_quality_profile(slug)
    assert_profile_allows_studio_gates(profile)
    clock.start("preset")
    _progress(on_progress, stage="preset", message=f"质量预设 {preset} · profile={profile}")
    assert_studio_providers(slug)
    clock.end("preset")

    if cancel_check:
        cancel_check()

    ep = get_episode(slug, n)
    markdown = ep.get("script")
    if not markdown:
        raise FileNotFoundError("没有分集剧本，请先 save_episode")

    from tools.drama_video import sync_shots_doc

    clock.start("sync")
    doc = sync_shots_doc(slug, n, str(markdown), title=str(ep.get("title") or ""))
    ep_title = str(doc.get("title") or f"第{n}集")

    if style_id:
        from tools.drama_studio import apply_style

        apply_style(slug, n, style_id)

    classify_shots(slug, n, force=False)
    doc = load_doc(slug, n) or doc
    from tools.drama_series import apply_dual_speaker_notes_doc, ensure_cast_embeddings
    from tools.drama_shots import save_doc
    from tools.drama_snapshots import take_snapshot
    from tools.drama_spatial import ensure_spatial_plans_doc

    dual_count = apply_dual_speaker_notes_doc(doc)
    spatial_count = ensure_spatial_plans_doc(slug, doc)
    if dual_count > 0 or spatial_count > 0:
        save_doc(doc)
    clock.end("sync")

    clock.start("cast")
    from tools.drama_characters import (
        ensure_character_looks_expanded,
        ensure_character_anchors,
        ensure_character_traits,
        purge_shadow_character_cards,
    )

    purged_shadows = purge_shadow_character_cards(slug)
    created_chars = ensure_characters_from_shots(slug, doc)
    expanded_looks = ensure_character_looks_expanded(slug)
    trait_cids = ensure_character_traits(slug)
    anchored = ensure_character_anchors(slug)
    _assert_identity_deps_ready(slug)
    ref_chars = ensure_character_refs(slug, on_progress=on_progress)
    emb_cids = ensure_cast_embeddings(slug)
    _progress(
        on_progress,
        stage="cast",
        message=(
            f"角色 {len(created_chars)} 新建 · 清除影子卡 {len(purged_shadows)} · "
            f"look 扩写 {len(expanded_looks)} · 特征字段 {len(trait_cids)} · "
            f"特征锚 {len(anchored)} · 定妆 {len(ref_chars)} 生成"
        ),
    )
    clock.end(
        "cast",
        characters=len(created_chars),
        refs=len(ref_chars),
        looks=len(expanded_looks),
        traits=len(trait_cids),
        anchors=len(anchored),
        shadows_purged=len(purged_shadows),
    )

    shots = list(doc.get("shots") or [])
    total = len(shots)
    stages: dict[str, Any] = {
        "preset": preset,
        "quality_profile": profile,
        "research": research_backlog(),
        "characters_created": created_chars,
        "shadows_purged": purged_shadows,
        "looks_expanded": expanded_looks,
        "refs_generated": ref_chars,
        "embeddings": emb_cids,
        "dual_speaker_shots": dual_count,
        "snapshots": [],
        "shots_rendered": [],
        "i2v_shots": [],
        "degraded": [],
        "strict": True,
        "parallel": True,
        "shot_concurrency": shot_concurrency(),
    }

    doc = load_doc(slug, n) or doc
    snap = take_snapshot(slug, n, doc, tag="stage_cast")
    if snap:
        stages["snapshots"].append(snap)

    shot_ns = [int(s.get("n") or 0) for s in shots if int(s.get("n") or 0) > 0]
    done_lock = __import__("threading").Lock()
    done_count = {"n": 0}
    ok_count = {"n": 0}
    fail_count = {"n": 0}

    def _worker(sn: int) -> dict[str, Any]:
        _progress(
            on_progress,
            stage="shot",
            shot=sn,
            total=total,
            current=ok_count["n"],
            finished=done_count["n"],
            message=f"Shot {sn} 画面/配音/口型/I2V（并行）",
        )
        return _hq_process_one_shot(
            slug,
            n,
            sn,
            ep_title=ep_title,
            force=force,
            cancel_check=cancel_check,
        )

    def _on_done(_i: int, sn: int, result: Any) -> None:
        with done_lock:
            done_count["n"] += 1
            finished = done_count["n"]
            if isinstance(result, BaseException):
                fail_count["n"] += 1
                ok = ok_count["n"]
                failed = fail_count["n"]
                _progress(
                    on_progress,
                    stage="shot",
                    shot=sn,
                    current=ok,
                    total=total,
                    finished=finished,
                    failed=failed,
                    ok=ok,
                    message=f"Shot {sn} 失败：{result}",
                )
                return
            ok_count["n"] += 1
            ok = ok_count["n"]
            _progress(
                on_progress,
                stage="shot",
                shot=sn,
                current=ok,
                total=total,
                finished=finished,
                failed=fail_count["n"],
                ok=ok,
                message=f"Shot {sn} 完成 ({ok}/{total} 成功，已结束 {finished}/{total})",
            )

    clock.start("shots")
    shot_results = parallel_map(
        shot_ns,
        _worker,
        max_workers=shot_concurrency(),
        cancel_check=cancel_check,
        on_done=_on_done,
    )
    clock.end("shots", count=len(shot_results))

    for row in shot_results:
        if not isinstance(row, dict) or row.get("skipped"):
            continue
        sn = int(row.get("shot") or 0)
        stages["shots_rendered"].append(sn)
        if row.get("i2v_tried"):
            stages["i2v_shots"].append(sn)
        stages["degraded"].extend(row.get("degrades") or [])

    doc = load_doc(slug, n) or doc
    snap = take_snapshot(slug, n, doc, tag="stage_shots")
    if snap:
        stages["snapshots"].append(snap)

    _progress(on_progress, stage="bgm", message="挂载默认配乐")
    clock.start("bgm")
    ensure_default_bgm(slug, n, catalog_id=catalog_bgm)
    clock.end("bgm")

    if cancel_check:
        cancel_check()

    doc = load_doc(slug, n) or doc
    snap = take_snapshot(slug, n, doc, tag="stage_pre_export")
    if snap:
        stages["snapshots"].append(snap)

    _progress(on_progress, stage="export", message="QC 硬闸后拼接导出")
    clock.start("export")
    # Agent / HQ: never allow_qc_fail_export. Workbench-only force is separate API.
    result = export_episode(
        slug,
        n,
        background=False,
        force=bool(allow_qc_fail_export),
    )
    clock.end("export")
    stages["timing"] = clock.snapshot()
    stages["observability"] = {"timing": stages["timing"], "failure_heat": {}}
    if not result.get("play_url"):
        from tools.drama_video import output_rel

        rel = output_rel(slug, n)
        result["play_url"] = f"/api/workspace/file?path={rel}"
        result["path"] = result.get("path") or rel
    result["produce"] = {
        "profile": "hq",
        "stages": stages,
        "candidate_count": 1,
        "refs_locked": True,
        "exported": True,
        "hint": "全自动 HQ 已导出整集；定妆已锁定；分镜仅单图（候选墙请在工作台微调时手动生成）",
    }
    return result


def suggest_project_slug(premise: str, title: str = "") -> str:
    """ASCII slug from title if possible; otherwise drama-{crc32}."""
    import re
    import zlib

    raw = str(title or "").strip() or str(premise or "").strip()
    ascii_part = re.sub(r"[^a-zA-Z0-9]+", "-", raw).strip("-").lower()
    if len(ascii_part) >= 3 and ascii_part[0].isalnum():
        return ascii_part[:40]
    digest = zlib.crc32(str(premise or raw).encode("utf-8")) & 0xFFFFFFFF
    return f"drama-{digest:08x}"


def _strip_code_fence(text: str) -> str:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    return raw


def _draft_title(slug: str, premise: str) -> str:
    from tools.drama_script import draft_text_sync

    title = draft_text_sync(
        slug,
        f"故事梗概：{premise}\n\n只输出一个中文短剧名（不超过16字），不要引号、不要解释。",
        system="你是竖屏漫剧起名专家，只输出标题。",
    )
    title = _strip_code_fence(title).splitlines()[0].strip().strip("《》\"'“”")
    return title[:32] or "未命名漫剧"


def generate_bible_and_outline(
    slug: str,
    premise: str,
    title: str,
    *,
    series: dict[str, Any] | None = None,
) -> dict[str, str]:
    """LLM: bible.md + outline.md from one premise."""
    from tools.drama_script import draft_text_sync
    from tools.workspace import resolve_safe

    spec = series or parse_series_spec(premise)
    ep_n = int(spec.get("episode_count") or 1)
    ep_sec = int(spec.get("seconds_per_episode") or _DEFAULT_SECONDS)
    if spec.get("count_explicit") and ep_n > 1:
        plan_line = f"- 集数规划：共 {ep_n} 集，每集约 {ep_sec} 秒\n"
        ep_lines = "\n".join(
            f"- EP{i:02d}：本集钩子、主体节拍、结尾悬念（严格服务第{i}集，约 {ep_sec}s）"
            for i in range(1, ep_n + 1)
        )
        outline_title = "# 系列大纲"
    else:
        # 默认单集：不写「集数/第几集」以免 UI 与模型都长出多余集概念
        plan_line = f"- 时长：约 {ep_sec} 秒\n"
        ep_lines = f"- 钩子与节拍：开头钩子、主体冲突、结尾悬念（完整单集故事，约 {ep_sec}s）"
        outline_title = "# 故事大纲"
    system = (
        "你是专业竖屏漫剧主创。根据梗概写出人设圣经与故事大纲。"
        "严格按下面分隔符输出，不要其它说明：\n"
        "===BIBLE===\n"
        "# 人设圣经\n"
        "## 世界观\n（2–4 句）\n"
        "## 主角\n- 姓名：…\n- 外形：具体五官/发型/服装/配色（可拍）\n- 性格：…\n- 口头禅：…\n"
        "## 对手/配角\n（同上格式，共 2–4 人）\n"
        "===OUTLINE===\n"
        f"{outline_title}\n"
        f"{plan_line}"
        "- 一句话卖点：…\n"
        "- 主线冲突：…\n"
        f"{ep_lines}\n"
    )
    constraint = (
        f"硬性约束：共{ep_n}集，每集{ep_sec}秒，请按集拆分大纲，不要把多集剧情挤进一集。"
        if spec.get("count_explicit") and ep_n > 1
        else f"硬性约束：只做一支单集短片，时长约{ep_sec}秒；不要写「第几集/共几集/EP02」，不要规划系列。"
    )
    raw = _strip_code_fence(
        draft_text_sync(
            slug,
            f"剧名：{title}\n故事梗概：{premise}\n{constraint}",
            system=system,
        )
    )
    bible = ""
    outline = ""
    if "===BIBLE===" in raw and "===OUTLINE===" in raw:
        mid = raw.split("===BIBLE===", 1)[1]
        bible_part, outline_part = mid.split("===OUTLINE===", 1)
        bible = bible_part.strip()
        outline = outline_part.strip()
    else:
        bible = f"# 人设圣经\n\n- 梗概：{premise}\n"
        outline = (
            f"{outline_title}\n\n- 剧名：{title}\n- 梗概：{premise}\n"
            f"{plan_line}"
        )

    if not bible.startswith("#"):
        bible = "# 人设圣经\n\n" + bible
    if not outline.startswith("#"):
        outline = "# 系列大纲\n\n" + outline

    root = resolve_safe(f"dramas/{slug}")
    root.mkdir(parents=True, exist_ok=True)
    (root / "bible.md").write_text(bible.rstrip() + "\n", encoding="utf-8")
    (root / "outline.md").write_text(outline.rstrip() + "\n", encoding="utf-8")
    return {"bible": bible, "outline": outline}


def init_project_from_premise(
    premise: str,
    *,
    slug: str = "",
    title: str = "",
    overwrite: bool = False,
) -> dict[str, Any]:
    """Create dramas/{slug}/project.json from a one-line premise.

    同一聊天多次重启续写时：即使传入新 slug，也优先复用同名/同梗概项目，
    避免侧栏堆出多个《嫦娥奔月》。
    """
    from tools.drama_common import (
        DramaBadRequest,
        find_project_slug_by_logline,
        find_project_slug_by_title,
        load_drama_project_file,
        parse_slug,
        utc_now,
    )
    from tools.workspace import resolve_safe

    def _normalize_title(value: str) -> str:
        return str(value or "").strip().strip("《》\"'“”‘’")

    def _save_project_local(project_slug: str, data: dict[str, Any]) -> None:
        data = dict(data)
        data["updated_at"] = utc_now()
        path = resolve_safe(f"dramas/{project_slug}/project.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    text = str(premise or "").strip()
    if not text:
        raise DramaBadRequest("请先给一句故事梗概")

    given_title = _normalize_title(title)

    # 先按标题/梗概撞车（覆盖显式 slug），除非 overwrite
    reused = None
    if not overwrite:
        if given_title:
            reused = find_project_slug_by_title(given_title)
        if not reused:
            reused = find_project_slug_by_logline(text)
        # 尚未起名时，从梗概里抽《标题》再撞一次
        if not reused and not given_title:
            m = re.search(r"《([^》]{1,32})》", text)
            if m:
                reused = find_project_slug_by_title(m.group(1))

    if reused:
        sid = parse_slug(reused)
    elif slug:
        sid = parse_slug(slug)
    else:
        sid = parse_slug(suggest_project_slug(text, given_title))

    existing = load_drama_project_file(sid)

    if existing and not overwrite:
        existing["logline"] = text
        if given_title:
            existing["title"] = given_title
        existing["updated_at"] = utc_now()
        existing.pop("archived", None)
        existing.pop("hidden", None)
        _save_project_local(sid, existing)
        ensure_hq_preset(sid)
        return existing

    now = utc_now()
    project = {
        "slug": sid,
        "title": given_title or sid,
        "logline": text,
        "aspect": "9:16",
        "created_at": (existing or {}).get("created_at") or now,
        "updated_at": now,
        "episodes": (existing or {}).get("episodes") if existing and not overwrite else [],
    }
    _save_project_local(sid, project)
    ensure_hq_preset(sid)
    resolve_safe(f"dramas/{sid}/episodes").mkdir(parents=True, exist_ok=True)

    if not given_title:
        project["title"] = _draft_title(sid, text)
        project["updated_at"] = utc_now()
        # 起名后再按标题撞车复用，避免同名剧多份目录
        collided = find_project_slug_by_title(project["title"])
        if collided and collided != sid and not overwrite:
            other = load_drama_project_file(collided)
            if other:
                other["logline"] = text
                other["updated_at"] = utc_now()
                other.pop("archived", None)
                other.pop("hidden", None)
                _save_project_local(collided, other)
                ensure_hq_preset(collided)
                return other
        _save_project_local(sid, project)

    readme = resolve_safe(f"dramas/{sid}/README.md")
    if not readme.is_file():
        readme.write_text(
            f"# {project['title']}\n\n"
            f"- slug: `{sid}`\n"
            f"- 画幅: 9:16\n"
            f"- 一句话: {text}\n\n"
            f"目录：`bible.md` · `outline.md` · `episodes/` · `characters.json`\n",
            encoding="utf-8",
        )
    return project


def create_from_premise(
    premise: str,
    *,
    slug: str = "",
    title: str = "",
    episode: int = 1,
    episode_count: int | None = None,
    seconds: int | None = None,
    overwrite: bool = False,
    background: bool = False,
    force: bool = False,
    style_id: str = "",
    catalog_bgm: str = DEFAULT_CATALOG_BGM,
    cancel_check: Callable[[], None] | None = None,
    on_progress: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """One sentence → project + bible + outline + N episode scripts + HQ mp4(s).

    Episode count / per-episode seconds are parsed from the premise unless overridden.
    """
    from tools.drama_studio import generate_episode_script, produce_episode, save_project
    from tools.drama_video import output_rel

    text = str(premise or "").strip()
    spec = parse_series_spec(text, episode_count=episode_count, seconds=seconds)
    ep_total = int(spec["episode_count"])
    ep_sec = int(spec["seconds_per_episode"])

    _progress(
        on_progress,
        stage="init",
        message=(
            f"立项…（共 {ep_total} 集 × {ep_sec}s）"
            if ep_total > 1
            else f"立项…（单集 {ep_sec}s）"
        ),
    )
    project = init_project_from_premise(
        text, slug=slug, title=title, overwrite=overwrite
    )
    slug = str(project.get("slug") or "")
    title = str(project.get("title") or slug)
    project["series"] = {
        "episode_count": ep_total,
        "seconds_per_episode": ep_sec,
        "shot_min": spec["shot_min"],
        "shot_max": spec["shot_max"],
        "count_explicit": bool(spec.get("count_explicit")),
        "seconds_explicit": bool(spec.get("seconds_explicit")),
        "source": spec["source"],
    }
    project["logline"] = text
    save_project(slug, project)

    # If caller passes episode>1 with default count=1, still honor single-ep produce.
    start_ep = clamp_episode_count(episode, default=1)
    if ep_total == 1 and start_ep > 1:
        episode_numbers = [start_ep]
    else:
        episode_numbers = list(range(1, ep_total + 1))

    # 已有分集内容时直接复用，绝不自动重跑成片（避免覆盖用户刚改的定妆/画面）
    existing_eps = [ep for ep in (project.get("episodes") or []) if int(ep.get("n") or 0) >= 1]
    if existing_eps and not overwrite:
        first = episode_numbers[0]
        _progress(on_progress, stage="reuse", message=f"复用已有项目 {slug}（不重渲）…")
        play_url = None
        play_path = None
        try:
            rel = output_rel(slug, first)
            from tools.workspace import resolve_safe as _resolve

            if _resolve(rel).is_file():
                play_path = rel
                play_url = f"/api/workspace/file?path={rel}"
        except Exception:
            pass
        return {
            "ok": True,
            "action": "create_from_premise",
            "reused": True,
            "slug": slug,
            "title": title,
            "episode": first,
            "series": project["series"],
            "logline": text,
            "scripts": [
                {
                    "episode": int(ep.get("n") or 0),
                    "title": ep.get("title"),
                    "seconds": ep.get("seconds"),
                }
                for ep in existing_eps
            ],
            "play_url": play_url,
            "path": play_path,
            "hint": (
                f"已复用项目 {slug}（{title}），保留现有定妆/分镜/成片，未自动重渲。"
                "若要重做某集，请显式调用 produce_episode。"
            ),
        }

    if cancel_check:
        cancel_check()
    _progress(on_progress, stage="bible", message="生成人设与大纲…")
    docs = generate_bible_and_outline(slug, text, title, series=spec)

    script_infos: list[dict[str, Any]] = []
    for n in episode_numbers:
        if cancel_check:
            cancel_check()
        _progress(
            on_progress,
            stage="script",
            message=(
                f"生成第{n}/{episode_numbers[-1]}集剧本（目标 {ep_sec}s）…"
                if ep_total > 1
                else f"生成剧本（目标 {ep_sec}s）…"
            ),
        )
        info = generate_episode_script(
            slug,
            n,
            text,
            target_seconds=ep_sec,
            episode_count=ep_total,
        )
        script_infos.append({"episode": n, **{k: info.get(k) for k in ("count", "title", "seconds")}})

    if cancel_check:
        cancel_check()

    if background:
        # Queue first episode only (queue API is per-episode); scripts for all are ready.
        first = episode_numbers[0]
        job = produce_episode(
            slug,
            first,
            background=True,
            force=force,
            style_id=style_id,
            catalog_bgm=catalog_bgm,
        )
        return {
            "ok": True,
            "action": "create_from_premise",
            "slug": slug,
            "title": title,
            "episode": first,
            "series": project["series"],
            "logline": text,
            "bible_chars": len(docs.get("bible") or ""),
            "outline_chars": len(docs.get("outline") or ""),
            "scripts": script_infos,
            "shots": (script_infos[0] or {}).get("count"),
            "job_id": job.get("job_id"),
            "status": job.get("status"),
            "hint": (
                f"已按 {ep_total}集×{ep_sec}s 写好剧本；第{first}集成片在后台渲染。"
                "其余集可用 produce_episode 继续；poll_job 查进度。"
                if ep_total > 1
                else f"剧本已生成（约 {ep_sec}s），成片在后台渲染；poll_job 查进度。"
            ),
        }

    episode_results: list[dict[str, Any]] = []
    primary: dict[str, Any] | None = None
    for idx, n in enumerate(episode_numbers):
        if cancel_check:
            cancel_check()
        _progress(
            on_progress,
            stage="produce",
            message=(
                f"HQ 成片 {n}/{episode_numbers[-1]}…"
                if ep_total > 1
                else "HQ 成片流水线…"
            ),
        )
        result = produce_episode(
            slug,
            n,
            background=False,
            force=force,
            style_id=style_id,
            catalog_bgm=catalog_bgm,
        )
        if not result.get("play_url"):
            rel = output_rel(slug, n)
            result["play_url"] = f"/api/workspace/file?path={rel}"
            result["path"] = result.get("path") or rel
        entry = {
            "episode": n,
            "title": result.get("title"),
            "shots": result.get("count") or (script_infos[idx].get("count") if idx < len(script_infos) else None),
            "seconds": result.get("seconds") or ep_sec,
            "play_url": result.get("play_url"),
            "path": result.get("path"),
            "bytes": result.get("bytes"),
        }
        episode_results.append(entry)
        if primary is None:
            primary = result

    assert primary is not None
    primary["series"] = project["series"]
    primary["episodes"] = episode_results
    primary["episode"] = episode_numbers[0]
    primary["play_url"] = episode_results[0].get("play_url") or primary.get("play_url")
    primary["create"] = {
        "slug": slug,
        "title": title,
        "logline": text,
        "bible_chars": len(docs.get("bible") or ""),
        "outline_chars": len(docs.get("outline") or ""),
        "episode_count": ep_total,
        "seconds_per_episode": ep_sec,
        "scripts": script_infos,
        "exported": True,
        "refs_locked": True,
        "candidate_count": 1,
    }
    primary["hint"] = (
        f"已按用户需求拆成 {ep_total} 集、每集约 {ep_sec} 秒，并全部导出成片；"
        "定妆已锁定；不满意可进工作台微调。"
        if ep_total > 1
        else f"已生成约 {ep_sec} 秒单集成片并导出；定妆已锁定；不满意可进工作台微调。"
    )
    return primary
