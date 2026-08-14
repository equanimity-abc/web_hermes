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
5. render_episode 按分镜生成画面 + 运镜 + 配音，合成竖屏 mp4
6. get / list 回看进度；视频在 videos/epNN.mp4

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
    return _ok(
        action="save_episode",
        slug=slug,
        episode=n,
        title=title,
        seconds=seconds,
        path=ep_rel,
    )


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
    from tools.drama_video import parse_episode_markdown

    slug, n, err = _episode_number(args)
    if err:
        return _err(err, slug=slug)
    if not _load_project(slug):
        return _err("项目不存在，请先 init", slug=slug)
    ep_rel = _rel(slug, "episodes", f"ep{n:02d}.md")
    content = _read_text(ep_rel)
    if content is None:
        return _err("该集剧本不存在", slug=slug, episode=n, path=ep_rel)
    parsed = parse_episode_markdown(content)
    return _ok(action="parse_shots", slug=slug, episode=n, path=ep_rel, **parsed)


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
    result = render_episode_video(slug, n, content, title=title)
    videos = [v for v in (project.get("videos") or []) if int(v.get("n") or 0) != n]
    videos.append(
        {
            "n": n,
            "path": result["path"],
            "play_url": result["play_url"],
            "shots": result["shots"],
            "bytes": result["bytes"],
        }
    )
    videos.sort(key=lambda v: int(v.get("n") or 0))
    project["videos"] = videos
    _save_project(slug, project)
    return _ok(action="render_episode", **result)


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
            "parse_shots（解析分镜）、render_episode（分镜出画面+运镜+配音，生成竖屏视频）。"
            "文件写在 workspace/dramas/{slug}/；成片为 videos/epNN.mp4。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "guide | init | list | get | save_bible | save_outline | save_episode | parse_shots | render_episode",
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
                    "description": "集数 1–99，get / save_episode / parse_shots / render_episode 使用",
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
        "写完分集后立刻 render_episode：会按「画面」生成镜头画面并加运镜/配音，"
        "不要再用 write_file 手动画字幕卡。回复里用返回的 play_url 做成 markdown 链接，"
        "例如 [预览第1集](/api/workspace/file?path=dramas/slug/videos/ep01.mp4)。"
    )


register_tiktok_drama()
