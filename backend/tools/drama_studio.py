"""Drama workbench service (D1). REST uses this; agent loop is not involved."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote

from tools.drama_characters import (
    VOICES,
    CharacterError,
    delete_character,
    load_characters,
    normalize_roles,
    primary_voice,
    resolve_shot_characters,
    save_character_ref,
    set_ref_locked,
    suggest_character_id,
    upsert_character,
)
from tools.drama_models import (
    SHOT_KINDS,
    SHOT_SIZES,
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
    find_shot,
    json_rel,
    load_doc,
    public_shot,
    save_doc,
    script_impact,
    set_shot_locks,
    TRANSITIONS,
    I2V_MODES,
    normalize_i2v_mode,
)
from tools.drama_timeline import apply_timeline_patch, patch_timeline_doc, public_timeline
from tools.workspace import resolve_safe, workspace_root

_SLUG_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,39}$")
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


class DramaNotFound(LookupError):
    pass


class DramaBadRequest(ValueError):
    pass


def play_url(rel: str) -> str:
    return f"/api/workspace/file?path={quote(str(rel), safe='/')}"


def parse_slug(raw: str) -> str:
    slug = str(raw or "").strip()
    if not _SLUG_RE.match(slug):
        raise DramaBadRequest("slug 须为 1–40 位字母数字、下划线或短横线，且以字母或数字开头")
    return slug


def parse_episode(raw: Any) -> int:
    try:
        n = int(raw)
    except (TypeError, ValueError) as e:
        raise DramaBadRequest("episode 须为正整数 1–99") from e
    if n < 1 or n > 99:
        raise DramaBadRequest("episode 范围 1–99")
    return n


def parse_shot_n(raw: Any) -> int:
    try:
        n = int(raw)
    except (TypeError, ValueError) as e:
        raise DramaBadRequest("shot 须为正整数 1–99") from e
    if n < 1 or n > 99:
        raise DramaBadRequest("shot 范围 1–99")
    return n


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
    raw = _read_text(_rel(name, "project.json"))
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


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


def _asset_meta(rel: str) -> dict[str, Any]:
    info = {"path": rel, "exists": False, "bytes": 0, "url": None}
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
    return info


def enrich_shot(shot: dict[str, Any], *, slug: str = "") -> dict[str, Any]:
    pub = public_shot(shot)
    assets = pub.get("assets") or {}
    pub["files"] = {layer: _asset_meta(str(rel or "")) for layer, rel in assets.items()}
    clip = pub["files"].get("clip") or {}
    pub["preview_url"] = clip.get("url") or (pub["files"].get("scene") or {}).get("url")
    pub["chosen"] = shot.get("chosen") or ""
    pub["candidates"] = []
    for item in shot.get("candidates") or []:
        meta = _asset_meta(str(item.get("path") or ""))
        pub["candidates"].append(
            {
                "id": item.get("id"),
                "path": item.get("path"),
                "source": item.get("source"),
                "seed": item.get("seed") or 0,
                "url": meta.get("url"),
                "exists": meta["exists"],
                "chosen": item.get("id") == shot.get("chosen"),
            }
        )
    if slug:
        cards = load_characters(slug)
        cast = resolve_shot_characters(shot, cards)
        pub["cast"] = [{"id": c["id"], "name": c["name"], "voice": c["voice"]} for c in cast]
        pub["voice_id"] = primary_voice(cast) if cast else ""
        pub["route"] = estimate_i2v(slug, shot)
        from tools.drama_lip import estimate_lip
        from tools.drama_qc import qc_passed

        pub["lip"] = estimate_lip(slug, shot)
        pub["identity"] = shot.get("identity") if isinstance(shot.get("identity"), dict) else None
        pub["identity_hint"] = str(shot.get("identity_hint") or "")
        pub["identity_passed"] = qc_passed(pub["identity"])
    return pub


def list_projects() -> dict[str, Any]:
    root = resolve_safe(_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        data = load_project_file(child.name)
        if not data:
            continue
        episodes = data.get("episodes") or []
        videos = data.get("videos") or []
        items.append(
            {
                "slug": data.get("slug") or child.name,
                "title": data.get("title") or child.name,
                "logline": data.get("logline") or "",
                "episodes": len(episodes),
                "videos": len(videos),
                "path": _rel(child.name),
                "updated_at": data.get("updated_at"),
            }
        )
    return {"workspace": str(workspace_root()), "count": len(items), "projects": items}


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
        "voices": [{"id": vid, "label": label} for vid, label in VOICES],
    }


def patch_project(slug: str, patch: dict[str, Any]) -> dict[str, Any]:
    project = load_project(slug)
    if "title" in patch and patch["title"] is not None:
        title = str(patch["title"]).strip()
        if not title:
            raise DramaBadRequest("title 不能为空")
        project["title"] = title
    if "logline" in patch and patch["logline"] is not None:
        project["logline"] = str(patch["logline"]).strip()
    save_project(slug, project)
    return get_project(slug)


def _public_coverage(doc: dict[str, Any] | None) -> dict[str, Any]:
    from tools.drama_director import public_coverage

    return public_coverage(doc)


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
    doc = load_doc(slug, n)
    video_rel = _rel(slug, "videos", f"ep{n:02d}.mp4")
    video = _asset_meta(video_rel)
    shots = [enrich_shot(s, slug=slug) for s in (doc.get("shots") or [])] if doc else []
    from tools.drama_video import _probe_duration

    timeline = public_timeline(doc, probe_duration=_probe_duration) if doc else None
    models = load_models(slug)
    from tools.drama_audio import public_mix

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
        "cameras": list(CAMERAS),
        "characters": list_characters(slug),
        "voices": [{"id": vid, "label": label} for vid, label in VOICES],
        "layer_ids": ["scene", "overlay", "voice", "motion", "lip", "clip"],
        "transitions": list(TRANSITIONS),
        "i2v_modes": list(I2V_MODES),
        "shot_kinds": list(SHOT_KINDS),
        "shot_sizes": list(SHOT_SIZES),
        "models": public_models(models),
        "cost": estimate_episode_i2v(slug, (doc or {}).get("shots") or []),
        "coverage": _public_coverage(doc),
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
    if doc is not None:
        return doc
    ep = get_episode(slug, episode)
    script = ep.get("script")
    if not script:
        raise DramaNotFound("没有 shots.json，也没有分集剧本。请先 parse_shots 或 save_episode")
    from tools.drama_video import sync_shots_doc

    return sync_shots_doc(slug, episode, str(script), title=str(ep.get("title") or ""))


def patch_shot(slug: str, episode: int, shot_n: int, patch: dict[str, Any]) -> dict[str, Any]:
    slug = parse_slug(slug)
    n = parse_episode(episode)
    shot_n = parse_shot_n(shot_n)
    allowed = ("画面", "对白", "字幕", "角色", "camera", "timing", "duration", "trim_in", "trim_out", "volume", "transition", "i2v", "kind", "size", "speaker")
    body = {k: patch[k] for k in allowed if k in patch and patch[k] is not None}
    timeline_keys = ("trim_in", "trim_out", "volume", "transition")
    timeline_body = {k: body.pop(k) for k in timeline_keys if k in body}
    has_lock = any(patch.get(k) is not None for k in ("locked", "lock", "unlock") if k in patch)
    if "duration" in body:
        try:
            body["duration"] = float(body["duration"])
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
    if not body and not timeline_body and not has_lock:
        raise DramaBadRequest("没有可更新的字段（画面 / 对白 / 字幕 / 角色 / camera / duration / kind / speaker / 时间线 / locked）")

    doc = _ensure_shots_doc(slug, n)
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
    if body:
        if "shot" in (shot.get("locked") or []):
            dirty = []
        else:
            try:
                dirty = apply_patch(shot, body)
            except ValueError as e:
                raise DramaBadRequest(str(e)) from e
            script_rel = str(doc.get("script_path") or _rel(slug, "episodes", f"ep{n:02d}.md"))
            script = _read_text(script_rel)
            if script is not None:
                from tools.drama_video import patch_shot_in_markdown

                updated = patch_shot_in_markdown(script, shot_n, body)
                if updated != script:
                    _write_text(script_rel, updated.rstrip() + "\n")
    if timeline_body:
        apply_timeline_patch(shot, timeline_body)
    if "i2v" in body:
        if "clip" not in (shot.get("locked") or []) and "clip" not in (shot.get("dirty") or []):
            shot.setdefault("dirty", []).append("clip")
            shot["status"] = "dirty"
    save_doc(doc)

    return {
        "slug": slug,
        "episode": n,
        "shot": enrich_shot(shot, slug=slug),
        "dirty": dirty or list(shot.get("dirty") or []),
        "locked": list(shot.get("locked") or []),
        "shots_json": json_rel(slug, n),
    }


def rerender_one_shot(slug: str, episode: int, shot_n: int, layers: list[str] | None = None) -> dict[str, Any]:
    slug = parse_slug(slug)
    n = parse_episode(episode)
    shot_n = parse_shot_n(shot_n)
    from tools.drama_video import rerender_shot

    return rerender_shot(slug, n, shot_n, layers=layers)


def generate_candidates(slug: str, episode: int, shot_n: int, count: int | None = None) -> dict[str, Any]:
    slug = parse_slug(slug)
    n = parse_episode(episode)
    shot_n = parse_shot_n(shot_n)
    doc = _ensure_shots_doc(slug, n)
    shot = find_shot(doc, shot_n)
    if shot is None:
        raise DramaNotFound(f"找不到 Shot {shot_n}")
    if "shot" in (shot.get("locked") or []):
        raise DramaBadRequest("整镜已锁定，不能重抽出图")
    from tools.drama_video import generate_shot_candidates

    ep_title = str(doc.get("title") or f"第{n}集")
    created = generate_shot_candidates(slug, n, shot, title=ep_title, count=count or 4)
    save_doc(doc)
    return {
        "slug": slug,
        "episode": n,
        "shot": enrich_shot(shot, slug=slug),
        "created": [c.get("id") for c in created],
        "chosen": shot.get("chosen") or "",
    }


def _rebuild_clip_keep_voice(slug: str, episode: int, shot_n: int, doc: dict[str, Any], shot: dict[str, Any]) -> dict[str, Any]:
    from tools.drama_video import ffmpeg_available, rerender_shot

    save_doc(doc)
    if "clip" in (shot.get("locked") or []):
        return {"rebuilt_layers": [], "skipped_layers": ["clip"], "assemble": "unchanged"}
    if not ffmpeg_available():
        dirty = list(shot.get("dirty") or [])
        if "clip" not in dirty:
            dirty.append("clip")
        shot["dirty"] = dirty
        shot["status"] = "dirty"
        save_doc(doc)
        return {"rebuilt_layers": [], "skipped_layers": ["clip"], "assemble": "unchanged", "hint": "未找到 ffmpeg，已换图，成片待重渲"}
    return rerender_shot(slug, episode, shot_n, layers=["clip"])


def choose_candidate(slug: str, episode: int, shot_n: int, cid: str) -> dict[str, Any]:
    slug = parse_slug(slug)
    n = parse_episode(episode)
    shot_n = parse_shot_n(shot_n)
    doc = _ensure_shots_doc(slug, n)
    shot = find_shot(doc, shot_n)
    if shot is None:
        raise DramaNotFound(f"找不到 Shot {shot_n}")
    from tools.drama_video import choose_shot_candidate

    try:
        cand = choose_shot_candidate(shot, cid)
    except ValueError as e:
        raise DramaBadRequest(str(e)) from e
    set_shot_locks(shot, lock=["scene"])
    result = _rebuild_clip_keep_voice(slug, n, shot_n, doc, shot)
    payload = {
        "slug": slug,
        "episode": n,
        "shot": enrich_shot(find_shot(load_doc(slug, n) or doc, shot_n) or shot, slug=slug),
        "chosen": cand.get("id"),
        "voice_rebuilt": False,
        "rebuilt_layers": result.get("rebuilt_layers") or result.get("rebuilt") or [],
    }
    payload.update({k: result[k] for k in ("assemble", "hint") if k in result})
    return payload


def upload_shot_scene(slug: str, episode: int, shot_n: int, data: bytes) -> dict[str, Any]:
    slug = parse_slug(slug)
    n = parse_episode(episode)
    shot_n = parse_shot_n(shot_n)
    doc = _ensure_shots_doc(slug, n)
    shot = find_shot(doc, shot_n)
    if shot is None:
        raise DramaNotFound(f"找不到 Shot {shot_n}")
    from tools.drama_video import upload_shot_candidate

    try:
        cand = upload_shot_candidate(slug, n, shot, data)
    except ValueError as e:
        raise DramaBadRequest(str(e)) from e
    set_shot_locks(shot, lock=["scene"])
    result = _rebuild_clip_keep_voice(slug, n, shot_n, doc, shot)
    payload = {
        "slug": slug,
        "episode": n,
        "shot": enrich_shot(find_shot(load_doc(slug, n) or doc, shot_n) or shot, slug=slug),
        "chosen": cand.get("id"),
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


def export_episode(slug: str, episode: int, *, background: bool = False) -> dict[str, Any]:
    slug = parse_slug(slug)
    n = parse_episode(episode)
    if background:
        return enqueue_job(slug, n, "export")
    doc = _ensure_shots_doc(slug, n)
    from tools.drama_audio import assert_export_licensed, load_mix
    from tools.drama_video import assemble_episode, ffmpeg_available

    if not ffmpeg_available():
        raise DramaBadRequest("未找到 ffmpeg，无法导出整集")
    try:
        assert_export_licensed(slug, load_mix(slug, n))
        mode = assemble_episode(doc)
    except ValueError as e:
        raise DramaBadRequest(str(e)) from e
    ep = get_episode(slug, n)
    ep["assemble"] = mode
    ep["mix_mode"] = (load_doc(slug, n) or {}).get("mix")
    return ep


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
    from tools.drama_video import parse_episode_markdown, sync_shots_doc

    project = load_project(slug)
    existing = load_doc(slug, n)
    parsed = parse_episode_markdown(text)
    if not parsed.get("shots"):
        raise DramaBadRequest("剧本里没有分镜（需要 ### Shot N (0-3s) 格式）")
    ep_title = str(title or parsed.get("title") or f"第{n}集").strip()
    ep_rel = _rel(slug, "episodes", f"ep{n:02d}.md")
    _write_text(ep_rel, text.rstrip() + "\n")

    episodes = [e for e in (project.get("episodes") or []) if int(e.get("n") or 0) != n]
    meta = parsed.get("meta") or {}
    seconds = 45
    raw_sec = str(meta.get("时长") or "")
    digits = "".join(ch for ch in raw_sec if ch.isdigit())
    if digits:
        seconds = max(15, min(int(digits), 90))
    old_ep = next((e for e in (project.get("episodes") or []) if int(e.get("n") or 0) == n), {})
    if old_ep.get("seconds") and not digits:
        seconds = int(old_ep.get("seconds") or 45)
    episodes.append({"n": n, "title": ep_title, "seconds": seconds, "path": ep_rel})
    episodes.sort(key=lambda e: int(e.get("n") or 0))
    project["episodes"] = episodes
    save_project(slug, project)

    merged = sync_shots_doc(slug, n, text, title=ep_title)
    impact = script_impact(
        existing,
        merged,
        old_meta=(existing or {}).get("meta") if existing else {},
        new_meta=parsed.get("meta") or {},
    )
    payload = get_episode(slug, n)
    payload["impact"] = impact
    return payload


def rerender_dirty_shots(slug: str, episode: int) -> dict[str, Any]:
    """Enqueue background rerender of dirty shots (D7)."""
    slug = parse_slug(slug)
    n = parse_episode(episode)
    ep = get_episode(slug, n)
    if not ep.get("script"):
        raise DramaNotFound("没有分集剧本")
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


def generate_i2v_shot(slug: str, episode: int, shot_n: int) -> dict[str, Any]:
    slug = parse_slug(slug)
    n = parse_episode(episode)
    shot_n = parse_shot_n(shot_n)
    doc = _ensure_shots_doc(slug, n)
    shot = find_shot(doc, shot_n)
    if shot is None:
        raise DramaNotFound(f"找不到 Shot {shot_n}")
    from tools.drama_i2v import should_try_i2v

    if not should_try_i2v(shot, slug=slug):
        est = estimate_i2v(slug, shot)
        if est.get("ladder") == "L0":
            raise DramaBadRequest("该镜为 L0（定场类），强制静图运镜，不能生成 I2V")
        raise DramaBadRequest("请先将 I2V 设为 on，或在 auto 模式下锁定画面（scene）")
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
    from tools.drama_qc import qc_passed, qc_shot_identity

    identity = qc_shot_identity(slug, n, shot, apply=True)
    save_doc(doc)
    return {
        "slug": slug,
        "episode": n,
        "n": shot_n,
        "identity": identity,
        "passed": qc_passed(identity),
        "shot": enrich_shot(shot, slug=slug),
    }


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
    doc = save_models(slug, current)
    return {"slug": slug, "models": public_models(doc)}


def classify_shots(slug: str, episode: int, *, force: bool = False) -> dict[str, Any]:
    slug = parse_slug(slug)
    n = parse_episode(episode)
    load_models(slug)
    doc = _ensure_shots_doc(slug, n)
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
        "shots": [enrich_shot(s, slug=slug) for s in (doc.get("shots") or [])],
        "cost": estimate_episode_i2v(slug, doc.get("shots") or []),
    }


def rerender_dirty_shots_sync(slug: str, episode: int) -> dict[str, Any]:
    """Synchronous rerender — used by tests and legacy callers."""
    slug = parse_slug(slug)
    n = parse_episode(episode)
    ep = get_episode(slug, n)
    markdown = ep.get("script")
    if not markdown:
        raise DramaNotFound("没有分集剧本")
    from tools.drama_video import render_episode_video

    result = render_episode_video(slug, n, str(markdown), title=str(ep.get("title") or ""))
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
    pub = dict(char)
    meta = _asset_meta(str(char.get("ref") or ""))
    pub["ref_exists"] = bool(meta["exists"])
    pub["ref_url"] = meta.get("url")
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
        "voices": [{"id": vid, "label": label} for vid, label in VOICES],
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
            if cid not in normalize_roles(shot.get("角色")):
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
    layers: list[str] = []
    if before:
        if str(before.get("look") or "") != str(rec.get("look") or "") or str(
            before.get("colors") or ""
        ) != str(rec.get("colors") or ""):
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
    try:
        rec = save_character_ref(slug, cid, data)
    except CharacterError as e:
        raise DramaBadRequest(str(e)) from e
    return enrich_character(slug, rec)
