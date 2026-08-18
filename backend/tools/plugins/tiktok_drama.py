"""抖音漫剧业务插件（P7）：能力放边缘，不改 agent loop。

单工具 `tiktok_drama`，按 action 分发，避免核心 schema 膨胀。
项目落在 workspace/dramas/{slug}/，路径走 workspace 沙箱。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from tools.loader import add_plugin_prompt_hint
from tools.registry import register
from tools.workspace import resolve_safe, workspace_root

_SLUG_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,39}$")
_MAX_CHARS = 80_000
_ROOT = "dramas"

_GUIDE = """# 抖音漫剧制作规范（竖屏短剧）

## 形式
- 画幅 9:16；单集 30–60 秒；对白约 80–150 字。
- 前 3 秒必须有钩子（冲突/悬念/反差），禁止慢热铺垫。
- 每集一个小反转；结尾留悬念，方便追更。
- 人设少而尖：2–4 个角色，各有一句口头禅或视觉锚点。

## 工作流
1. tiktok_drama action=init 建项目（slug + title + logline）
2. save_bible 写入人设 bible.md
3. save_outline 写入系列大纲 outline.md
4. save_episode 按集写入 episodes/epNN.md
5. parse_shots 解析分镜并写入 videos/epNN/shots.json（分镜真相源）
6. render_episode 按镜生成 clip，再拼接竖屏 mp4
7. 改某一镜用 rerender_shot；layers=scene|overlay|voice|clip|assemble 只重做指定层
8. lock_shot 锁住 scene 后，改台词只换声和字幕，不会覆盖画面
9. lock_shot 锁住 shot（整镜）后，save_episode 改剧本不会覆盖该镜
10. get / list 回看进度；成片 videos/epNN.mp4
11. 只重写脏镜用 rerender_dirty（跳过干净镜与锁层）

## 单集剧本格式（save_episode 的 content）
# EP01 标题
- 时长: 45s
- 钩子: （前3秒）
- 悬念: （结尾）

## 分镜
### Shot 1 (0-3s)
- 画面:
- 对白:
- 字幕:

### Shot 2 (3-12s)
- 画面:
- 对白:
- 字幕:
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ok(**kwargs: Any) -> str:
    return json.dumps({"ok": True, **kwargs}, ensure_ascii=False)


def _err(message: str, **kwargs: Any) -> str:
    return json.dumps({"error": message, **kwargs}, ensure_ascii=False)


def _slug(raw: str) -> str | None:
    s = str(raw or "").strip()
    if _SLUG_RE.match(s):
        return s
    return None


def _rel(*parts: str) -> str:
    return "/".join((_ROOT,) + parts)


def _write_text(rel: str, content: str) -> str:
    if len(content) > _MAX_CHARS:
        raise ValueError(f"content 过长（>{_MAX_CHARS} 字符）")
    target = resolve_safe(rel)
    if target.exists() and target.is_dir():
        raise ValueError("目标是目录，无法写入")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return rel


def _read_text(rel: str) -> str | None:
    target = resolve_safe(rel)
    if not target.is_file():
        return None
    text = target.read_text(encoding="utf-8", errors="replace")
    if len(text) > _MAX_CHARS:
        return text[:_MAX_CHARS]
    return text


def _project_rel(slug: str) -> str:
    return _rel(slug, "project.json")


def _load_project(slug: str) -> dict[str, Any] | None:
    raw = _read_text(_project_rel(slug))
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _save_project(slug: str, data: dict[str, Any]) -> None:
    data["updated_at"] = _utc_now()
    _write_text(_project_rel(slug), json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _action_guide(_args: dict) -> str:
    return _ok(action="guide", content=_GUIDE)


def _action_init(args: dict) -> str:
    slug = _slug(str(args.get("slug") or ""))
    if not slug:
        return _err("slug 须为 1–40 位字母数字、下划线或短横线，且以字母或数字开头")
    title = str(args.get("title") or slug).strip() or slug
    logline = str(args.get("logline") or "").strip()
    overwrite = bool(args.get("overwrite"))

    existing = _load_project(slug)
    if existing and not overwrite:
        return _err("项目已存在", slug=slug, path=_rel(slug), hint="传入 overwrite=true 可重建元数据")

    now = _utc_now()
    project = {
        "slug": slug,
        "title": title,
        "logline": logline,
        "aspect": "9:16",
        "created_at": existing.get("created_at") if existing else now,
        "updated_at": now,
        "episodes": existing.get("episodes") if existing else [],
    }
    _save_project(slug, project)
    files = [_project_rel(slug)]
    if not _read_text(_rel(slug, "README.md")):
        readme = (
            f"# {title}\n\n"
            f"- slug: `{slug}`\n"
            f"- 画幅: 9:16\n"
            f"- 一句话: {logline or '（待写）'}\n\n"
            f"目录：`bible.md` 人设 · `outline.md` 大纲 · `episodes/` 分集剧本\n"
        )
        files.append(_write_text(_rel(slug, "README.md"), readme))
    resolve_safe(_rel(slug, "episodes")).mkdir(parents=True, exist_ok=True)
    return _ok(action="init", slug=slug, path=_rel(slug), files=files, project=project)


def _action_list(_args: dict) -> str:
    root = resolve_safe(_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        data = _load_project(child.name)
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
    return _ok(action="list", workspace=str(workspace_root()), count=len(items), projects=items)


def _action_get(args: dict) -> str:
    slug = _slug(str(args.get("slug") or ""))
    if not slug:
        return _err("需要合法 slug")
    project = _load_project(slug)
    if not project:
        return _err("项目不存在", slug=slug)
    episode = args.get("episode")
    payload: dict[str, Any] = {
        "action": "get",
        "slug": slug,
        "path": _rel(slug),
        "project": project,
    }
    bible = _read_text(_rel(slug, "bible.md"))
    if bible is not None:
        payload["bible"] = bible
    outline = _read_text(_rel(slug, "outline.md"))
    if outline is not None:
        payload["outline"] = outline
    if episode is not None and str(episode).strip() != "":
        try:
            n = int(episode)
        except (TypeError, ValueError):
            return _err("episode 须为正整数")
        if n < 1 or n > 99:
            return _err("episode 范围 1–99")
        ep_rel = _rel(slug, "episodes", f"ep{n:02d}.md")
        content = _read_text(ep_rel)
        if content is None:
            return _err("该集不存在", slug=slug, episode=n, path=ep_rel)
        payload["episode"] = n
        payload["episode_path"] = ep_rel
        payload["episode_content"] = content
        from tools.drama_shots import json_rel, load_doc, public_shot

        shots_doc = load_doc(slug, n)
        if shots_doc:
            payload["shots_json"] = json_rel(slug, n)
            payload["shots"] = [public_shot(s) for s in shots_doc.get("shots") or []]
        video_rel = _rel(slug, "videos", f"ep{n:02d}.mp4")
        video_path = resolve_safe(video_rel)
        if video_path.is_file():
            payload["video_path"] = video_rel
            payload["play_url"] = f"/api/workspace/file?path={video_rel}"
    return _ok(**payload)


def _action_save_md(args: dict, *, filename: str, label: str) -> str:
    slug = _slug(str(args.get("slug") or ""))
    if not slug:
        return _err("需要合法 slug")
    if not _load_project(slug):
        return _err("项目不存在，请先 init", slug=slug)
    content = args.get("content")
    if content is None or not str(content).strip():
        return _err(f"{label} content 不能为空")
    rel = _rel(slug, filename)
    _write_text(rel, str(content).rstrip() + "\n")
    project = _load_project(slug) or {}
    _save_project(slug, project)
    return _ok(action=f"save_{label}", slug=slug, path=rel, chars=len(str(content)))


def _action_save_episode(args: dict) -> str:
    slug = _slug(str(args.get("slug") or ""))
    if not slug:
        return _err("需要合法 slug")
    project = _load_project(slug)
    if not project:
        return _err("项目不存在，请先 init", slug=slug)
    try:
        n = int(args.get("episode"))
    except (TypeError, ValueError):
        return _err("需要 episode（正整数 1–99）")
    if n < 1 or n > 99:
        return _err("episode 范围 1–99")
    content = args.get("content")
    if content is None or not str(content).strip():
        return _err("content 不能为空")
    title = str(args.get("title") or f"第{n}集").strip()
    try:
        seconds = int(args.get("seconds") or 45)
    except (TypeError, ValueError):
        seconds = 45
    seconds = max(15, min(seconds, 90))

    ep_rel = _rel(slug, "episodes", f"ep{n:02d}.md")
    _write_text(ep_rel, str(content).rstrip() + "\n")

    episodes = [e for e in (project.get("episodes") or []) if int(e.get("n") or 0) != n]
    episodes.append({"n": n, "title": title, "seconds": seconds, "path": ep_rel})
    episodes.sort(key=lambda e: int(e.get("n") or 0))
    project["episodes"] = episodes
    _save_project(slug, project)
    synced = None
    try:
        from tools.drama_shots import load_doc, json_rel as shots_json_rel, script_impact
        from tools.drama_video import parse_episode_markdown, sync_shots_doc

        if resolve_safe(_rel(slug, "videos", f"ep{n:02d}", "shots.json")).is_file():
            existing = load_doc(slug, n)
            parsed = parse_episode_markdown(str(content))
            doc = sync_shots_doc(slug, n, str(content), title=title)
            impact = script_impact(
                existing,
                doc,
                old_meta=(existing or {}).get("meta") if existing else {},
                new_meta=parsed.get("meta") or {},
            )
            synced = {
                "shots_json": shots_json_rel(slug, n),
                "dirty": [
                    {"n": s.get("n"), "dirty": s.get("dirty")}
                    for s in doc.get("shots") or []
                    if s.get("dirty")
                ],
                "impact": impact,
            }
    except ValueError:
        synced = None
    result: dict[str, Any] = {
        "action": "save_episode",
        "slug": slug,
        "episode": n,
        "title": title,
        "seconds": seconds,
        "path": ep_rel,
    }
    if synced:
        result["shots"] = synced
    return _ok(**result)


def _episode_number(args: dict) -> tuple[str | None, int | None, str | None]:
    slug = _slug(str(args.get("slug") or ""))
    if not slug:
        return None, None, "需要合法 slug"
    try:
        n = int(args.get("episode"))
    except (TypeError, ValueError):
        return slug, None, "需要 episode（正整数 1–99）"
    if n < 1 or n > 99:
        return slug, None, "episode 范围 1–99"
    return slug, n, None


def _action_parse_shots(args: dict) -> str:
    from tools.drama_shots import public_shot
    from tools.drama_video import sync_shots_doc

    slug, n, err = _episode_number(args)
    if err:
        return _err(err, slug=slug)
    if not _load_project(slug):
        return _err("项目不存在，请先 init", slug=slug)
    ep_rel = _rel(slug, "episodes", f"ep{n:02d}.md")
    content = _read_text(ep_rel)
    if content is None:
        return _err("该集剧本不存在", slug=slug, episode=n, path=ep_rel)
    doc = sync_shots_doc(slug, n, content)
    return _ok(
        action="parse_shots",
        slug=slug,
        episode=n,
        path=ep_rel,
        shots_json=f"{doc.get('work_dir')}/shots.json",
        title=doc.get("title"),
        meta=doc.get("meta") or {},
        count=doc.get("count") or 0,
        shots=[public_shot(s) for s in doc.get("shots") or []],
    )


def _record_video(project: dict[str, Any], result: dict[str, Any]) -> None:
    slug = str(project.get("slug") or result["slug"])
    n = int(result["episode"])
    videos = [v for v in (project.get("videos") or []) if int(v.get("n") or 0) != n]
    videos.append(
        {
            "n": n,
            "path": result["path"],
            "play_url": result["play_url"],
            "shots": result["shots"],
            "bytes": result["bytes"],
            "shots_json": result.get("shots_json"),
        }
    )
    videos.sort(key=lambda v: int(v.get("n") or 0))
    project["videos"] = videos
    _save_project(slug, project)


def _action_render_episode(args: dict) -> str:
    from tools.drama_video import render_episode_video

    slug, n, err = _episode_number(args)
    if err:
        return _err(err, slug=slug)
    project = _load_project(slug)
    if not project:
        return _err("项目不存在，请先 init", slug=slug)
    ep_rel = _rel(slug, "episodes", f"ep{n:02d}.md")
    content = _read_text(ep_rel)
    if content is None:
        return _err("该集剧本不存在，请先 save_episode", slug=slug, episode=n, path=ep_rel)
    ep_meta = next(
        (e for e in (project.get("episodes") or []) if int(e.get("n") or 0) == n),
        {},
    )
    title = str(args.get("title") or ep_meta.get("title") or "").strip()
    force = bool(args.get("force"))
    result = render_episode_video(slug, n, content, title=title, force=force)
    _record_video(project, result)
    return _ok(action="render_episode", **result)


def _parse_layers(raw: Any) -> list[str] | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, list):
        parts = [str(x).strip() for x in raw]
    else:
        parts = [p.strip() for p in str(raw).split(",")]
    layers = [p for p in parts if p]
    return layers or None


def _action_rerender_shot(args: dict) -> str:
    from tools.drama_video import rerender_shot

    slug, n, err = _episode_number(args)
    if err:
        return _err(err, slug=slug)
    project = _load_project(slug)
    if not project:
        return _err("项目不存在，请先 init", slug=slug)
    try:
        shot_n = int(args.get("shot"))
    except (TypeError, ValueError):
        return _err("需要 shot（镜头号，正整数）")
    if shot_n < 1 or shot_n > 99:
        return _err("shot 范围 1–99")

    ep_rel = _rel(slug, "episodes", f"ep{n:02d}.md")
    content = _read_text(ep_rel)
    patch: dict[str, Any] = {}
    for key in ("画面", "对白", "字幕", "camera", "timing"):
        if args.get(key) is not None:
            patch[key] = args.get(key)
    if args.get("duration") is not None:
        try:
            patch["duration"] = float(args.get("duration"))
        except (TypeError, ValueError):
            return _err("duration 须为数字")
    ep_meta = next(
        (e for e in (project.get("episodes") or []) if int(e.get("n") or 0) == n),
        {},
    )
    title = str(args.get("title") or ep_meta.get("title") or "").strip()
    result = rerender_shot(
        slug,
        n,
        shot_n,
        markdown=content,
        title=title,
        patch=patch or None,
        layers=_parse_layers(args.get("layers")),
    )
    if patch and content:
        from tools.drama_video import patch_shot_in_markdown

        updated = patch_shot_in_markdown(content, shot_n, patch)
        if updated != content:
            _write_text(ep_rel, updated.rstrip() + "\n")
            result["episode_md"] = ep_rel
    _record_video(project, result)
    return _ok(action="rerender_shot", **result)


def _action_lock_shot(args: dict) -> str:
    from tools.drama_studio import patch_shot

    slug, n, err = _episode_number(args)
    if err:
        return _err(err, slug=slug)
    if not _load_project(slug):
        return _err("项目不存在，请先 init", slug=slug)
    try:
        shot_n = int(args.get("shot"))
    except (TypeError, ValueError):
        return _err("需要 shot（镜头号，正整数）")
    if shot_n < 1 or shot_n > 99:
        return _err("shot 范围 1–99")
    patch: dict[str, Any] = {}
    if args.get("locked") is not None:
        patch["locked"] = _parse_layers(args.get("locked")) or []
    if args.get("lock") is not None:
        patch["lock"] = args.get("lock")
    if args.get("unlock") is not None:
        patch["unlock"] = args.get("unlock")
    if args.get("layers") and "lock" not in patch and "unlock" not in patch and "locked" not in patch:
        patch["lock"] = args.get("layers")
    if not patch:
        return _err("需要 locked / lock / unlock（层名：scene,overlay,voice,clip,shot）")
    result = patch_shot(slug, n, shot_n, patch)
    return _ok(action="lock_shot", **result)


def _action_rerender_dirty(args: dict) -> str:
    from tools.drama_studio import rerender_dirty_shots

    slug, n, err = _episode_number(args)
    if err:
        return _err(err, slug=slug)
    project = _load_project(slug)
    if not project:
        return _err("项目不存在，请先 init", slug=slug)
    result = rerender_dirty_shots(slug, n)
    _record_video(project, result)
    return _ok(action="rerender_dirty", **result)


def _tiktok_drama(args: dict) -> str:
    action = str(args.get("action") or "").strip().lower()
    handlers = {
        "guide": _action_guide,
        "init": _action_init,
        "list": _action_list,
        "get": _action_get,
        "save_bible": lambda a: _action_save_md(a, filename="bible.md", label="bible"),
        "save_outline": lambda a: _action_save_md(a, filename="outline.md", label="outline"),
        "save_episode": _action_save_episode,
        "parse_shots": _action_parse_shots,
        "render_episode": _action_render_episode,
        "rerender_shot": _action_rerender_shot,
        "lock_shot": _action_lock_shot,
        "rerender_dirty": _action_rerender_dirty,
    }
    handler = handlers.get(action)
    if not handler:
        return _err(
            "未知 action",
            action=action or None,
            allowed=list(handlers.keys()),
        )
    try:
        return handler(args)
    except ValueError as e:
        return _err(str(e))
    except OSError as e:
        return _err(str(e))
    except RuntimeError as e:
        return _err(str(e))


def register_tiktok_drama() -> None:
    register(
        "tiktok_drama",
        description=(
            "抖音竖屏漫剧项目工具。action: "
            "guide（规范与剧本格式）、init（建项目）、list、get、"
            "save_bible（人设）、save_outline（大纲）、save_episode（分集剧本）、"
            "parse_shots（解析并落盘 shots.json）、render_episode（按镜出 clip 再拼接）、"
            "rerender_shot（只重渲一镜或指定层）、lock_shot（锁定/解锁 scene/overlay/voice/clip/shot）、"
            "rerender_dirty（只重渲脏镜）。"
            "文件写在 workspace/dramas/{slug}/；成片为 videos/epNN.mp4。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "guide | init | list | get | save_bible | save_outline | save_episode | parse_shots | render_episode | rerender_shot | lock_shot | rerender_dirty",
                    "enum": [
                        "guide",
                        "init",
                        "list",
                        "get",
                        "save_bible",
                        "save_outline",
                        "save_episode",
                        "parse_shots",
                        "render_episode",
                        "rerender_shot",
                        "lock_shot",
                        "rerender_dirty",
                    ],
                },
                "slug": {
                    "type": "string",
                    "description": "项目短名，字母数字/下划线/短横线，如 cold-palace",
                },
                "title": {
                    "type": "string",
                    "description": "init / save_episode 用的标题",
                },
                "logline": {
                    "type": "string",
                    "description": "init 用的一句话故事",
                },
                "overwrite": {
                    "type": "boolean",
                    "description": "init 时是否覆盖已有 project.json",
                },
                "episode": {
                    "type": "integer",
                    "description": "集数 1–99，get / save_episode / parse_shots / render_episode / rerender_shot / rerender_dirty 使用",
                },
                "shot": {
                    "type": "integer",
                    "description": "镜头号，rerender_shot 使用",
                },
                "layers": {
                    "type": "string",
                    "description": "rerender_shot 要重做的层，逗号分隔：scene,overlay,voice,clip,assemble；默认按脏层推断。lock_shot 时作为要锁定的层",
                },
                "force": {
                    "type": "boolean",
                    "description": "render_episode 时强制重渲全部镜头（忽略已有 clip）",
                },
                "字幕": {
                    "type": "string",
                    "description": "rerender_shot 时覆盖该镜字幕",
                },
                "对白": {
                    "type": "string",
                    "description": "rerender_shot 时覆盖该镜对白",
                },
                "画面": {
                    "type": "string",
                    "description": "rerender_shot 时覆盖该镜画面描述",
                },
                "camera": {
                    "type": "string",
                    "description": "rerender_shot 时覆盖运镜：punch_in / pan_right / rise 等",
                },
                "duration": {
                    "type": "number",
                    "description": "rerender_shot 时覆盖该镜秒数",
                },
                "lock": {
                    "type": "string",
                    "description": "lock_shot 要锁定的层，逗号分隔：scene,overlay,voice,clip,shot（shot=整镜，改剧本不覆盖）",
                },
                "unlock": {
                    "type": "string",
                    "description": "lock_shot 要解锁的层，逗号分隔",
                },
                "locked": {
                    "type": "string",
                    "description": "lock_shot 时整表替换锁定层；空字符串表示全部解锁",
                },
                "seconds": {
                    "type": "integer",
                    "description": "save_episode 预估时长（15–90，默认 45）",
                },
                "content": {
                    "type": "string",
                    "description": "save_bible / save_outline / save_episode 的 Markdown 正文",
                },
            },
            "required": ["action"],
        },
        handler=_tiktok_drama,
    )
    add_plugin_prompt_hint(
        "抖音漫剧请调用 tiktok_drama：先 guide 看规范，再 init 建项目，"
        "save_bible / save_outline / save_episode 落盘到 workspace/dramas/{slug}/。"
        "写完分集后先 parse_shots 落盘 shots.json，再 render_episode。"
        "只改某一镜请用 rerender_shot；layers 可指定 scene/overlay/voice/clip。"
        "锁住的层用 lock_shot，禁止覆盖。例如锁 scene 后改对白只重配音和字幕；"
        "锁 shot（整镜）后改剧本不会覆盖该镜。脏镜一键重渲用 rerender_dirty。"
        "回复里用返回的 play_url 做成 markdown 链接，"
        "例如 [预览第1集](/api/workspace/file?path=dramas/slug/videos/ep01.mp4)。"
    )


register_tiktok_drama()
