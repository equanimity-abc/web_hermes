"""Drama workbench service (D1). REST uses this; agent loop is not involved."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import quote

# drama_common 必须最先导入：其它 tools 子模块可能回勾 drama_studio，
# 若此时尚未绑定 normalize_project_title 等，会触发 ImportError。
from tools.drama_common import (
    DramaBadRequest,
    DramaNotFound,
    find_project_slug_by_logline,
    find_project_slug_by_title,
    load_drama_project_file,
    normalize_project_title,
    parse_episode,
    parse_shot_n,
    parse_slug,
    project_substance_score,
)
from tools.workspace import resolve_safe, workspace_root

from tools.drama_characters import (
    CharacterError,
    delete_character,
    load_characters,
    normalize_roles,
    primary_voice,
    public_voices,
    resolve_shot_characters,
    save_character_ref,
    set_ref_locked,
    suggest_character_id,
    upsert_character,
)
from tools.drama_models import (
    SHOT_KINDS,
    SHOT_SIZES,
    budget_state as _budget_state,
    estimate_episode_i2v,
    estimate_i2v,
    load_models,
    public_models,
    save_models,
    set_provider_available,
)
from tools.drama_shots import (
    apply_shot_class,
    apply_patch,
    cascade_shot_timings,
    doc_timings_drift,
    episode_total_seconds,
    find_shot,
    json_rel,
    load_doc,
    MIN_PLAY_SEC,
    public_shot,
    reconcile_doc_timings,
    round_timing,
    save_doc,
    script_impact,
    set_shot_locks,
    TRANSITIONS,
    I2V_MODES,
    normalize_i2v_mode,
)
from tools.drama_timeline import apply_timeline_patch, patch_timeline_doc, public_timeline
from tools.drama_snapshots import (
    drop_snapshot as _drop_snapshot,
    list_snapshots as _list_snapshots,
    restore_snapshot as _restore_snapshot,
    take_snapshot as _take_snapshot,
)

_ROOT = "dramas"
CAMERAS = (
    "punch_in",
    "punch_shake",
    "pan_right",
    "pan_left",
    "rise",
    "fall",
    "pull_out",
)


def play_url(rel: str) -> str:
    return f"/api/workspace/file?path={quote(str(rel), safe='/')}"


def _rel(*parts: str) -> str:
    return "/".join((_ROOT,) + parts)


def _project_rel(slug: str) -> str:
    return _rel(slug, "project.json")


def _read_text(rel: str) -> str | None:
    path = resolve_safe(rel)
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def _write_text(rel: str, content: str) -> str:
    path = resolve_safe(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return rel


def load_project_file(name: str) -> dict[str, Any] | None:
    return load_drama_project_file(name)


def load_project(slug: str) -> dict[str, Any]:
    slug = parse_slug(slug)
    data = load_project_file(slug)
    if data is None:
        raise DramaNotFound(f"项目不存在：{slug}")
    return data


def save_project(slug: str, data: dict[str, Any]) -> None:
    from datetime import datetime, timezone

    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_text(_project_rel(slug), json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _asset_meta(rel: str, *, probe_image: bool = False) -> dict[str, Any]:
    info = {"path": rel, "exists": False, "bytes": 0, "url": None, "width": 0, "height": 0}
    if not rel:
        return info
    try:
        path = resolve_safe(rel)
    except ValueError:
        return info
    if path.is_file() and path.stat().st_size > 0:
        info["exists"] = True
        info["bytes"] = path.stat().st_size
        info["url"] = play_url(rel)
        # 候选墙/列表默认不 probe：8MB 级 PNG 用 PIL 开尺寸会拖死接口，导致图不显示、删除超时
        if probe_image and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
            try:
                from PIL import Image

                with Image.open(path) as img:
                    w, h = img.size
                    info["width"] = int(w)
                    info["height"] = int(h)
            except Exception:
                pass
    return info


def enrich_shot(shot: dict[str, Any], *, slug: str = "", episode: int | None = None) -> dict[str, Any]:
    pub = public_shot(shot)
    assets = pub.get("assets") or {}
    pub["files"] = {layer: _asset_meta(str(rel or "")) for layer, rel in assets.items()}
    clip = pub["files"].get("clip") or {}
    pub["preview_url"] = clip.get("url") or (pub["files"].get("scene") or {}).get("url")
    if slug:
        cards = load_characters(slug)
        cast = resolve_shot_characters(shot, cards)
        pub["cast"] = [{"id": c["id"], "name": c["name"], "voice": c["voice"]} for c in cast]
        pub["voice_id"] = primary_voice(cast, slug=slug) if cast else ""
        from tools.drama_video import shot_voice_speakers

        pub["voice_speakers"] = shot_voice_speakers(shot, cards, slug=slug)
        pub["voice_turns"] = list(shot.get("voice_turns") or [])
        from tools.drama_dialogue import build_dialogue_track, normalize_dialogue_track

        stored_track = normalize_dialogue_track(shot.get("dialogue_track"))
        if stored_track.get("turns"):
            pub["dialogue_track"] = stored_track
        else:
            pub["dialogue_track"] = build_dialogue_track(shot, cards, slug=slug)
        pub["lip_base_used"] = bool(shot.get("lip_base_used"))
        pub["motion_locked"] = "motion" in (shot.get("locked") or []) or "shot" in (shot.get("locked") or [])
        # Mismatch: lip was built from still lip_base while video-page motion exists
        motion_rel = str((shot.get("assets") or {}).get("motion") or "")
        has_motion_asset = False
        if motion_rel:
            try:
                mp = resolve_safe(motion_rel)
                has_motion_asset = mp.is_file() and mp.stat().st_size > 500
            except ValueError:
                has_motion_asset = False
        pub["lip_base_mismatch"] = bool(pub["lip_base_used"] and has_motion_asset)
        pub["route"] = estimate_i2v(slug, shot)
        from tools.drama_lip import estimate_lip
        from tools.drama_styles import estimate_image

        pub["image"] = estimate_image(slug, shot, episode=episode)

        pub["lip"] = estimate_lip(slug, shot)
        from tools.drama_keys import estimate_keys

        pub["keys"] = []
        for item in shot.get("keys") or []:
            if not isinstance(item, dict):
                continue
            meta = _asset_meta(str(item.get("file") or ""))
            cands = []
            for cand in item.get("candidates") or []:
                if not isinstance(cand, dict):
                    continue
                cm = _asset_meta(str(cand.get("path") or ""))
                cands.append(
                    {
                        **cand,
                        "url": cm.get("url"),
                        "exists": cm["exists"],
                        "chosen": cand.get("id") == item.get("chosen"),
                    }
                )
            pub["keys"].append({**item, "url": meta.get("url"), "exists": meta["exists"], "candidates": cands})
        pub["keys_gate"] = estimate_keys(slug, shot)
        pub["qc"] = shot.get("qc") if isinstance(shot.get("qc"), dict) else None
    return pub


def list_projects() -> dict[str, Any]:
    root = resolve_safe(_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        if child.name.startswith("_"):
            continue
        data = load_project_file(child.name)
        if not data:
            continue
        if data.get("archived") or data.get("hidden"):
            continue
        episodes = data.get("episodes") or []
        videos = data.get("videos") or []
        sid = str(data.get("slug") or child.name)
        items.append(
            {
                "slug": sid,
                "title": data.get("title") or child.name,
                "logline": data.get("logline") or "",
                "episodes": len(episodes),
                "videos": len(videos),
                "path": _rel(child.name),
                "updated_at": data.get("updated_at"),
                "created_at": data.get("created_at"),
                "substance": project_substance_score(sid),
            }
        )
    # 同名剧只保留内容最全的一份，避免侧栏堆出多个《嫦娥奔月》
    winners: dict[str, dict[str, Any]] = {}
    for item in items:
        key = normalize_project_title(item.get("title")) or str(item.get("slug") or "")
        prev = winners.get(key)
        if prev is None or _project_rank(item) > _project_rank(prev):
            winners[key] = item
    out = list(winners.values())
    out.sort(key=lambda x: str(x.get("updated_at") or x.get("created_at") or ""), reverse=True)
    return {"workspace": str(workspace_root()), "count": len(out), "projects": out}


def _project_rank(item: dict[str, Any]) -> tuple:
    return (
        int(item.get("substance") or 0),
        str(item.get("updated_at") or item.get("created_at") or ""),
    )


def get_project(slug: str) -> dict[str, Any]:
    project = load_project(slug)
    slug = str(project.get("slug") or slug)
    bible = _read_text(_rel(slug, "bible.md"))
    outline = _read_text(_rel(slug, "outline.md"))
    episodes: list[dict[str, Any]] = []
    for ep in project.get("episodes") or []:
        try:
            n = int(ep.get("n") or 0)
        except (TypeError, ValueError):
            continue
        if n < 1:
            continue
        video_rel = _rel(slug, "videos", f"ep{n:02d}.mp4")
        video = _asset_meta(video_rel)
        shots_rel = json_rel(slug, n)
        doc = load_doc(slug, n)
        episodes.append(
            {
                "n": n,
                "title": ep.get("title") or f"第{n}集",
                "seconds": ep.get("seconds"),
                "path": ep.get("path") or _rel(slug, "episodes", f"ep{n:02d}.md"),
                "shots_json": shots_rel if doc else None,
                "shot_count": len(doc.get("shots") or []) if doc else 0,
                "video_path": video_rel if video["exists"] else None,
                "play_url": video.get("url") if video["exists"] else None,
            }
        )
    return {
        "slug": slug,
        "path": _rel(slug),
        "project": project,
        "bible": bible,
        "outline": outline,
        "episodes": episodes,
        "cameras": list(CAMERAS),
        "characters": list_characters(slug),
        "voices": public_voices(slug),
    }


def project_manual_voice(slug: str) -> bool:
    """项目级开关：手动配音（默认关 → Seedance generate_audio）。"""
    try:
        project = load_project(slug)
    except Exception:
        return False
    return bool(project.get("manual_voice"))


def patch_project(slug: str, patch: dict[str, Any]) -> dict[str, Any]:
    project = load_project(slug)
    if "title" in patch and patch["title"] is not None:
        title = str(patch["title"]).strip()
        if not title:
            raise DramaBadRequest("title 不能为空")
        project["title"] = title
    if "logline" in patch and patch["logline"] is not None:
        project["logline"] = str(patch["logline"]).strip()
    if "manual_voice" in patch and patch["manual_voice"] is not None:
        project["manual_voice"] = bool(patch["manual_voice"])
    save_project(slug, project)
    return get_project(slug)


def create_project(
    *,
    title: str = "",
    logline: str = "",
    slug: str = "",
) -> dict[str, Any]:
    """Workbench: create a blank drama project for step-by-step production."""
    from tools.drama_common import utc_now
    from tools.drama_produce import ensure_hq_preset, suggest_project_slug

    given_title = str(title or "").strip().strip("《》\"'“”‘’") or "未命名漫剧"
    logline_text = str(logline or "").strip()

    if slug:
        sid = parse_slug(slug)
    else:
        sid = parse_slug(suggest_project_slug(logline_text or given_title, given_title))

    base = sid
    n = 2
    while load_drama_project_file(sid):
        suffix = f"-{n}"
        sid = parse_slug(f"{base[: max(1, 40 - len(suffix))]}{suffix}")
        n += 1
        if n > 99:
            raise DramaBadRequest("无法生成唯一项目 slug，请指定不同标题")

    now = utc_now()
    project = {
        "slug": sid,
        "title": given_title,
        "logline": logline_text,
        "aspect": "9:16",
        # 默认关：图生视频用 Seedance 自带声；打开后才走手动 TTS
        "manual_voice": False,
        "created_at": now,
        "updated_at": now,
        "episodes": [],
    }
    save_project(sid, project)
    ensure_hq_preset(sid)
    resolve_safe(f"dramas/{sid}/episodes").mkdir(parents=True, exist_ok=True)
    readme = resolve_safe(f"dramas/{sid}/README.md")
    if not readme.is_file():
        readme.write_text(
            f"# {given_title}\n\n"
            f"- slug: `{sid}`\n"
            f"- 画幅: 9:16\n"
            f"- 一句话: {logline_text or '（待写）'}\n\n"
            f"目录：`bible.md` · `outline.md` · `episodes/` · `characters.json`\n",
            encoding="utf-8",
        )
    return get_project(sid)


def _force_rmtree(path: Path, *, retries: int = 6) -> str:
    """Delete a directory tree; on Windows lock failures quarantine under ``_trash/``.

    Returns ``deleted`` | ``quarantined`` | ``missing``.
    """
    import os
    import stat
    import time
    from pathlib import Path as _P

    path = _P(path)
    if not path.exists():
        return "missing"

    def _unlock(func, p, _exc_info) -> None:
        try:
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
            func(p)
        except Exception:
            pass

    last_err: Exception | None = None
    for i in range(max(1, int(retries))):
        if not path.exists():
            return "deleted"
        try:
            shutil.rmtree(path, onerror=_unlock)
            if not path.exists():
                return "deleted"
        except OSError as e:
            last_err = e
        time.sleep(0.15 * (i + 1))

    # Still there: rename aside so slug is free for recreate.
    trash_root = path.parent / "_trash"
    try:
        trash_root.mkdir(parents=True, exist_ok=True)
        dest = trash_root / f"{path.name}__{int(time.time())}"
        # Avoid collision
        n = 0
        while dest.exists():
            n += 1
            dest = trash_root / f"{path.name}__{int(time.time())}_{n}"
        path.rename(dest)
        return "quarantined"
    except OSError as e:
        detail = f"{last_err or e}"
        raise OSError(f"无法删除项目目录 {path.name}：{detail}") from e


def remove_project(slug: str, *, purge_same_title: bool = True) -> dict[str, Any]:
    """彻底删除漫剧项目：队列任务 + 磁盘目录（含同名/同梗概副本）。

    Windows 下若文件被占用：重试 → 仍失败则隔离到 ``dramas/_trash/``，
    保证原 slug / 标题可立刻重新立项，不会再报「项目已存在」。
    """
    slug = parse_slug(slug)
    # 软读：目录在但 project.json 损坏/缺失时也要能清掉孤儿树
    project = load_project_file(slug) or {}
    title = str(project.get("title") or "").strip()
    logline = str(project.get("logline") or "").strip()
    title_key = normalize_project_title(title)
    from tools.drama_queue import drama_jobs

    targets: list[str] = [slug]
    root = resolve_safe(_ROOT)
    if root.is_dir() and purge_same_title:
        for child in root.iterdir():
            if not child.is_dir() or child.name.startswith("_"):
                continue
            other_slug = child.name
            if other_slug in targets:
                continue
            data = load_project_file(other_slug)
            if not data:
                # 无 project.json 的孤儿目录：slug 前缀撞车也清（如 yugong-yishan-2）
                continue
            other_title = normalize_project_title(str(data.get("title") or ""))
            other_log = str(data.get("logline") or "").strip()
            same_title = bool(title_key) and other_title == title_key
            same_log = bool(logline) and len(logline) >= 8 and other_log == logline
            if same_title or same_log:
                targets.append(other_slug)

    # 标题/梗概索引再补一轮（防侧栏去重漏掉的副本）
    if purge_same_title and title_key:
        hit = find_project_slug_by_title(title)
        if hit and hit not in targets:
            targets.append(hit)
    if purge_same_title and logline and len(logline) >= 8:
        hit = find_project_slug_by_logline(logline)
        if hit and hit not in targets:
            targets.append(hit)

    removed: list[str] = []
    quarantined: list[str] = []
    jobs_removed = 0
    errors: list[str] = []

    for sid in targets:
        try:
            jobs_removed += int(drama_jobs.remove_slug(sid, wait_s=2.5) or 0)
        except Exception as e:
            errors.append(f"{sid}:queue {e}")
        try:
            target = resolve_safe(_rel(sid))
            root_path = resolve_safe(_ROOT)
            if target == root_path or root_path not in target.parents:
                raise DramaBadRequest("非法项目路径，拒绝删除")
            if not target.exists():
                removed.append(sid)
                continue
            mode = _force_rmtree(target)
            if mode == "quarantined":
                quarantined.append(sid)
            removed.append(sid)
            # 双检：原路径不得再有 project.json
            if (target / "project.json").is_file():
                raise OSError("删除后 project.json 仍在")
        except DramaBadRequest:
            raise
        except OSError as e:
            errors.append(f"{sid}: {e}")

    if not removed:
        detail = "；".join(errors) if errors else "项目目录不存在或正在被占用"
        raise DramaBadRequest(f"删除失败：{detail}")

    memory_scrubbed = False
    try:
        from agent.memory_store import scrub_memory_terms

        terms = [title, logline, *removed]
        scrub_memory_terms(*[t for t in terms if t])
        memory_scrubbed = True
    except Exception:
        memory_scrubbed = False

    return {
        "ok": True,
        "slug": slug,
        "removed": removed,
        "quarantined": quarantined,
        "path": _rel(slug),
        "jobs_removed": jobs_removed,
        "memory_scrubbed": memory_scrubbed,
        "errors": errors,
    }


def _public_coverage(doc: dict[str, Any] | None) -> dict[str, Any]:
    from tools.drama_director import public_coverage

    return public_coverage(doc)


def _public_qc(doc: dict[str, Any] | None) -> dict[str, Any]:
    from tools.drama_qc import public_episode_qc

    return public_episode_qc(doc)


def _script_headers_match_doc(script: str | None, doc: dict[str, Any] | None) -> bool:
    """False when markdown Shot headers disagree with shots.json timing."""
    if not doc or script is None:
        return True
    from tools.drama_video import parse_episode_markdown

    parsed = parse_episode_markdown(script)
    by_n = {int(s.get("n") or 0): s for s in (doc.get("shots") or [])}
    for ps in parsed.get("shots") or []:
        n = int(ps.get("n") or 0)
        shot = by_n.get(n)
        if not shot:
            continue
        try:
            if abs(float(ps.get("duration") or 0) - float(shot.get("duration") or 0)) > 0.05:
                return False
            if abs(float(ps.get("start") or 0) - float(shot.get("start") or 0)) > 0.05:
                return False
            if abs(float(ps.get("end") or 0) - float(shot.get("end") or 0)) > 0.05:
                return False
        except (TypeError, ValueError):
            return False
        if str(ps.get("timing") or "").strip() != str(shot.get("timing") or "").strip():
            return False
    return True


def doc_timings_need_sync(doc: dict[str, Any] | None, script: str | None = None) -> bool:
    if not doc:
        return False
    if doc_timings_drift(doc):
        return True
    return not _script_headers_match_doc(script, doc)


def write_script_timings_from_doc(script: str, doc: dict[str, Any]) -> str:
    """Rewrite every ### Shot N (…) header + episode 时长 from shots.json."""
    from tools.drama_video import patch_episode_meta_duration, patch_shot_in_markdown

    updated = str(script or "")
    for shot in sorted((doc.get("shots") or []), key=lambda s: int(s.get("n") or 0)):
        n = int(shot.get("n") or 0)
        if n <= 0:
            continue
        updated = patch_shot_in_markdown(
            updated,
            n,
            {
                "timing": shot.get("timing"),
                "start": shot.get("start"),
                "end": shot.get("end"),
                "duration": shot.get("duration"),
            },
        )
    return patch_episode_meta_duration(updated, episode_total_seconds(doc))


def sync_episode_timings(
    slug: str,
    episode: int,
    doc: dict[str, Any],
    *,
    script_rel: str | None = None,
    script: str | None = None,
) -> tuple[dict[str, Any], str | None]:
    """Reconcile timings from duration, persist shots.json + markdown headers."""
    reconcile_doc_timings(doc)
    save_doc(doc)
    rel = script_rel or str(doc.get("script_path") or _rel(slug, "episodes", f"ep{int(episode):02d}.md"))
    text = script if script is not None else _read_text(rel)
    if text is not None:
        updated = write_script_timings_from_doc(text, doc)
        if updated != text:
            _write_text(rel, updated.rstrip() + "\n")
        text = updated
    return doc, text


def get_episode(slug: str, episode: int) -> dict[str, Any]:
    project = load_project(slug)
    n = parse_episode(episode)
    slug = str(project.get("slug") or slug)
    ep_meta = next(
        (e for e in (project.get("episodes") or []) if int(e.get("n") or 0) == n),
        {},
    )
    script_rel = str(ep_meta.get("path") or _rel(slug, "episodes", f"ep{n:02d}.md"))
    script = _read_text(script_rel)
    # series_pack SSOT：无可用 ep.md 时从 shots / pack 合成，避免「没有分集剧本」误拦
    try:
        from tools.drama_layout import resolve_episode_script

        resolved = resolve_episode_script(slug, n, existing=script, persist=False)
        if resolved:
            script = resolved
    except Exception:
        pass
    doc = load_doc(slug, n)
    # Heal duration↔timing drift so UI / script / shots.json stay globally consistent.
    if doc and doc_timings_need_sync(doc, script):
        doc, script = sync_episode_timings(slug, n, doc, script_rel=script_rel, script=script)
        for ep in project.get("episodes") or []:
            if int(ep.get("n") or 0) == n:
                from tools.drama_shots import episode_total_seconds

                total = episode_total_seconds(doc)
                if total > 0:
                    ep["seconds"] = int(round(total))
                break
        try:
            save_project(slug, project)
        except Exception:
            pass
        ep_meta = next(
            (e for e in (project.get("episodes") or []) if int(e.get("n") or 0) == n),
            ep_meta,
        )
    video_rel = _rel(slug, "videos", f"ep{n:02d}.mp4")
    video = _asset_meta(video_rel)
    shots = [enrich_shot(s, slug=slug, episode=n) for s in (doc.get("shots") or [])] if doc else []
    from tools.drama_video import _probe_duration

    timeline = public_timeline(doc, probe_duration=_probe_duration) if doc else None
    from tools.drama_styles import effective_models, list_styles, public_style

    models = effective_models(slug, episode=n, doc=doc)
    from tools.drama_audio import public_mix

    episode_status = ""
    episode_status_path = ""
    try:
        from tools.drama_episode_status import build_episode_status, write_episode_status

        episode_status = build_episode_status(slug, n, doc)
        episode_status_path = write_episode_status(slug, n, doc)
    except Exception:
        pass

    return {
        "slug": slug,
        "episode": n,
        "title": ep_meta.get("title") or (doc or {}).get("title") or f"第{n}集",
        "seconds": ep_meta.get("seconds"),
        "script_path": script_rel,
        "script": script,
        "shots_json": json_rel(slug, n) if doc else None,
        "shots": shots,
        "count": len(shots),
        "timeline": timeline,
        "mix": public_mix(slug, n),
        "mix_mode": (doc or {}).get("mix"),
        "video_path": video_rel if video["exists"] else None,
        "play_url": video.get("url") if video["exists"] else None,
        "episode_status": episode_status,
        "episode_status_path": episode_status_path,
        "cameras": list(CAMERAS),
        "characters": list_characters(slug),
        "voices": public_voices(slug),
        "layer_ids": ["scene", "overlay", "voice", "motion", "lip", "clip"],
        "transitions": list(TRANSITIONS),
        "i2v_modes": list(I2V_MODES),
        "shot_kinds": list(SHOT_KINDS),
        "shot_sizes": list(SHOT_SIZES),
        "models": public_models(models),
        "cost": estimate_episode_i2v(slug, (doc or {}).get("shots") or [], episode=n, doc=doc),
        "budget": _budget_state(slug, episode=n, shots=(doc or {}).get("shots") or []),
        "style_id": str((doc or {}).get("style_id") or ""),
        "styles": [public_style(item) for item in list_styles(slug)],
        "coverage": _public_coverage(doc),
        "qc": _public_qc(doc),
        "updated_at": (doc or {}).get("updated_at"),
    }


def patch_episode(slug: str, episode: int, patch: dict[str, Any]) -> dict[str, Any]:
    project = load_project(slug)
    n = parse_episode(episode)
    episodes = list(project.get("episodes") or [])
    found = False
    for ep in episodes:
        if int(ep.get("n") or 0) != n:
            continue
        found = True
        if "title" in patch and patch["title"] is not None:
            title = str(patch["title"]).strip()
            if not title:
                raise DramaBadRequest("title 不能为空")
            ep["title"] = title
        if "seconds" in patch and patch["seconds"] is not None:
            try:
                seconds = int(patch["seconds"])
            except (TypeError, ValueError) as e:
                raise DramaBadRequest("seconds 须为整数") from e
            ep["seconds"] = max(15, min(seconds, 90))
        break
    if not found:
        raise DramaNotFound(f"该集不存在：{n}")
    project["episodes"] = episodes
    save_project(slug, project)
    if "title" in patch and patch["title"] is not None:
        doc = load_doc(slug, n)
        if doc is not None:
            doc["title"] = str(patch["title"]).strip()
            save_doc(doc)
    return get_episode(slug, n)


def _ensure_shots_doc(slug: str, episode: int) -> dict[str, Any]:
    doc = load_doc(slug, episode)
    if doc is not None and doc.get("shots"):
        return doc
    try:
        from tools.drama_layout import ensure_episode_ready

        return ensure_episode_ready(slug, episode)
    except FileNotFoundError as e:
        ep = get_episode(slug, episode)
        script = ep.get("script")
        if not script:
            raise DramaNotFound("没有 shots.json，也没有分集剧本。请先 parse_shots 或 save_episode") from e
        from tools.drama_video import sync_shots_doc

        return sync_shots_doc(slug, episode, str(script), title=str(ep.get("title") or ""))


def patch_shot(slug: str, episode: int, shot_n: int, patch: dict[str, Any]) -> dict[str, Any]:
    slug = parse_slug(slug)
    n = parse_episode(episode)
    shot_n = parse_shot_n(shot_n)
    allowed = ("画面", "字幕", "旁白", "对白", "角色", "camera", "timing", "duration", "trim_in", "trim_out", "volume", "transition", "i2v", "i2v_ladder", "i2v_source", "kind", "size", "speaker", "voice")
    body = {k: patch[k] for k in allowed if k in patch and patch[k] is not None}
    # legacy 对白 → 字幕；若同时带旧「字幕」则视为旁白
    if "对白" in body:
        dialogue = body.pop("对白")
        if "旁白" not in body and "字幕" in body:
            body["旁白"] = body.pop("字幕")
        body["字幕"] = dialogue
    # Allow clearing optional overrides with empty string
    for key in ("i2v_ladder", "i2v_source"):
        if key in patch and patch[key] is not None and key not in body:
            body[key] = patch[key]
    timeline_keys = ("trim_in", "trim_out", "volume", "transition")
    timeline_body = {k: body.pop(k) for k in timeline_keys if k in body}
    has_lock = any(patch.get(k) is not None for k in ("locked", "lock", "unlock") if k in patch)
    if "duration" in body:
        try:
            body["duration"] = round_timing(body["duration"], minimum=MIN_PLAY_SEC)
        except (TypeError, ValueError) as e:
            raise DramaBadRequest("duration 须为数字") from e
        if body["duration"] <= 0:
            raise DramaBadRequest("duration 须大于 0")
    if "camera" in body:
        cam = str(body["camera"]).strip()
        if cam and cam not in CAMERAS:
            raise DramaBadRequest(f"未知运镜：{cam}，可选 {', '.join(CAMERAS)}")
        body["camera"] = cam
    if "角色" in body:
        body["角色"] = normalize_roles(body["角色"])
    if "transition" in timeline_body:
        t = str(timeline_body["transition"]).strip() or "auto"
        if t not in TRANSITIONS:
            raise DramaBadRequest(f"未知转场：{t}，可选 {', '.join(TRANSITIONS)}")
    if "i2v" in body:
        body["i2v"] = normalize_i2v_mode(body["i2v"])
    if "i2v_ladder" in body:
        from tools.drama_models import normalize_ladder

        raw_ladder = str(body.get("i2v_ladder") or "").strip()
        if raw_ladder:
            ladder = normalize_ladder(raw_ladder)
            if not ladder:
                raise DramaBadRequest("i2v_ladder 须为 L0–L4")
            body["i2v_ladder"] = ladder
        else:
            body["i2v_ladder"] = ""
    if "i2v_source" in body:
        src = str(body.get("i2v_source") or "").strip().lower()
        if src and src not in ("ai", "keys", "fallback", "none"):
            raise DramaBadRequest("i2v_source 须为 ai / keys / fallback / 空")
        body["i2v_source"] = "" if src in ("", "none") else src
    if not body and not timeline_body and not has_lock:
        raise DramaBadRequest("没有可更新的字段（画面 / 字幕 / 旁白 / 角色 / camera / duration / kind / speaker / 时间线 / locked）")

    doc = _ensure_shots_doc(slug, n)
    _take_snapshot(slug, n, doc, tag="patch_shot")
    shot = find_shot(doc, shot_n)
    if shot is None:
        raise DramaNotFound(f"找不到 Shot {shot_n}")
    if has_lock:
        set_shot_locks(
            shot,
            locked=patch.get("locked") if "locked" in patch else None,
            lock=patch.get("lock"),
            unlock=patch.get("unlock"),
        )
    dirty: list[str] = []
    timing_touched = any(k in body for k in ("duration", "timing", "start", "end"))
    did_retime = False
    if body:
        if "shot" in (shot.get("locked") or []):
            dirty = []
        else:
            try:
                dirty = apply_patch(shot, body)
            except ValueError as e:
                raise DramaBadRequest(str(e)) from e
            if timing_touched:
                cascade_shot_timings(doc, from_n=shot_n)
                did_retime = True
                body = {
                    **body,
                    "timing": shot.get("timing"),
                    "start": shot.get("start"),
                    "end": shot.get("end"),
                    "duration": shot.get("duration"),
                }
            script_rel = str(doc.get("script_path") or _rel(slug, "episodes", f"ep{n:02d}.md"))
            script = _read_text(script_rel)
            if script is not None:
                from tools.drama_video import patch_shot_in_markdown

                if did_retime:
                    updated = write_script_timings_from_doc(script, doc)
                else:
                    updated = patch_shot_in_markdown(script, shot_n, body)
                if updated != script:
                    _write_text(script_rel, updated.rstrip() + "\n")
    if timeline_body:
        apply_timeline_patch(shot, timeline_body)
    if any(k in body for k in ("i2v", "i2v_ladder", "i2v_source")):
        locked = set(shot.get("locked") or [])
        dirty_list = list(shot.get("dirty") or [])
        for layer in ("motion", "clip"):
            if layer not in locked and layer not in dirty_list:
                dirty_list.append(layer)
        shot["dirty"] = dirty_list
        if dirty_list:
            shot["status"] = "dirty"
    save_doc(doc)

    if did_retime:
        total = episode_total_seconds(doc)
        try:
            project = load_project(slug)
            for ep in project.get("episodes") or []:
                if int(ep.get("n") or 0) == n:
                    ep["seconds"] = int(round(total)) if total else ep.get("seconds")
                    break
            save_project(slug, project)
        except Exception:
            pass

    return {
        "slug": slug,
        "episode": n,
        "shot": enrich_shot(shot, slug=slug, episode=n),
        "shots": [enrich_shot(s, slug=slug, episode=n) for s in (doc.get("shots") or [])],
        "dirty": dirty or list(shot.get("dirty") or []),
        "locked": list(shot.get("locked") or []),
        "shots_json": json_rel(slug, n),
        "retimed": did_retime,
    }


_BATCH_FIELDS = ("camera", "voice", "kind", "i2v", "speaker")


def patch_shots(slug: str, episode: int, shot_ns: list[int], field: str, value: Any) -> dict[str, Any]:
    """R5: batch edit one field across multiple shots (camera / voice / kind / i2v / speaker)."""
    slug = parse_slug(slug)
    n = parse_episode(episode)
    field = str(field or "").strip()
    if field not in _BATCH_FIELDS:
        raise DramaBadRequest(f"不支持的批量字段：{field}，可选 {', '.join(_BATCH_FIELDS)}")

    shots_wanted = sorted({parse_shot_n(x) for x in (shot_ns or [])})
    if not shots_wanted:
        raise DramaBadRequest("需要至少一个 shot 编号")
    if len(shots_wanted) > 99:
        raise DramaBadRequest("批量操作最多 99 镜")

    doc = _ensure_shots_doc(slug, n)
    _take_snapshot(slug, n, doc, tag="patch_shots")

    if field == "kind":
        from tools.drama_models import normalize_kind

        kind = normalize_kind(value)
        if not kind:
            raise DramaBadRequest(f"未知镜头类型：{value}")
        patch_value = kind
    elif field == "i2v":
        patch_value = normalize_i2v_mode(value)
    else:
        patch_value = str(value or "").strip()

    updated: list[int] = []
    skipped_locked: list[int] = []
    changed: list[int] = []
    for shot in doc.get("shots") or []:
        shot_num = int(shot.get("n") or 0)
        if shot_num not in shots_wanted:
            continue
        locked = set(shot.get("locked") or [])
        blocked = {"shot", field} & locked
        if blocked:
            skipped_locked.append(shot_num)
            continue
        before = shot.get(field)
        try:
            apply_patch(shot, {field: patch_value})
        except ValueError as e:
            raise DramaBadRequest(str(e)) from e
        changed.append(shot_num)
        if str(before or "") != str(shot.get(field) or ""):
            updated.append(shot_num)

    save_doc(doc)
    return {
        "slug": slug,
        "episode": n,
        "field": field,
        "changed": changed,
        "updated": updated,
        "skipped_locked": skipped_locked,
        "shot": None,
        "shots": [enrich_shot(s, slug=slug, episode=n) for s in (doc.get("shots") or [])],
        "shots_json": json_rel(slug, n),
    }


def rerender_one_shot(slug: str, episode: int, shot_n: int, layers: list[str] | None = None) -> dict[str, Any]:
    slug = parse_slug(slug)
    n = parse_episode(episode)
    shot_n = parse_shot_n(shot_n)
    from tools.drama_video import rerender_shot

    return rerender_shot(slug, n, shot_n, layers=layers)


def _rebuild_clip_keep_voice(
    slug: str,
    episode: int,
    shot_n: int,
    doc: dict[str, Any],
    shot: dict[str, Any],
    *,
    sync: bool = True,
) -> dict[str, Any]:
    from tools.drama_video import ffmpeg_available, rerender_shot

    save_doc(doc)
    locked = set(shot.get("locked") or [])
    if "clip" in locked:
        return {"rebuilt_layers": [], "skipped_layers": ["clip"], "assemble": "unchanged"}

    def _mark_clip_dirty() -> dict[str, Any]:
        dirty = list(shot.get("dirty") or [])
        if "clip" not in dirty:
            dirty.append("clip")
        shot["dirty"] = dirty
        shot["status"] = "dirty"
        save_doc(doc)
        hint = "未找到 ffmpeg，已换图，成片待重渲" if not ffmpeg_available() else "画面已换，成片待重渲"
        return {"rebuilt_layers": [], "skipped_layers": ["clip"], "assemble": "unchanged", "hint": hint}

    if not sync or not ffmpeg_available():
        return _mark_clip_dirty()
    return rerender_shot(slug, episode, shot_n, layers=["clip"])


def upload_shot_scene(slug: str, episode: int, shot_n: int, data: bytes) -> dict[str, Any]:
    slug = parse_slug(slug)
    n = parse_episode(episode)
    shot_n = parse_shot_n(shot_n)
    doc = _ensure_shots_doc(slug, n)
    shot = find_shot(doc, shot_n)
    if shot is None:
        raise DramaNotFound(f"找不到 Shot {shot_n}")
    _take_snapshot(slug, n, doc, tag="scene")
    if "shot" in (shot.get("locked") or []):
        raise DramaBadRequest("整镜已锁定，不能覆盖画面")
    if "scene" in (shot.get("locked") or []):
        raise DramaBadRequest("画面已锁定，不能覆盖画面（请先解锁）")
    if not data:
        raise DramaBadRequest("图片不能为空")
    from tools.drama_shots import shot_assets
    from tools.drama_video import _write_scene_png

    scene_rel = str((shot.get("assets") or {}).get("scene") or shot_assets(slug, n, shot_n)["scene"])
    shot.setdefault("assets", {}).setdefault("scene", scene_rel)
    try:
        _write_scene_png(data, resolve_safe(scene_rel))
    except Exception as e:
        raise DramaBadRequest("无法读取图片") from e
    shot["scene_source"] = "upload"
    set_shot_locks(shot, lock=["scene"])
    result = _rebuild_clip_keep_voice(slug, n, shot_n, doc, shot)
    payload = {
        "slug": slug,
        "episode": n,
        "shot": enrich_shot(find_shot(load_doc(slug, n) or doc, shot_n) or shot, slug=slug),
        "voice_rebuilt": False,
        "rebuilt_layers": result.get("rebuilt_layers") or result.get("rebuilt") or [],
    }
    payload.update({k: result[k] for k in ("assemble", "hint") if k in result})
    return payload


def get_timeline(slug: str, episode: int) -> dict[str, Any]:
    slug = parse_slug(slug)
    n = parse_episode(episode)
    doc = _ensure_shots_doc(slug, n)
    from tools.drama_video import _probe_duration

    return {
        "slug": slug,
        "episode": n,
        "timeline": public_timeline(doc, probe_duration=_probe_duration),
        "play_url": _asset_meta(_rel(slug, "videos", f"ep{n:02d}.mp4")).get("url"),
    }


def patch_timeline(slug: str, episode: int, body: dict[str, Any]) -> dict[str, Any]:
    slug = parse_slug(slug)
    n = parse_episode(episode)
    doc = _ensure_shots_doc(slug, n)
    patch_timeline_doc(doc, body)
    save_doc(doc)
    from tools.drama_video import _probe_duration

    return {
        "slug": slug,
        "episode": n,
        "timeline": public_timeline(doc, probe_duration=_probe_duration),
    }


def export_episode(
    slug: str,
    episode: int,
    *,
    background: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """Assemble + mix episode. QC hard-gate unless force=True (workbench only)."""
    slug = parse_slug(slug)
    n = parse_episode(episode)
    if background:
        return enqueue_job(slug, n, "export", params={"force": bool(force)})
    doc = _ensure_shots_doc(slug, n)
    from tools.drama_audio import assert_export_licensed, load_mix
    from tools.drama_quality import (
        assert_loudness_after_export,
        assert_shots_qc_for_export,
        assert_studio_bgm,
    )
    from tools.drama_shots import LAYERS, cascade_shot_timings, save_doc
    from tools.drama_video import assemble_episode, ffmpeg_available, render_shot_layers
    from tools.workspace import resolve_safe

    if not ffmpeg_available():
        raise DramaBadRequest("未找到 ffmpeg，无法导出整集")
    try:
        assert_export_licensed(slug, load_mix(slug, n))
        assert_studio_bgm(slug, n, force=bool(force))
        assert_shots_qc_for_export(slug, n, doc, force=bool(force))
        # 导出前重渲：脏层全量处理；未锁镜头至少刷新 overlay+clip，
        # 避免声音页 CSS 预览正确、成片仍是旧旁白/旧时长。
        ep_title = str(doc.get("title") or f"第{n}集")
        for shot in doc.get("shots") or []:
            locked = set(shot.get("locked") or [])
            if "shot" in locked:
                continue
            dirty = [layer for layer in (shot.get("dirty") or []) if layer]
            layers = list(dict.fromkeys(dirty))
            if "clip" not in locked:
                for layer in ("overlay", "clip"):
                    if layer not in layers:
                        layers.append(layer)
            clip_rel = str((shot.get("assets") or {}).get("clip") or "").strip()
            clip_ok = False
            if clip_rel:
                try:
                    clip_ok = resolve_safe(clip_rel).is_file()
                except ValueError:
                    clip_ok = False
            if not layers and not clip_ok:
                layers = [layer for layer in LAYERS if layer != "scene"]
            if not layers:
                continue
            if "clip" not in layers and any(
                layer in layers for layer in ("scene", "overlay", "voice", "lip", "motion")
            ):
                layers = [*layers, "clip"]
            render_shot_layers(slug, n, shot, layers, title=ep_title)
            save_doc(doc)
        cascade_shot_timings(doc)
        save_doc(doc)
        mode = assemble_episode(doc)
        assert_loudness_after_export(slug, n, force=bool(force))
    except ValueError as e:
        raise DramaBadRequest(str(e)) from e
    except RuntimeError as e:
        raise DramaBadRequest(str(e)) from e
    ep = get_episode(slug, n)
    ep["assemble"] = mode
    ep["mix_mode"] = (load_doc(slug, n) or {}).get("mix")
    ep["export_forced"] = bool(force)
    return ep


def produce_episode(
    slug: str,
    episode: int,
    *,
    background: bool = False,
    force: bool = False,
    style_id: str = "",
    catalog_bgm: str = "",
) -> dict[str, Any]:
    """One-shot HQ pipeline: cast → scene/voice/lip → I2V → BGM → export mp4."""
    slug = parse_slug(slug)
    n = parse_episode(episode)
    _ensure_shots_doc(slug, n)
    params: dict[str, Any] = {"force": force}
    if style_id:
        params["style_id"] = style_id
    if catalog_bgm:
        params["catalog_bgm"] = catalog_bgm
    if background:
        return enqueue_job(slug, n, "produce_episode", params=params)
    from tools.drama_produce import produce_episode_hq

    _assert_budget(slug, n)
    kwargs: dict[str, Any] = {
        "force": force,
        "style_id": style_id,
        "catalog_bgm": catalog_bgm or "rebirth_resolve",
        "allow_qc_fail_export": False,
    }
    try:
        result = produce_episode_hq(slug, n, **kwargs)
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        raise DramaBadRequest(str(e)) from e
    project = load_project(slug)
    if project:
        videos = [v for v in (project.get("videos") or []) if int(v.get("n") or 0) != n]
        videos.append(
            {
                "n": n,
                "path": result.get("path") or result.get("video_path"),
                "play_url": result.get("play_url"),
                "shots": result.get("count") or result.get("shots"),
                "bytes": result.get("bytes") or 0,
                "shots_json": result.get("shots_json"),
            }
        )
        videos.sort(key=lambda v: int(v.get("n") or 0))
        project["videos"] = videos
        save_project(slug, project)
    return result


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
    catalog_bgm: str = "",
) -> dict[str, Any]:
    """One sentence → bible/outline/episode(s) + HQ produce."""
    from tools.drama_produce import create_from_premise as _create

    return _create(
        premise,
        slug=slug,
        title=title,
        episode=episode,
        episode_count=episode_count,
        seconds=seconds,
        overwrite=overwrite,
        background=background,
        force=force,
        style_id=style_id,
        catalog_bgm=catalog_bgm or "rebirth_resolve",
    )


def get_mix(slug: str, episode: int) -> dict[str, Any]:
    from tools.drama_audio import public_mix

    load_project(slug)
    slug = parse_slug(slug)
    n = parse_episode(episode)
    return {"slug": slug, "episode": n, **public_mix(slug, n)}


def patch_mix_episode(slug: str, episode: int, body: dict[str, Any]) -> dict[str, Any]:
    from tools.drama_audio import patch_mix

    load_project(slug)
    slug = parse_slug(slug)
    n = parse_episode(episode)
    try:
        patch_mix(slug, n, body or {})
    except ValueError as e:
        raise DramaBadRequest(str(e)) from e
    return get_episode(slug, n)


def upload_episode_bgm(
    slug: str,
    episode: int,
    data: bytes,
    *,
    filename: str = "bgm.mp3",
    license_ok: bool = False,
    title: str = "",
) -> dict[str, Any]:
    from tools.drama_audio import save_uploaded_bgm

    load_project(slug)
    slug = parse_slug(slug)
    n = parse_episode(episode)
    try:
        save_uploaded_bgm(slug, n, data, filename=filename, license_ok=license_ok, title=title)
    except ValueError as e:
        raise DramaBadRequest(str(e)) from e
    return get_episode(slug, n)


def mix_episode(slug: str, episode: int, *, background: bool = False) -> dict[str, Any]:
    """Remix epNN.mp4 from VO stem + mix.json. Does not rebuild per-shot clips."""
    slug = parse_slug(slug)
    n = parse_episode(episode)
    if background:
        return enqueue_job(slug, n, "export")
    from tools.drama_audio import mix_assembled, vo_stem_rel
    from tools.drama_video import assemble_episode, ffmpeg_available, output_rel

    if not ffmpeg_available():
        raise DramaBadRequest("未找到 ffmpeg，无法混音")
    stem = resolve_safe(vo_stem_rel(slug, n))
    dest = resolve_safe(output_rel(slug, n))
    try:
        if not stem.is_file():
            doc = _ensure_shots_doc(slug, n)
            assemble_episode(doc)
        else:
            mode = mix_assembled(slug, n, stem=stem, dest=dest)
            doc = load_doc(slug, n)
            if doc:
                doc["mix"] = mode
                save_doc(doc)
    except ValueError as e:
        raise DramaBadRequest(str(e)) from e
    ep = get_episode(slug, n)
    ep["mix_mode"] = (load_doc(slug, n) or {}).get("mix")
    return ep


def preview_script(slug: str, episode: int, content: str) -> dict[str, Any]:
    slug = parse_slug(slug)
    n = parse_episode(episode)
    text = str(content or "")
    if not text.strip():
        raise DramaBadRequest("剧本不能为空")
    from tools.drama_shots import merge_from_parsed
    from tools.drama_video import parse_episode_markdown

    existing = load_doc(slug, n)
    parsed = parse_episode_markdown(text)
    if not parsed.get("shots"):
        raise DramaBadRequest("剧本里没有分镜（需要 ### Shot N (0-3s) 格式）")
    title = str(parsed.get("title") or "")
    merged = merge_from_parsed(slug, n, parsed, title=title, existing=existing)
    impact = script_impact(
        existing,
        merged,
        old_meta=(existing or {}).get("meta") if existing else {},
        new_meta=parsed.get("meta") or {},
    )
    return {"slug": slug, "episode": n, "impact": impact, "count": merged.get("count") or 0}


def save_script(slug: str, episode: int, content: str, *, title: str | None = None) -> dict[str, Any]:
    slug = parse_slug(slug)
    n = parse_episode(episode)
    text = str(content or "")
    if not text.strip():
        raise DramaBadRequest("剧本不能为空")
    from tools.drama_produce import extract_single_episode_markdown
    from tools.drama_video import parse_episode_markdown, sync_shots_doc

    # Guard: never let a multi-episode dump inflate one shots.json.
    text = extract_single_episode_markdown(text, n)

    project = load_project(slug)
    existing = load_doc(slug, n)
    _take_snapshot(slug, n, existing, tag="script")
    parsed = parse_episode_markdown(text)
    if not parsed.get("shots"):
        raise DramaBadRequest("剧本里没有分镜（需要 ### Shot N (0-3s) 格式）")
    ep_title = str(title or parsed.get("title") or "").strip()
    if not ep_title or ep_title in ("标题", f"EP{n:02d}", f"EP{n:02d} 标题"):
        series = project.get("series") if isinstance(project.get("series"), dict) else {}
        multi = bool(series.get("count_explicit") and int(series.get("episode_count") or 1) > 1)
        ep_title = str(project.get("title") or "").strip() or (f"第{n}集" if multi else "正片")
    ep_rel = _rel(slug, "episodes", f"ep{n:02d}.md")
    _write_text(ep_rel, text.rstrip() + "\n")

    episodes = [e for e in (project.get("episodes") or []) if int(e.get("n") or 0) != n]
    meta = parsed.get("meta") or {}
    seconds = 60
    raw_sec = str(meta.get("时长") or "")
    digits = "".join(ch for ch in raw_sec if ch.isdigit() or ch == ".")
    if digits:
        try:
            seconds = max(1, int(round(float(digits))))
        except ValueError:
            seconds = 60
    old_ep = next((e for e in (project.get("episodes") or []) if int(e.get("n") or 0) == n), {})
    if old_ep.get("seconds") and not digits:
        seconds = int(old_ep.get("seconds") or 60)
    series = project.get("series") if isinstance(project.get("series"), dict) else {}
    if series.get("seconds_per_episode") and not digits:
        try:
            seconds = int(series.get("seconds_per_episode"))
        except (TypeError, ValueError):
            pass
    episodes.append({"n": n, "title": ep_title, "seconds": seconds, "path": ep_rel})
    episodes.sort(key=lambda e: int(e.get("n") or 0))
    project["episodes"] = episodes
    save_project(slug, project)

    merged = sync_shots_doc(slug, n, text, title=ep_title)
    # Prefer summed shot timeline as the global episode length.
    from tools.drama_shots import episode_total_seconds
    from tools.drama_video import patch_episode_meta_duration

    total = episode_total_seconds(merged)
    if total > 0:
        seconds = int(round(total))
        for ep in project.get("episodes") or []:
            if int(ep.get("n") or 0) == n:
                ep["seconds"] = seconds
                break
        save_project(slug, project)
        synced_md = patch_episode_meta_duration(text, total)
        if synced_md != text:
            _write_text(ep_rel, synced_md.rstrip() + "\n")
            text = synced_md
    # 界面手动改剧本 = 更新 step1 真相源的唯一合法写入口
    try:
        from tools.drama_shots import json_rel as _shots_json_rel
        from tools.drama_step_contract import publish_script_step

        publish_script_step(
            slug,
            n,
            script_rel=ep_rel,
            shots_rel=_shots_json_rel(slug, n),
            doc=merged,
            from_ui=True,
        )
    except Exception as exc:
        raise DramaBadRequest(f"写入 step1_script 失败：{exc}") from exc
    impact = script_impact(
        existing,
        merged,
        old_meta=(existing or {}).get("meta") if existing else {},
        new_meta=(merged.get("meta") or parsed.get("meta") or {}),
    )
    payload = get_episode(slug, n)
    payload["impact"] = impact
    try:
        from tools.drama_script_blueprint import materialize_script_assets

        payload["blueprint"] = materialize_script_assets(slug, n, parsed)
    except Exception:
        payload["blueprint"] = {"error": "materialize_failed"}
    return payload


def generate_episode_script(
    slug: str,
    episode: int,
    premise: str,
    *,
    target_seconds: int | None = None,
    episode_count: int | None = None,
) -> dict[str, Any]:
    """一句话 → 完整剧本 + 分镜表，然后落盘为分集剧本。

    用 script 节点模型生成 Markdown，再复用 save_script 同步 shots.json。
    Hard constraints: single episode only, target duration from user/series plan.
    """
    import re

    slug = parse_slug(slug)
    n = parse_episode(episode)
    text = str(premise or "").strip()
    if not text:
        raise DramaBadRequest("请先给一句故事梗概")
    project = load_project(slug)

    from tools.drama_produce import (
        apply_target_duration_meta,
        extract_single_episode_markdown,
        parse_series_spec,
        shot_range_for_seconds,
    )
    from tools.drama_script import draft_text_sync, scrub_script_markdown
    from tools.drama_video import parse_episode_markdown

    series = project.get("series") if isinstance(project.get("series"), dict) else {}
    spec = parse_series_spec(
        text,
        episode_count=episode_count
        if episode_count is not None
        else series.get("episode_count"),
        seconds=target_seconds
        if target_seconds is not None
        else series.get("seconds_per_episode"),
    )
    ep_total = int(spec["episode_count"])
    ep_sec = int(spec["seconds_per_episode"])
    shot_lo, shot_hi = shot_range_for_seconds(ep_sec)
    multi = bool(spec.get("count_explicit") and ep_total > 1)

    series_rule = (
        f"这是第 {n} 集（共 {ep_total} 集）；"
        if multi
        else f"这是一支约 {ep_sec} 秒的单集短片；不要写「第几集/共几集/EP02」；"
    )
    user_series = (
        f"请只编写第 {n} 集（共 {ep_total} 集），目标时长 {ep_sec} 秒。"
        "若梗概提到多集，其它集剧情只能作为本集悬念 foreshadow，禁止直接写成多集剧本。"
        if multi
        else f"请编写单集剧本，目标时长 {ep_sec} 秒。不要规划或输出其它集。"
    )

    # File format still uses EP{n:02d} header for the workbench path; keep it internal.
    title_line = f"# EP{n:02d} 标题" if multi else "# 标题"

    from tools.drama_script_blueprint import (
        build_episode_script_system,
        build_episode_user_prompt,
        ensure_bible_and_outline,
        load_bible_outline,
        materialize_script_assets,
    )

    ensure_bible_and_outline(
        slug,
        text,
        title=str(project.get("title") or ""),
        series=spec,
    )
    bible, outline = load_bible_outline(slug)

    system = build_episode_script_system(
        title_line=title_line,
        ep_sec=ep_sec,
        shot_lo=shot_lo,
        shot_hi=shot_hi,
        series_rule=series_rule,
    )
    user_prompt = build_episode_user_prompt(
        text,
        user_series=user_series,
        bible=bible,
        outline=outline,
    )

    draft = draft_text_sync(slug, user_prompt, system=system)
    if not str(draft or "").strip():
        raise DramaBadRequest("剧本生成失败（模型无返回），请重试")

    cleaned = apply_target_duration_meta(
        extract_single_episode_markdown(scrub_script_markdown(str(draft).strip()), n),
        ep_sec,
    )

    parsed = parse_episode_markdown(cleaned)
    shot_n = len(parsed.get("shots") or [])
    ep_headers = re.findall(r"^#\s*EP\s*\d+", cleaned, flags=re.M)
    if shot_n > shot_hi + 3 or len(ep_headers) > 1:
        draft2 = draft_text_sync(
            slug,
            user_prompt
            + f"\n上次稿不合格（镜头数={shot_n}）。请重写：仅 EP{n:02d}，"
            f"{shot_lo}-{shot_hi} 镜，总时长 {ep_sec}s；"
            "必须保留角色设定/场景设定/道具设定/配乐与分镜结构化字段；"
            "场景设定须可生成无人物主底板，道具设定须可画设定图；"
            "分镜地点/道具与设定块逐字同名。",
            system=system,
        )
        if str(draft2 or "").strip():
            cleaned = apply_target_duration_meta(
                extract_single_episode_markdown(scrub_script_markdown(str(draft2).strip()), n),
                ep_sec,
            )

    # Persist series plan so workbench can show EP2/EP3 even before they are opened.
    project = load_project(slug)
    project["series"] = {
        "episode_count": ep_total,
        "seconds_per_episode": ep_sec,
        "shot_min": shot_lo,
        "shot_max": shot_hi,
        "count_explicit": bool(spec.get("count_explicit")),
        "seconds_explicit": bool(spec.get("seconds_explicit")),
        "source": spec.get("source") or "premise",
    }
    if text and not str(project.get("logline") or "").strip():
        project["logline"] = text
    save_project(slug, project)

    payload = save_script(slug, n, cleaned)
    try:
        assets = materialize_script_assets(slug, n, parse_episode_markdown(cleaned))
        payload["blueprint"] = assets
    except Exception:
        # Script is already saved; asset upsert is best-effort enrichment.
        payload["blueprint"] = {"error": "materialize_failed"}
    return payload


def generate_scripts_from_premise(
    slug: str,
    premise: str,
    *,
    episode: int = 1,
) -> dict[str, Any]:
    """Studio chat entry: one premise → planned episode script(s).

    If the premise clearly asks for N>1 episodes (or the project series plan does and
    some episodes are still missing), write those scripts. Returns the focus episode
    payload plus series metadata.
    """
    slug = parse_slug(slug)
    focus = parse_episode(episode)
    text = str(premise or "").strip()
    if not text:
        raise DramaBadRequest("请先给一句故事梗概")
    project = load_project(slug)

    from tools.drama_produce import _parse_episode_count_from_text, parse_series_spec

    series = project.get("series") if isinstance(project.get("series"), dict) else {}
    from_text = _parse_episode_count_from_text(text)
    if from_text and from_text > 1:
        spec = parse_series_spec(text)
    else:
        spec = parse_series_spec(
            text,
            episode_count=series.get("episode_count"),
            seconds=series.get("seconds_per_episode"),
        )

    ep_total = int(spec["episode_count"])
    ep_sec = int(spec["seconds_per_episode"])
    multi = bool(spec.get("count_explicit") and ep_total > 1)

    existing = {
        int(e.get("n") or 0)
        for e in (project.get("episodes") or [])
        if int(e.get("n") or 0) >= 1
    }

    if multi:
        if from_text and from_text > 1:
            targets = list(range(1, ep_total + 1))
        else:
            missing = [n for n in range(1, ep_total + 1) if n not in existing]
            targets = sorted(set(missing + [focus]))
    else:
        targets = [focus]

    generated: list[dict[str, Any]] = []
    focus_payload: dict[str, Any] | None = None
    for n in targets:
        info = generate_episode_script(
            slug,
            n,
            text,
            target_seconds=ep_sec,
            episode_count=ep_total,
        )
        generated.append(
            {
                "episode": n,
                "title": info.get("title"),
                "count": info.get("count"),
                "seconds": info.get("seconds"),
            }
        )
        if n == focus:
            focus_payload = info

    if focus_payload is None:
        focus_payload = next(
            (
                generate_episode_script(
                    slug,
                    n,
                    text,
                    target_seconds=ep_sec,
                    episode_count=ep_total,
                )
                for n in targets
            ),
            None,
        )
        if focus_payload is None:
            focus_payload = generate_episode_script(
                slug,
                focus,
                text,
                target_seconds=ep_sec,
                episode_count=ep_total,
            )

    focus_payload["series"] = {
        "episode_count": ep_total,
        "seconds_per_episode": ep_sec,
        "count_explicit": bool(spec.get("count_explicit")),
        "shot_min": spec.get("shot_min"),
        "shot_max": spec.get("shot_max"),
    }
    focus_payload["generated_episodes"] = [g["episode"] for g in generated]
    focus_payload["scripts"] = generated
    return focus_payload


def rerender_dirty_shots(slug: str, episode: int) -> dict[str, Any]:
    """Enqueue background rerender of dirty shots (D7)."""
    slug = parse_slug(slug)
    n = parse_episode(episode)
    _assert_budget(slug, n)
    _ensure_shots_doc(slug, n)
    from tools.drama_queue import drama_jobs

    try:
        return drama_jobs.submit("rerender_dirty", slug, n)
    except RuntimeError as e:
        raise DramaBadRequest(str(e)) from e


def enqueue_job(
    slug: str,
    episode: int,
    kind: str,
    *,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    slug = parse_slug(slug)
    n = parse_episode(episode)
    _ensure_shots_doc(slug, n)
    if str(kind or "").strip() in ("render_episode", "rerender_dirty", "produce_episode"):
        _assert_budget(slug, n)
    from tools.drama_queue import drama_jobs

    try:
        return drama_jobs.submit(kind, slug, n, params=params)
    except RuntimeError as e:
        raise DramaBadRequest(str(e)) from e
    except ValueError as e:
        raise DramaBadRequest(str(e)) from e


def get_render_job(job_id: str) -> dict[str, Any]:
    from tools.drama_queue import drama_jobs

    job = drama_jobs.get(job_id)
    if job is None:
        raise DramaNotFound(f"任务不存在：{job_id}")
    from tools.drama_queue import public_job

    return public_job(job)


def list_render_jobs(
    *,
    slug: str | None = None,
    active_only: bool = False,
    limit: int = 20,
) -> dict[str, Any]:
    from tools.drama_queue import drama_jobs

    if slug:
        slug = parse_slug(slug)
    return {
        "count": len(drama_jobs.list_jobs(slug=slug, active_only=active_only, limit=limit)),
        "jobs": drama_jobs.list_jobs(slug=slug, active_only=active_only, limit=limit),
    }


def cancel_render_job(job_id: str) -> dict[str, Any]:
    from tools.drama_queue import drama_jobs

    try:
        return drama_jobs.cancel(job_id)
    except KeyError as e:
        raise DramaNotFound(f"任务不存在：{job_id}") from e


def retry_render_job(job_id: str) -> dict[str, Any]:
    from tools.drama_queue import drama_jobs

    try:
        return drama_jobs.retry(job_id)
    except KeyError as e:
        raise DramaNotFound(f"任务不存在：{job_id}") from e
    except ValueError as e:
        raise DramaBadRequest(str(e)) from e
    except RuntimeError as e:
        raise DramaBadRequest(str(e)) from e


def resume_interrupted_jobs(*, slug: str = "", limit: int = 20) -> dict[str, Any]:
    """Batch re-queue jobs interrupted by process restart."""
    from tools.drama_queue import drama_jobs

    if slug:
        slug = parse_slug(slug)
    jobs = drama_jobs.resume_interrupted(slug=slug, limit=limit)
    return {"ok": True, "count": len(jobs), "jobs": jobs}


def resume_render_job(
    *,
    job_id: str = "",
    kind: str = "",
    slug: str = "",
    episode: int = 0,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """失败/中断后的续跑入口（历史会话「继续渲染」）。"""
    from tools.drama_queue import drama_jobs

    try:
        if slug:
            slug = parse_slug(slug)
        if episode:
            episode = parse_episode(episode)
        return drama_jobs.resume_or_retry(
            job_id,
            kind=kind,
            slug=slug,
            episode=int(episode or 0),
            params=params,
        )
    except KeyError as e:
        raise DramaNotFound(f"任务不存在：{job_id or slug}") from e
    except ValueError as e:
        raise DramaBadRequest(str(e)) from e
    except RuntimeError as e:
        raise DramaBadRequest(str(e)) from e


def _assert_budget(slug: str, episode: int) -> None:
    """预算闸已移除：不再因超支拦截任何生成动作。

    保留空实现以维持调用点不变；预算功能整体下线，默认永远放行，
    力求极致成片效果、不考虑成本约束。
    """
    return None


def generate_i2v_shot(slug: str, episode: int, shot_n: int) -> dict[str, Any]:
    slug = parse_slug(slug)
    n = parse_episode(episode)
    shot_n = parse_shot_n(shot_n)
    _assert_budget(slug, n)
    doc = _ensure_shots_doc(slug, n)
    shot = find_shot(doc, shot_n)
    if shot is None:
        raise DramaNotFound(f"找不到 Shot {shot_n}")

    from tools.drama_i2v import should_try_i2v
    from tools.drama_shots import normalize_i2v_mode

    assets = shot.get("assets") if isinstance(shot.get("assets"), dict) else {}
    scene_rel = str(assets.get("scene") or "").strip()
    try:
        scene_ok = bool(scene_rel) and resolve_safe(scene_rel).is_file()
    except ValueError:
        scene_ok = False
    if not scene_ok:
        raise DramaBadRequest("请先在「画面」步骤生成关键帧")

    mode = normalize_i2v_mode(shot.get("i2v"))
    if mode == "off":
        raise DramaBadRequest("本镜 I2V 为 off，请在视频页改为 auto 或 on 后再生成")

    # 工作台点「生成视频」= 明确意图：auto 下自动锁 scene，避免再卡「请先锁定」
    if not should_try_i2v(shot, slug=slug):
        est = estimate_i2v(slug, shot)
        if est.get("ladder") == "L0":
            shot["i2v_source"] = "fallback"
            save_doc(doc)
            job = enqueue_job(slug, n, "rerender_shot", params={"shot": shot_n, "layers": ["clip"]})
            job["estimate"] = est
            job["i2v_source"] = "fallback"
            return job
        locked = list(shot.get("locked") or [])
        if "scene" not in locked and "shot" not in locked:
            locked.append("scene")
            shot["locked"] = locked
            save_doc(doc)
        if not should_try_i2v(shot, slug=slug):
            raise DramaBadRequest("当前镜头无法生成视频（可能为 L0 静图运镜档或配置异常）")

    job = enqueue_job(slug, n, "i2v_shot", params={"shot": shot_n})
    job["estimate"] = estimate_i2v(slug, shot)
    return job


def qc_shot(slug: str, episode: int, shot_n: int) -> dict[str, Any]:
    slug = parse_slug(slug)
    n = parse_episode(episode)
    shot_n = parse_shot_n(shot_n)
    doc = _ensure_shots_doc(slug, n)
    shot = find_shot(doc, shot_n)
    if shot is None:
        raise DramaNotFound(f"找不到 Shot {shot_n}")
    from tools.drama_qc import qc_shot_bundle, shot_can_pass

    bundle = qc_shot_bundle(slug, n, shot, apply=True)
    save_doc(doc)
    return {
        "slug": slug,
        "episode": n,
        "n": shot_n,
        "passed": shot_can_pass(bundle),
        "shot": enrich_shot(shot, slug=slug),
    }


def qc_episode(slug: str, episode: int) -> dict[str, Any]:
    slug = parse_slug(slug)
    n = parse_episode(episode)
    doc = _ensure_shots_doc(slug, n)
    from tools.drama_qc import run_episode_qc

    run_episode_qc(slug, n, doc, apply=True)
    save_doc(doc)
    ep = get_episode(slug, n)
    return {"slug": slug, "episode": n, "qc": ep.get("qc"), "hint": (ep.get("qc") or {}).get("block_reason") or "验收已跑，通过必须以脚本为准"}


def qc_checklist(slug: str, episode: int) -> dict[str, Any]:
    """R8: one-screen checklist of what blocks this episode from passing."""
    slug = parse_slug(slug)
    n = parse_episode(episode)
    doc = _ensure_shots_doc(slug, n)
    from tools.drama_qc import qc_episode_checklist

    return qc_episode_checklist(slug, n, doc)


def reject_all_qc(slug: str, episode: int) -> dict[str, Any]:
    """R8: reject every problem shot at once (mark 待修 + dirty)."""
    slug = parse_slug(slug)
    n = parse_episode(episode)
    doc = _ensure_shots_doc(slug, n)
    from tools.drama_qc import mark_shot_verdict

    rejected: list[int] = []
    for shot in doc.get("shots") or []:
        sn = int(shot.get("n") or 0)
        if sn < 1 or "shot" in (shot.get("locked") or []):
            continue
        try:
            mark_shot_verdict(shot, "待修")
        except ValueError:
            continue
        dirty = [str(x) for x in (shot.get("dirty") or [])]
        for layer in ("scene", "motion", "lip", "clip"):
            if layer not in dirty and layer not in (shot.get("locked") or []):
                dirty.append(layer)
        shot["dirty"] = dirty
        if dirty:
            shot["status"] = "dirty"
        rejected.append(sn)
    save_doc(doc)
    return qc_checklist(slug, n)


def pass_episode_qc(slug: str, episode: int) -> dict[str, Any]:
    slug = parse_slug(slug)
    n = parse_episode(episode)
    doc = _ensure_shots_doc(slug, n)
    from tools.drama_qc import mark_episode_passed

    try:
        mark_episode_passed(doc, passed=True)
    except ValueError as e:
        raise DramaBadRequest(str(e)) from e
    save_doc(doc)
    return get_episode(slug, n)


def reject_shot_qc(slug: str, episode: int, shot_n: int) -> dict[str, Any]:
    slug = parse_slug(slug)
    n = parse_episode(episode)
    shot_n = parse_shot_n(shot_n)
    doc = _ensure_shots_doc(slug, n)
    shot = find_shot(doc, shot_n)
    if shot is None:
        raise DramaNotFound(f"找不到 Shot {shot_n}")
    from tools.drama_qc import mark_episode_passed, mark_shot_verdict

    try:
        mark_shot_verdict(shot, "待修")
        mark_episode_passed(doc, passed=False)
    except ValueError as e:
        raise DramaBadRequest(str(e)) from e
    save_doc(doc)
    return get_episode(slug, n)


def pass_shot_qc(slug: str, episode: int, shot_n: int) -> dict[str, Any]:
    slug = parse_slug(slug)
    n = parse_episode(episode)
    shot_n = parse_shot_n(shot_n)
    doc = _ensure_shots_doc(slug, n)
    shot = find_shot(doc, shot_n)
    if shot is None:
        raise DramaNotFound(f"找不到 Shot {shot_n}")
    from tools.drama_qc import mark_shot_verdict

    try:
        mark_shot_verdict(shot, "通过")
    except ValueError as e:
        raise DramaBadRequest(str(e)) from e
    save_doc(doc)
    return get_episode(slug, n)


def remix_loudness(slug: str, episode: int) -> dict[str, Any]:
    """Loudness fail path: remix mix only, never rebuild per-shot clips."""
    slug = parse_slug(slug)
    n = parse_episode(episode)
    mix_episode(slug, n, background=False)
    doc = load_doc(slug, n)
    if doc is None:
        raise DramaNotFound("没有 shots.json")
    from tools.drama_qc import check_allows_pass, qc_episode_loudness, normalize_episode_qc

    loudness = qc_episode_loudness(slug, n, apply=True)
    qc = normalize_episode_qc(doc.get("qc"))
    qc["loudness"] = loudness
    if qc.get("verdict") == "通过" and not check_allows_pass(loudness):
        qc["verdict"] = "待修"
        qc["status"] = "review"
        qc["passed_at"] = ""
        qc["block_reason"] = str(loudness.get("hint") or "响度不达标，只重 mix")
    doc["qc"] = qc
    save_doc(doc)
    ep = get_episode(slug, n)
    ep["hint"] = "已只重 mix，各镜 clip 未改"
    return ep


def suggest_coverage(slug: str, episode: int) -> dict[str, Any]:
    slug = parse_slug(slug)
    n = parse_episode(episode)
    load_project(slug)
    doc = _ensure_shots_doc(slug, n)
    from tools.drama_director import refresh_coverage

    coverage = refresh_coverage(doc)
    save_doc(doc)
    return {
        "slug": slug,
        "episode": n,
        "coverage": coverage,
        "hint": "只建议，未改镜头、未加锁",
    }


def apply_coverage(slug: str, episode: int, sid: str) -> dict[str, Any]:
    slug = parse_slug(slug)
    n = parse_episode(episode)
    sid = str(sid or "").strip()
    if not sid:
        raise DramaBadRequest("需要建议 id")
    doc = _ensure_shots_doc(slug, n)
    from tools.drama_director import apply_suggestion

    try:
        info = apply_suggestion(doc, sid)
    except ValueError as e:
        raise DramaBadRequest(str(e)) from e
    save_doc(doc)
    ep = get_episode(slug, n)
    ep["applied"] = info
    return ep


def dismiss_coverage(slug: str, episode: int, sid: str) -> dict[str, Any]:
    slug = parse_slug(slug)
    n = parse_episode(episode)
    sid = str(sid or "").strip()
    if not sid:
        raise DramaBadRequest("需要建议 id")
    doc = _ensure_shots_doc(slug, n)
    from tools.drama_director import dismiss_suggestion

    try:
        dismiss_suggestion(doc, sid)
    except ValueError as e:
        raise DramaBadRequest(str(e)) from e
    save_doc(doc)
    return get_episode(slug, n)


def lock_coverage(slug: str, episode: int, sid: str) -> dict[str, Any]:
    slug = parse_slug(slug)
    n = parse_episode(episode)
    sid = str(sid or "").strip()
    if not sid:
        raise DramaBadRequest("需要建议 id")
    doc = _ensure_shots_doc(slug, n)
    from tools.drama_director import lock_suggestion

    try:
        lock_suggestion(doc, sid)
    except ValueError as e:
        raise DramaBadRequest(str(e)) from e
    save_doc(doc)
    return get_episode(slug, n)


def generate_lip_shot(slug: str, episode: int, shot_n: int) -> dict[str, Any]:
    slug = parse_slug(slug)
    n = parse_episode(episode)
    shot_n = parse_shot_n(shot_n)
    _assert_budget(slug, n)
    doc = _ensure_shots_doc(slug, n)
    shot = find_shot(doc, shot_n)
    if shot is None:
        raise DramaNotFound(f"找不到 Shot {shot_n}")
    from tools.drama_lip import estimate_lip, lip_eligible

    gate = lip_eligible(shot)
    if not gate["ok"]:
        raise DramaBadRequest(gate["reason"])
    scene = (shot.get("assets") or {}).get("scene") or ""
    voice = (shot.get("assets") or {}).get("voice") or ""
    try:
        scene_ok = bool(scene) and resolve_safe(scene).is_file()
        voice_ok = bool(voice) and resolve_safe(voice).is_file()
    except ValueError:
        scene_ok = False
        voice_ok = False
    if not scene_ok:
        raise DramaBadRequest("请先锁定/生成画面再开口型")
    if not voice_ok:
        raise DramaBadRequest("请先生成配音再开口型")
    job = enqueue_job(slug, n, "lip_shot", params={"shot": shot_n})
    job["estimate"] = estimate_lip(slug, shot)
    return job


def generate_keys_shot(slug: str, episode: int, shot_n: int, count: int | None = None) -> dict[str, Any]:
    slug = parse_slug(slug)
    n = parse_episode(episode)
    shot_n = parse_shot_n(shot_n)
    _assert_budget(slug, n)
    doc = _ensure_shots_doc(slug, n)
    shot = find_shot(doc, shot_n)
    if shot is None:
        raise DramaNotFound(f"找不到 Shot {shot_n}")
    from tools.drama_keys import estimate_keys, keys_count, keys_eligible

    gate = keys_eligible(shot, slug=slug)
    if not gate["ok"]:
        raise DramaBadRequest(gate["reason"])
    scene = (shot.get("assets") or {}).get("scene") or ""
    try:
        scene_ok = bool(scene) and resolve_safe(scene).is_file()
    except ValueError:
        scene_ok = False
    if not scene_ok:
        raise DramaBadRequest("请先锁定/生成画面再钉关键帧")
    job = enqueue_job(slug, n, "keys_shot", params={"shot": shot_n, "count": keys_count(count)})
    job["estimate"] = estimate_keys(slug, shot)
    return job


def choose_key(slug: str, episode: int, shot_n: int, kid: str, cid: str) -> dict[str, Any]:
    slug = parse_slug(slug)
    n = parse_episode(episode)
    shot_n = parse_shot_n(shot_n)
    doc = _ensure_shots_doc(slug, n)
    shot = find_shot(doc, shot_n)
    if shot is None:
        raise DramaNotFound(f"找不到 Shot {shot_n}")
    from tools.drama_keys import choose_key_pose

    try:
        choose_key_pose(shot, kid, cid)
    except (ValueError, FileNotFoundError) as e:
        raise DramaBadRequest(str(e)) from e
    save_doc(doc)
    return {"slug": slug, "episode": n, "shot": enrich_shot(shot, slug=slug), "voice_rebuilt": False}


def upload_key(slug: str, episode: int, shot_n: int, kid: str, data: bytes) -> dict[str, Any]:
    slug = parse_slug(slug)
    n = parse_episode(episode)
    shot_n = parse_shot_n(shot_n)
    doc = _ensure_shots_doc(slug, n)
    shot = find_shot(doc, shot_n)
    if shot is None:
        raise DramaNotFound(f"找不到 Shot {shot_n}")
    from tools.drama_keys import upload_key_pose

    try:
        upload_key_pose(slug, n, shot, kid, data)
    except (ValueError, FileNotFoundError) as e:
        raise DramaBadRequest(str(e)) from e
    save_doc(doc)
    return {"slug": slug, "episode": n, "shot": enrich_shot(shot, slug=slug), "voice_rebuilt": False}


def lock_key(slug: str, episode: int, shot_n: int, kid: str, locked: bool = True) -> dict[str, Any]:
    slug = parse_slug(slug)
    n = parse_episode(episode)
    shot_n = parse_shot_n(shot_n)
    doc = _ensure_shots_doc(slug, n)
    shot = find_shot(doc, shot_n)
    if shot is None:
        raise DramaNotFound(f"找不到 Shot {shot_n}")
    from tools.drama_keys import lock_key_pose

    try:
        lock_key_pose(shot, kid, locked)
    except ValueError as e:
        raise DramaBadRequest(str(e)) from e
    save_doc(doc)
    return {"slug": slug, "episode": n, "shot": enrich_shot(shot, slug=slug)}


def get_models(slug: str) -> dict[str, Any]:
    slug = parse_slug(slug)
    load_project(slug)
    doc = load_models(slug)
    return {"slug": slug, "path": f"dramas/{slug}/models.json", "models": public_models(doc)}


def patch_models(slug: str, patch: dict[str, Any]) -> dict[str, Any]:
    slug = parse_slug(slug)
    load_project(slug)
    if "provider" in patch and "available" in patch:
        try:
            doc = set_provider_available(slug, str(patch.get("provider") or ""), bool(patch.get("available")))
        except ValueError as e:
            raise DramaBadRequest(str(e)) from e
        return {"slug": slug, "models": public_models(doc)}
    current = load_models(slug)
    if "currency" in patch and patch["currency"]:
        current["currency"] = str(patch["currency"]).strip().upper()
    if "budget" in patch and isinstance(patch["budget"], dict):
        budget = current.setdefault("budget", {})
        for key, value in patch["budget"].items():
            if key in ("enabled", "per_episode", "warn_at", "note") and value is not None:
                budget[key] = value
    doc = save_models(slug, current)
    return {"slug": slug, "models": public_models(doc)}


def apply_style(slug: str, episode: int, style_id: str) -> dict[str, Any]:
    """Switch this episode's style pack. Does not rebuild existing clips."""
    slug = parse_slug(slug)
    n = parse_episode(episode)
    doc = _ensure_shots_doc(slug, n)
    from tools.drama_styles import load_style, parse_style_id

    try:
        sid = parse_style_id(style_id)
    except ValueError as e:
        raise DramaBadRequest(str(e)) from e
    if sid:
        pack = load_style(slug, sid)
        if pack is None:
            raise DramaBadRequest(f"没有风格包：{sid}")
        doc["style_id"] = sid
        title = pack.get("title") or sid
    else:
        doc["style_id"] = ""
        title = "默认路由"
    save_doc(doc)
    ep = get_episode(slug, n)
    ep["hint"] = f"已切换为{title}，未重渲已有 clip；新镜按新路由出图"
    return ep


def list_snapshots(slug: str, episode: int) -> dict[str, Any]:
    slug = parse_slug(slug)
    n = parse_episode(episode)
    _ensure_shots_doc(slug, n)
    return {"slug": slug, "episode": n, "snapshots": _list_snapshots(slug, n)}


def restore_snapshot(slug: str, episode: int, sid: str) -> dict[str, Any]:
    slug = parse_slug(slug)
    n = parse_episode(episode)
    try:
        result = _restore_snapshot(slug, n, str(sid or ""))
    except LookupError as e:
        raise DramaNotFound(str(e)) from e
    ep = get_episode(slug, n)
    ep["restored"] = result
    return ep


def drop_snapshot(slug: str, episode: int, sid: str) -> dict[str, Any]:
    slug = parse_slug(slug)
    n = parse_episode(episode)
    try:
        return _drop_snapshot(slug, n, str(sid or ""))
    except LookupError as e:
        raise DramaNotFound(str(e)) from e


def classify_shots(slug: str, episode: int, *, force: bool = False) -> dict[str, Any]:
    slug = parse_slug(slug)
    n = parse_episode(episode)
    load_models(slug)
    doc = _ensure_shots_doc(slug, n)
    _take_snapshot(slug, n, doc, tag="classify")
    changed: list[int] = []
    for shot in doc.get("shots") or []:
        before = (shot.get("kind"), shot.get("size"), shot.get("speaker"))
        apply_shot_class(shot, force=force)
        after = (shot.get("kind"), shot.get("size"), shot.get("speaker"))
        if before != after:
            changed.append(int(shot.get("n") or 0))
            if before[0] != after[0] or before[1] != after[1]:
                dirty = list(shot.get("dirty") or [])
                locked = set(shot.get("locked") or [])
                for layer in ("clip", "motion", "lip"):
                    if layer not in locked and layer not in dirty:
                        dirty.append(layer)
                shot["dirty"] = dirty
                if dirty:
                    shot["status"] = "dirty"
    save_doc(doc)
    return {
        "slug": slug,
        "episode": n,
        "classified": len(doc.get("shots") or []),
        "changed": [n for n in changed if n],
        "shots": [enrich_shot(s, slug=slug, episode=n) for s in (doc.get("shots") or [])],
        "cost": estimate_episode_i2v(slug, doc.get("shots") or [], episode=n, doc=doc),
    }


def rerender_dirty_shots_sync(slug: str, episode: int) -> dict[str, Any]:
    """Synchronous rerender — used by tests and legacy callers."""
    slug = parse_slug(slug)
    n = parse_episode(episode)
    doc = _ensure_shots_doc(slug, n)
    ep = get_episode(slug, n)
    markdown = ep.get("script") or ""
    from tools.drama_video import render_episode_video

    result = render_episode_video(
        slug,
        n,
        str(markdown),
        title=str(ep.get("title") or doc.get("title") or ""),
    )
    result["impact"] = {
        "rebuilt_shots": result.get("rebuilt_shots") or [],
        "skipped_shots": result.get("skipped_shots") or [],
        "summary": (
            "重渲 Shot "
            + "/".join(str(x) for x in (result.get("rebuilt_shots") or []))
            if result.get("rebuilt_shots")
            else "没有脏镜头需要重渲"
        ),
    }
    return result


def enrich_character(slug: str, char: dict[str, Any]) -> dict[str, Any]:
    from tools.drama_characters import normalize_category, ref_canvas_size

    pub = dict(char)
    meta = _asset_meta(str(char.get("ref") or ""))
    face_meta = _asset_meta(str(char.get("ref_face") or ""))
    plate_meta = _asset_meta(str(char.get("ref_plate") or ""))
    # Scene visual authority = master plate only (no separate 设定图)
    if normalize_category(char.get("category")) == "scene":
        pub["ref_exists"] = bool(plate_meta["exists"])
        pub["ref_url"] = plate_meta.get("url") or meta.get("url")
        pub["ref_bytes"] = int(plate_meta.get("bytes") or meta.get("bytes") or 0)
        pub["ref_width"] = int(plate_meta.get("width") or meta.get("width") or 0)
        pub["ref_height"] = int(plate_meta.get("height") or meta.get("height") or 0)
    else:
        pub["ref_exists"] = bool(meta["exists"])
        pub["ref_url"] = meta.get("url")
        pub["ref_bytes"] = int(meta.get("bytes") or 0)
        pub["ref_width"] = int(meta.get("width") or 0)
        pub["ref_height"] = int(meta.get("height") or 0)
    cw, ch = ref_canvas_size(char)
    pub["ref_canvas_width"] = int(cw)
    pub["ref_canvas_height"] = int(ch)
    pub["ref_face_exists"] = bool(face_meta["exists"])
    pub["ref_face_url"] = face_meta.get("url")
    pub["ref_plate_exists"] = bool(plate_meta["exists"])
    pub["ref_plate_url"] = plate_meta.get("url")
    return pub


def list_characters(slug: str) -> list[dict[str, Any]]:
    slug = parse_slug(slug)
    return [enrich_character(slug, c) for c in load_characters(slug)]


def get_characters(slug: str) -> dict[str, Any]:
    project = load_project(slug)
    slug = str(project.get("slug") or slug)
    return {
        "slug": slug,
        "characters": list_characters(slug),
        "voices": public_voices(slug),
    }


def _dirty_shots_for_character(slug: str, cid: str, layers: list[str]) -> None:
    project = load_project(slug)
    for ep in project.get("episodes") or []:
        try:
            n = int(ep.get("n") or 0)
        except (TypeError, ValueError):
            continue
        if n < 1:
            continue
        doc = load_doc(slug, n)
        if doc is None:
            continue
        changed = False
        for shot in doc.get("shots") or []:
            roles = normalize_roles(shot.get("角色"))
            prop_ids = [
                str(x).strip()
                for x in (shot.get("prop_ids") or [])
                if str(x).strip()
            ] if isinstance(shot.get("prop_ids"), (list, tuple)) else normalize_roles(shot.get("prop_ids"))
            hit = (
                cid in roles
                or cid == str(shot.get("location_id") or "")
                or cid in prop_ids
            )
            if not hit:
                continue
            locked = set(shot.get("locked") or [])
            if "shot" in locked:
                continue
            dirty = list(shot.get("dirty") or [])
            for layer in layers:
                if layer not in locked and layer not in dirty:
                    dirty.append(layer)
                    changed = True
            shot["dirty"] = dirty
            if dirty:
                shot["status"] = "dirty"
        if changed:
            save_doc(doc)


def save_character(slug: str, patch: dict[str, Any]) -> dict[str, Any]:
    project = load_project(slug)
    slug = str(project.get("slug") or slug)
    cid = str(patch.get("id") or suggest_character_id(str(patch.get("name") or ""))).strip()
    before = next((c for c in load_characters(slug) if c.get("id") == cid), None)
    try:
        rec = upsert_character(slug, {**patch, "id": cid})
    except CharacterError as e:
        raise DramaBadRequest(str(e)) from e
    try:
        from tools.drama_series_pack_materialize import sync_asset_to_series_pack

        sync_asset_to_series_pack(slug, rec)
    except Exception:
        pass
    layers: list[str] = []
    if before:
        if str(before.get("look") or "") != str(rec.get("look") or "") or str(
            before.get("colors") or ""
        ) != str(rec.get("colors") or "") or any(
            str(before.get(k) or "") != str(rec.get(k) or "")
            for k in ("hair", "eyes", "outfit", "marks")
        ):
            layers.extend(["scene", "clip"])
        if str(before.get("voice") or "") != str(rec.get("voice") or ""):
            layers.extend(["voice", "clip"])
        if layers:
            _dirty_shots_for_character(slug, rec["id"], layers)
    return enrich_character(slug, rec)


def remove_character(slug: str, cid: str) -> dict[str, Any]:
    load_project(slug)
    slug = parse_slug(slug)
    try:
        delete_character(slug, cid)
    except CharacterError as e:
        raise DramaBadRequest(str(e)) from e
    return get_characters(slug)


def lock_character_ref(slug: str, cid: str, locked: bool) -> dict[str, Any]:
    load_project(slug)
    slug = parse_slug(slug)
    try:
        rec = set_ref_locked(slug, cid, locked)
    except CharacterError as e:
        raise DramaBadRequest(str(e)) from e
    return enrich_character(slug, rec)


def upload_character_ref(slug: str, cid: str, data: bytes) -> dict[str, Any]:
    load_project(slug)
    slug = parse_slug(slug)
    from tools.drama_characters import CharacterError, find_character, load_characters, save_character_ref

    rec = find_character(load_characters(slug), cid)
    if rec is None:
        raise DramaNotFound(f"找不到资产：{cid}，请先保存")
    try:
        rec = save_character_ref(slug, cid, data)
    except CharacterError as e:
        raise DramaBadRequest(str(e)) from e
    # Ref/plate/visual asset change → dirty bound scenes (location_id / prop_ids / 角色).
    _dirty_shots_for_character(slug, cid, ["scene", "clip"])
    return enrich_character(slug, rec)


def generate_character_ref(slug: str, cid: str, *, lock: bool = False, seed: int | None = None) -> dict[str, Any]:
    """文生图生成定妆参考图，直接写入 ref（单张，无候选墙）。

    Autopilot passes lock=True so the plate is frozen for identity consistency.
    Workbench fine-tune keeps lock=False until the user clicks 锁定.
    ``seed`` 用于锁定前校验失败后「换一张脸」重生成（None 时走默认确定性种子）。
    全身定妆成功后会再生成正脸特写锚（``ref_face``），供出图图1与 ArcFace。
    """
    load_project(slug)
    slug = parse_slug(slug)
    from tools.drama_characters import (
        find_character,
        load_characters,
        normalize_category,
        ref_exists,
        ref_face_exists,
        ref_plate_exists,
        set_ref_locked,
        upsert_character,
    )

    rec = find_character(load_characters(slug), cid)
    if rec is None:
        raise DramaNotFound(f"找不到资产：{cid}，请先保存")
    cat = normalize_category(rec.get("category"))
    # 工作台「重新生成」直接覆盖已有图；流水线仍靠生成后自动锁定
    was_locked = bool(rec.get("ref_locked"))
    if was_locked:
        try:
            rec = set_ref_locked(slug, cid, False)
        except Exception:
            rec = {**rec, "ref_locked": False}
    if not str(rec.get("look") or "").strip():
        raise DramaBadRequest(
            "请先填写空间描述再生成" if cat == "scene" else "请先填写全身定妆描述再生成"
        )

    from tools.drama_video import generate_character_face_portrait, generate_character_portrait, generate_location_plate
    from tools.drama_characters import environment_anchor_prompt

    if cat == "scene":
        plate_rel = generate_location_plate(slug, rec, seed=seed)
        if not plate_rel:
            detail = str(getattr(generate_location_plate, "last_error", "") or "").strip()
            msg = "主底板生成失败"
            if detail:
                msg += f"：{detail}"
            else:
                msg += "（后端无可用图像模型或网络异常）"
            msg += "，可改用手动上传"
            raise DramaBadRequest(msg)
        patch: dict[str, Any] = {"id": cid, "ref_plate": plate_rel}
        if not str(rec.get("anchor_prompt") or "").strip():
            patch["anchor_prompt"] = environment_anchor_prompt({**rec, **patch})
        upsert_character(slug, patch)
        try:
            from tools.drama_series import invalidate_character_embedding

            invalidate_character_embedding(slug, cid)
        except Exception:
            pass
        try:
            set_ref_locked(slug, cid, True)
        except Exception:
            pass
        _dirty_shots_for_character(slug, cid, ["scene", "clip"])
        out = find_character(load_characters(slug), cid) or {**rec, **patch}
        return enrich_character(slug, out)

    rel = generate_character_portrait(slug, rec, seed=seed)
    if not rel:
        detail = str(getattr(generate_character_portrait, "last_error", "") or "").strip()
        msg = "参考图生成失败"
        if detail:
            msg += f"：{detail}"
        else:
            msg += "（后端无可用图像模型或网络异常）"
        msg += "，可改用手动上传"
        raise DramaBadRequest(msg)
    patch = {"id": cid, "ref": rel}
    rec = {**rec, "ref": rel}

    if cat == "character":
        face_rel = generate_character_face_portrait(slug, rec, seed=seed)
        if not face_rel:
            detail = str(getattr(generate_character_face_portrait, "last_error", "") or "").strip()
            msg = "正脸特写生成失败或与全身定妆不是同一人"
            if detail:
                msg += f"：{detail}"
            msg += "。全身定妆已生成，请重试「生成正脸」或重新生成定妆"
            raise DramaBadRequest(msg)
        patch["ref_face"] = face_rel
    elif cat == "prop":
        if not str(rec.get("anchor_prompt") or "").strip():
            patch["anchor_prompt"] = environment_anchor_prompt({**rec, **patch})
    upsert_character(slug, patch)
    try:
        from tools.drama_series import invalidate_character_embedding

        invalidate_character_embedding(slug, cid)
    except Exception:
        pass
    try:
        set_ref_locked(slug, cid, True)
    except Exception:
        pass
    # Regenerated ref / plate must invalidate bound shot scenes.
    _dirty_shots_for_character(slug, cid, ["scene", "clip"])
    out = find_character(load_characters(slug), cid) or rec
    # 特写缺失时仍返回全身定妆，但提示工作台可重试（仅角色）
    if cat == "character" and not ref_face_exists(slug, out):
        enriched = enrich_character(slug, out)
        enriched["face_ref_missing"] = True
        return enriched
    return enrich_character(slug, out)


def refine_character_ref(slug: str, cid: str, instruction: str) -> dict[str, Any]:
    """根据聊天指令更新全身定妆/正脸描述并重新生成定妆图。"""
    import asyncio

    load_project(slug)
    slug = parse_slug(slug)
    from llm_client import llm_client
    from tools.drama_characters import find_character, load_characters, ref_exists, upsert_character

    text = str(instruction or "").strip()
    if not text:
        raise DramaBadRequest("请输入调整说明")

    rec = find_character(load_characters(slug), cid)
    if rec is None:
        raise DramaNotFound(f"找不到资产：{cid}，请先保存")
    if rec.get("ref_locked") and ref_exists(slug, rec):
        raise DramaBadRequest("参考图已锁定，解锁后才能调整")

    current_look = str(rec.get("look") or "").strip()
    current_face = str(rec.get("look_face") or "").strip()
    category = str(rec.get("category") or "character")
    name = str(rec.get("name") or cid)

    system = (
        "你是漫剧定妆设定助手。根据用户指令更新角色外形文字。"
        "角色定妆用「正面全身」描述，禁止写成三视图/多视角。"
        "只输出一到两行，格式严格为：\n"
        "外形：<更新后的正面全身描述>\n"
        "正脸：<更新后的正脸锚点>（可选，无改动可省略）"
    )
    user = (
        f"资产类型：{category}\n名称：{name}\n"
        f"当前外形：{current_look or '（未填写）'}\n"
        f"当前正脸：{current_face or '（未填写）'}\n\n"
        f"用户调整指令：{text}"
    )
    raw = asyncio.run(
        llm_client.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.4,
            max_tokens=800,
        )
    )
    new_look = current_look
    new_face = current_face
    for line in str(raw or "").splitlines():
        line = line.strip()
        if line.startswith("外形：") or line.startswith("外形:"):
            new_look = line.split("：", 1)[-1].split(":", 1)[-1].strip() or new_look
        elif line.startswith("正脸：") or line.startswith("正脸:"):
            new_face = line.split("：", 1)[-1].split(":", 1)[-1].strip() or new_face
        elif line.startswith("三视图：") or line.startswith("三视图:"):
            # 兼容旧模型输出：当作全身外形
            new_look = line.split("：", 1)[-1].split(":", 1)[-1].strip() or new_look
    if new_look == current_look and raw.strip() and "外形" not in raw and "正脸" not in raw:
        new_look = raw.strip()

    patch_look: dict[str, Any] = {"id": cid, "look": new_look}
    if new_face != current_face:
        patch_look["look_face"] = new_face
    upsert_character(slug, patch_look)
    rec = find_character(load_characters(slug), cid) or rec

    from tools.drama_video import generate_character_face_portrait, generate_character_portrait

    rel = generate_character_portrait(slug, rec)
    if not rel:
        detail = str(getattr(generate_character_portrait, "last_error", "") or "").strip()
        msg = "参考图生成失败"
        if detail:
            msg += f"：{detail}"
        else:
            msg += "（后端无可用图像模型或网络异常）"
        raise DramaBadRequest(msg)
    patch: dict[str, Any] = {"id": cid, "ref": rel}
    rec = {**rec, "ref": rel}
    face_rel = generate_character_face_portrait(slug, rec)
    if not face_rel:
        detail = str(getattr(generate_character_face_portrait, "last_error", "") or "").strip()
        msg = "正脸特写生成失败或与全身定妆不是同一人"
        if detail:
            msg += f"：{detail}"
        raise DramaBadRequest(msg)
    patch["ref_face"] = face_rel
    upsert_character(slug, patch)
    rec = find_character(load_characters(slug), cid) or rec
    try:
        from tools.drama_series import invalidate_character_embedding

        invalidate_character_embedding(slug, cid)
    except Exception:
        pass
    reply = f"已根据「{text}」更新设定并重新生成定妆与正脸特写。"
    return {
        "character": enrich_character(slug, rec),
        "reply": reply,
        "look": new_look,
    }


def refine_shot(
    slug: str,
    episode: int,
    shot_n: int,
    instruction: str,
    *,
    stage: str = "video",
) -> dict[str, Any]:
    """根据聊天指令更新分镜字段（视频/声音页）。"""
    import asyncio
    import json
    import re

    load_project(slug)
    slug = parse_slug(slug)
    n = parse_episode(episode)
    shot_n = parse_shot_n(shot_n)
    text = str(instruction or "").strip()
    if not text:
        raise DramaBadRequest("请输入调整说明")
    stage_key = str(stage or "video").strip().lower()
    if stage_key not in ("video", "voice"):
        raise DramaBadRequest("stage 须为 video 或 voice")

    doc = _ensure_shots_doc(slug, n)
    shot = find_shot(doc, shot_n)
    if shot is None:
        raise DramaNotFound(f"找不到 Shot {shot_n}")

    from llm_client import llm_client

    if stage_key == "video":
        allowed = ("camera", "duration", "i2v", "i2v_ladder", "i2v_source")
        current = {
            "camera": shot.get("camera") or "",
            "duration": shot.get("duration"),
            "i2v": shot.get("i2v") or "auto",
            "i2v_ladder": shot.get("i2v_ladder") or "",
            "i2v_source": shot.get("i2v_source") or "",
            "画面": shot.get("画面") or "",
        }
        system = (
            "你是漫剧分镜视频助手。根据用户指令，仅输出一个 JSON 对象（不要 markdown）。"
            "可改字段：camera, duration, i2v, i2v_ladder, i2v_source。"
            f"camera 可选：{', '.join(CAMERAS)}。"
            "i2v 可选：off / auto / on。"
            "i2v_ladder 可选：L0–L4 或空字符串。"
            "i2v_source 可选：ai / keys / fallback / 空字符串。"
            "duration 为正数秒。"
            "只返回需要修改的字段；另加 reply 字符串用中文简述改了什么。"
            "若无法理解指令，返回 {\"reply\":\"…\"} 且不含其它字段。"
        )
    else:
        allowed = ("字幕", "旁白", "speaker", "voice")
        current = {
            "字幕": shot.get("字幕") or shot.get("对白") or "",
            "旁白": shot.get("旁白") or "",
            "speaker": shot.get("speaker") or "",
            "voice": shot.get("voice") or "",
            "角色": shot.get("角色") or [],
        }
        system = (
            "你是漫剧分镜配音助手。根据用户指令，仅输出一个 JSON 对象（不要 markdown）。"
            "可改字段：字幕（台词，配音+底部字幕）、旁白（画外说明）、speaker、voice。"
            "可用空字符串清空字幕或旁白。"
            "只返回需要修改的字段；另加 reply 字符串用中文简述改了什么。"
            "若无法理解指令，返回 {\"reply\":\"…\"} 且不含其它字段。"
        )

    user = (
        f"当前 Shot {shot_n} 字段：\n{json.dumps(current, ensure_ascii=False)}\n\n"
        f"用户调整指令：{text}"
    )
    raw = asyncio.run(
        llm_client.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.3,
            max_tokens=800,
        )
    )
    raw_text = str(raw or "").strip()
    parsed: dict[str, Any] = {}
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", raw_text)
        if m:
            try:
                parsed = json.loads(m.group(0))
            except json.JSONDecodeError:
                parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}

    patch = {k: parsed[k] for k in allowed if k in parsed}
    reply = str(parsed.get("reply") or "").strip()
    if not patch:
        if not reply:
            reply = "没有识别到可应用的修改，请换一种说法（例如改运镜、时长、字幕或旁白）。"
        return {
            "slug": slug,
            "episode": n,
            "shot": enrich_shot(shot, slug=slug, episode=n),
            "reply": reply,
            "patched": {},
        }

    result = patch_shot(slug, n, shot_n, patch)
    if not reply:
        keys = "、".join(patch.keys())
        reply = f"已更新：{keys}。可点击生成按钮使预览生效。"
    result["reply"] = reply
    result["patched"] = patch
    return result


# 高内聚工作台文件：创意 SSOT + 壳 + 资产运行态 + 分集生产态（含 mix）
SCRIPT_WORKSPACE_KEYS = (
    "series_pack",
    "project",
    "characters",
    "shots",
)


def _pretty_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _parse_json_text(raw: str, *, label: str) -> Any:
    text = str(raw or "").strip()
    if not text:
        raise DramaBadRequest(f"{label} 不能为空")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise DramaBadRequest(f"{label} JSON 无效：{e}") from e


def get_script_workspace(slug: str, episode: int) -> dict[str, Any]:
    """剧本工作台：以 series_pack 为创意真相源，去掉 bible/outline/ep.md 双写。"""
    slug = parse_slug(slug)
    n = parse_episode(episode)
    project = load_project(slug)

    from tools.drama_audio import load_mix
    from tools.drama_characters import load_characters
    from tools.drama_layout import series_pack_rel as pack_rel
    from tools.drama_series_pack import dump_series_pack
    from tools.drama_series_pack_gen import load_saved_series_pack

    characters_path = _rel(slug, "characters.json")
    project_path = _project_rel(slug)
    shots_path = json_rel(slug, n)
    pack_path = pack_rel(slug)

    doc = load_doc(slug, n)
    mix = load_mix(slug, n)
    if isinstance(doc, dict) and "mix" not in doc:
        doc = {**doc, "mix": mix}
    chars = load_characters(slug)

    pack = load_saved_series_pack(slug)
    pack_text = ""
    if pack is not None:
        pack_text = dump_series_pack(pack) + "\n"
    else:
        try:
            p = resolve_safe(pack_path)
            if p.is_file():
                pack_text = p.read_text(encoding="utf-8")
        except Exception:
            pack_text = ""

    files = {
        "series_pack": {
            "key": "series_pack",
            "label": "剧包 series_pack.json（创意 SSOT）",
            "path": pack_path,
            "format": "json",
            "exists": bool(pack_text.strip()),
            "content": pack_text if pack_text.endswith("\n") else (pack_text + ("\n" if pack_text else "")),
        },
        "project": {
            "key": "project",
            "label": "项目壳 project.json",
            "path": project_path,
            "format": "json",
            "exists": True,
            "content": _pretty_json(project),
        },
        "characters": {
            "key": "characters",
            "label": "资产运行态 characters.json",
            "path": characters_path,
            "format": "json",
            "exists": True,
            "content": _pretty_json({"characters": chars}),
        },
        "shots": {
            "key": "shots",
            "label": "分集生产态 shots.json（含 mix）",
            "path": shots_path,
            "format": "json",
            "exists": doc is not None,
            "content": _pretty_json(doc) if doc is not None else "",
        },
    }
    return {
        "slug": slug,
        "episode": n,
        "keys": list(SCRIPT_WORKSPACE_KEYS),
        "files": files,
        "layout": "series_pack_ssot",
    }


def save_script_workspace(
    slug: str,
    episode: int,
    files: dict[str, Any],
    *,
    keys: list[str] | None = None,
) -> dict[str, Any]:
    """Persist workspace files. Creative edits to series_pack; runtime to characters/shots."""
    slug = parse_slug(slug)
    n = parse_episode(episode)
    load_project(slug)
    if not isinstance(files, dict):
        raise DramaBadRequest("files 必须是对象")

    # 兼容旧键名：bible/outline/script/mix 忽略或映射
    alias = {"script": "series_pack", "bible": "series_pack", "outline": "series_pack", "mix": "shots"}
    normalized: dict[str, Any] = {}
    for k, v in files.items():
        normalized[alias.get(k, k)] = v

    wanted = [k for k in (keys or list(normalized.keys())) if k in SCRIPT_WORKSPACE_KEYS or k in alias]
    wanted = [alias.get(k, k) for k in wanted]
    wanted = [k for k in wanted if k in SCRIPT_WORKSPACE_KEYS]
    if not wanted:
        raise DramaBadRequest("没有可保存的文件键")

    saved: list[str] = []
    hints: list[str] = []
    order = [k for k in SCRIPT_WORKSPACE_KEYS if k in wanted]

    for key in order:
        if key not in normalized:
            continue
        raw = normalized[key]
        content = raw if isinstance(raw, str) else (
            raw.get("content") if isinstance(raw, dict) else None
        )
        if content is None:
            raise DramaBadRequest(f"{key} 缺少 content")
        text = str(content)

        if key == "series_pack":
            from tools.drama_series_pack import loads_series_pack
            from tools.drama_series_pack_gen import save_series_pack
            from tools.drama_series_pack_materialize import materialize_series_pack
            from tools.drama_series_pack_validate import assert_series_pack_valid

            data = _parse_json_text(text, label="series_pack.json")
            pack = assert_series_pack_valid(loads_series_pack(data))
            save_series_pack(slug, pack)
            # 同步运行态 / 生产态副本（不写 bible 真相源）
            materialize_series_pack(slug, pack, write_bible=False)
            saved.append(key)
            hints.append("已保存 series_pack 并同步资产/分镜运行态")
        elif key == "shots":
            data = _parse_json_text(text, label="shots.json")
            if not isinstance(data, dict):
                raise DramaBadRequest("shots.json 必须是对象")
            data["slug"] = slug
            data["episode"] = n
            if "shots" not in data or not isinstance(data.get("shots"), list):
                raise DramaBadRequest("shots.json 需要 shots 数组")
            # mix 内嵌时一并落盘
            if isinstance(data.get("mix"), dict):
                from tools.drama_audio import save_mix

                save_mix(slug, n, data["mix"])
            save_doc(data)
            saved.append(key)
        elif key == "characters":
            from tools.drama_characters import save_characters
            from tools.drama_series_pack_materialize import sync_asset_to_series_pack

            data = _parse_json_text(text, label="characters.json")
            if isinstance(data, dict) and isinstance(data.get("characters"), list):
                cards = data["characters"]
            elif isinstance(data, list):
                cards = data
            else:
                raise DramaBadRequest("characters.json 需要 {characters:[…]} 或数组")
            save_characters(slug, cards)
            for rec in cards:
                if isinstance(rec, dict):
                    try:
                        sync_asset_to_series_pack(slug, rec)
                    except Exception:
                        pass
            saved.append(key)
            hints.append("资产运行态已保存；外形文案已回写 series_pack")
        elif key == "project":
            from tools.drama_layout import slim_project_shell, load_pack_or_none

            data = _parse_json_text(text, label="project.json")
            if not isinstance(data, dict):
                raise DramaBadRequest("project.json 必须是对象")
            data["slug"] = slug
            pack = load_pack_or_none(slug)
            if pack is not None:
                data = slim_project_shell(data, pack)
                data["slug"] = slug
            save_project(slug, data)
            saved.append(key)

    workspace = get_script_workspace(slug, n)
    workspace["saved"] = saved
    workspace["hint"] = "；".join(hints) if hints else f"已保存：{', '.join(saved)}"
    return workspace

