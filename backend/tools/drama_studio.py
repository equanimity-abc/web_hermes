"""Drama workbench service (D1). REST uses this; agent loop is not involved."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote

from tools.drama_shots import (
    apply_patch,
    find_shot,
    json_rel,
    load_doc,
    public_shot,
    save_doc,
    script_impact,
    set_shot_locks,
)
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


def enrich_shot(shot: dict[str, Any]) -> dict[str, Any]:
    pub = public_shot(shot)
    assets = pub.get("assets") or {}
    pub["files"] = {layer: _asset_meta(str(rel or "")) for layer, rel in assets.items()}
    clip = pub["files"].get("clip") or {}
    pub["preview_url"] = clip.get("url") or (pub["files"].get("scene") or {}).get("url")
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
    shots = [enrich_shot(s) for s in (doc.get("shots") or [])] if doc else []
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
        "video_path": video_rel if video["exists"] else None,
        "play_url": video.get("url") if video["exists"] else None,
        "cameras": list(CAMERAS),
        "layer_ids": ["scene", "overlay", "voice", "clip"],
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
    allowed = ("画面", "对白", "字幕", "camera", "timing", "duration")
    body = {k: patch[k] for k in allowed if k in patch and patch[k] is not None}
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
    if not body and not has_lock:
        raise DramaBadRequest("没有可更新的字段（画面 / 对白 / 字幕 / camera / duration / locked）")

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
            dirty = apply_patch(shot, body)
            script_rel = str(doc.get("script_path") or _rel(slug, "episodes", f"ep{n:02d}.md"))
            script = _read_text(script_rel)
            if script is not None:
                from tools.drama_video import patch_shot_in_markdown

                updated = patch_shot_in_markdown(script, shot_n, body)
                if updated != script:
                    _write_text(script_rel, updated.rstrip() + "\n")
    save_doc(doc)

    return {
        "slug": slug,
        "episode": n,
        "shot": enrich_shot(shot),
        "dirty": dirty or list(shot.get("dirty") or []),
        "locked": list(shot.get("locked") or []),
        "shots_json": json_rel(slug, n),
    }


def rerender_one_shot(slug: str, episode: int, shot_n: int, layers: list[str] | None = None) -> dict[str, Any]:
    slug = parse_slug(slug)
    n = parse_episode(episode)
    shot_n = parse_shot_n(shot_n)
    from tools.drama_video import rerender_shot

    result = rerender_shot(slug, n, shot_n, layers=layers)
    return result


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
