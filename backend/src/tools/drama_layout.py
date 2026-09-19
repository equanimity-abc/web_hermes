"""Drama project file layout — high cohesion, low coupling.

Target layout (SeriesPack era)::

    dramas/{slug}/
      project.json          # 壳：slug/title/aspect/settings/集索引（不含创意正文）
      series_pack.json      # 创意唯一真相源（人设/场景/道具/分镜 still+motion+台词）
      characters.json       # 资产运行态（定妆路径、锁、音色 id）——外形文案以 pack 为准
      characters/*.png      # 定妆媒体
      videos/epNN/
        shots.json          # 分集生产态（候选图/锁定/QC/资产路径 + 可选 mix）
        mix.json            # 兼容旧版；新写入优先嵌进 shots.json["mix"]
        *.png / *.mp4 / …   # 渲染产物
      exports/              # 可选导出视图（bible.md / outline.md），非真相源

已废弃作为真相源（可读兼容，不再主动维护）::

    bible.md / outline.md / episodes/epNN.md
    step1_script/ 下的 bible·outline·ep.md 副本

职责边界::

    series_pack  → 写创意（look / still / motion / dialogue / plate）
    characters   → 写运行态（ref / ref_face / ref_locked / voice）
    shots.json   → 写生产态（candidates / locked / assets / qc / mix）
    project.json → 写项目壳与开关（manual_voice 等）
"""

from __future__ import annotations

import json
from typing import Any

from tools.workspace import resolve_safe

LAYOUT_VERSION = "2.0.0"

# 创意字段：以 series_pack 为准，load 时覆盖运行态副本
CREATIVE_SHOT_KEYS = (
    "still",
    "画面",
    "motion",
    "shot_size",
    "size",
    "camera",
    "字幕",
    "旁白",
    "角色",
    "地点",
    "location_id",
    "道具",
    "prop_ids",
    "kind",
    "speaker",
    "audio_mode",
    "sfx",
    "timing",
    "start",
    "end",
    "duration",
)

CREATIVE_ASSET_KEYS = (
    "look",
    "look_face",
    "trait",
    "catchphrase",
    "gender",
    "age_band",
    "voice_hint",
    "name",
)


def project_rel(slug: str) -> str:
    return f"dramas/{slug}/project.json"


def series_pack_rel(slug: str) -> str:
    return f"dramas/{slug}/series_pack.json"


def characters_rel(slug: str) -> str:
    return f"dramas/{slug}/characters.json"


def episode_shots_rel(slug: str, episode: int) -> str:
    return f"dramas/{slug}/videos/ep{int(episode):02d}/shots.json"


def episode_mix_rel(slug: str, episode: int) -> str:
    return f"dramas/{slug}/videos/ep{int(episode):02d}/mix.json"


def exports_dir_rel(slug: str) -> str:
    return f"dramas/{slug}/exports"


def layout_readme() -> str:
    return __doc__ or ""


def has_series_pack(slug: str) -> bool:
    try:
        return resolve_safe(series_pack_rel(slug)).is_file()
    except ValueError:
        return False


def load_pack_or_none(slug: str) -> Any | None:
    try:
        from tools.drama_series_pack_gen import load_saved_series_pack

        return load_saved_series_pack(slug)
    except Exception:
        return None


def _pack_shot_maps(pack: Any, episode: int) -> tuple[dict[int, Any], dict[str, str], dict[str, str], dict[str, str]]:
    cast_name = {c.id: c.name for c in (pack.cast or [])}
    loc_name = {x.id: x.name for x in (pack.locations or [])}
    prop_name = {p.id: p.name for p in (pack.props or [])}
    by_n: dict[int, Any] = {}
    for ep in pack.episodes or []:
        if int(ep.n) != int(episode):
            continue
        for shot in ep.shots or []:
            by_n[int(shot.n)] = shot
        break
    return by_n, cast_name, loc_name, prop_name


def hydrate_shot_from_pack_shot(
    row: dict[str, Any],
    pack_shot: Any,
    *,
    cast_name: dict[str, str],
    loc_name: dict[str, str],
    prop_name: dict[str, str],
) -> dict[str, Any]:
    """用 SeriesPack 镜头覆盖运行态里的创意字段；保留 candidates/locked/assets/qc。"""
    from tools.drama_series_pack_materialize import pack_shot_to_legacy

    legacy = pack_shot_to_legacy(
        pack_shot,
        cast_name_by_id=cast_name,
        loc_name_by_id=loc_name,
        prop_name_by_id=prop_name,
    )
    out = dict(row)
    for key in CREATIVE_SHOT_KEYS:
        if key in legacy:
            out[key] = legacy[key]
    out["source"] = "series_pack"
    out["_creative_ssot"] = "series_pack"
    return out


def hydrate_episode_doc_from_pack(doc: dict[str, Any], pack: Any) -> dict[str, Any]:
    """shots.json 生产态 ← 创意字段从 pack 注入。"""
    if not isinstance(doc, dict) or pack is None:
        return doc
    episode = int(doc.get("episode") or 0)
    if episode < 1:
        return doc
    by_n, cast_name, loc_name, prop_name = _pack_shot_maps(pack, episode)
    if not by_n:
        return doc
    rows = []
    for row in doc.get("shots") or []:
        if not isinstance(row, dict):
            continue
        n = int(row.get("n") or 0)
        ps = by_n.get(n)
        if ps is None:
            rows.append(row)
            continue
        rows.append(
            hydrate_shot_from_pack_shot(
                row,
                ps,
                cast_name=cast_name,
                loc_name=loc_name,
                prop_name=prop_name,
            )
        )
    out = dict(doc)
    out["shots"] = rows
    # 集标题 / 配乐意图：pack 优先
    for ep in pack.episodes or []:
        if int(ep.n) != episode:
            continue
        if ep.title:
            out["title"] = f"EP{episode:02d} {ep.title}".strip()
        break
    style = getattr(pack, "style", None)
    if style is not None:
        intent = " ".join(
            x for x in (getattr(style, "bgm_mood", ""), getattr(style, "bgm_instruments", "")) if x
        ).strip()
        if intent:
            meta = dict(out.get("meta") or {}) if isinstance(out.get("meta"), dict) else {}
            meta["配乐"] = intent
            out["meta"] = meta
            mix = dict(out.get("mix") or {}) if isinstance(out.get("mix"), dict) else {}
            if not str(mix.get("bgm_intent") or "").strip():
                mix["bgm_intent"] = intent
                out["mix"] = mix
    out["creative_ssot"] = "series_pack"
    out["script_schema"] = "series_pack"
    return out


def hydrate_characters_from_pack(rows: list[dict[str, Any]], pack: Any) -> list[dict[str, Any]]:
    """characters.json 运行态 ← 外形/正脸等从 pack 注入。"""
    if not rows or pack is None:
        return rows
    by_id: dict[str, Any] = {}
    for member in pack.cast or []:
        by_id[member.id] = ("character", member)
    for loc in pack.locations or []:
        by_id[loc.id] = ("scene", loc)
    for prop in pack.props or []:
        by_id[prop.id] = ("prop", prop)

    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("pack_id") or row.get("id") or "").strip()
        hit = by_id.get(cid)
        if not hit:
            out.append(row)
            continue
        kind, obj = hit
        patched = dict(row)
        if kind == "character":
            patched["name"] = obj.name
            patched["look"] = obj.look_full
            patched["look_face"] = obj.look_face
            patched["trait"] = obj.trait or ""
            patched["catchphrase"] = obj.catchphrase or ""
            patched["gender"] = obj.gender if obj.gender in ("male", "female") else patched.get("gender") or ""
            patched["age_band"] = obj.age_band or ""
            patched["voice_hint"] = obj.voice or ""
            if obj.voice_id and not patched.get("voice"):
                patched["voice"] = obj.voice_id
        elif kind == "scene":
            patched["name"] = obj.name
            patched["look"] = obj.plate
            patched["colors"] = obj.light or patched.get("colors") or ""
        else:
            patched["name"] = obj.name
            patched["look"] = obj.look
            patched["trait"] = obj.role or patched.get("trait") or ""
        patched["_creative_ssot"] = "series_pack"
        out.append(patched)
    return out


def slim_project_shell(project: dict[str, Any], pack: Any | None = None) -> dict[str, Any]:
    """project.json 只保留壳字段；创意正文不进这里。"""
    out = {
        "slug": str(project.get("slug") or "").strip(),
        "title": str(project.get("title") or "").strip(),
        "aspect": str(project.get("aspect") or "9:16"),
        "created_at": project.get("created_at"),
        "updated_at": project.get("updated_at"),
        "manual_voice": bool(project.get("manual_voice")),
        "script_schema": "series_pack" if pack is not None or project.get("script_schema") == "series_pack" else str(
            project.get("script_schema") or ""
        ),
        "layout_version": LAYOUT_VERSION,
        "episodes": [],
    }
    if pack is not None:
        out["title"] = pack.meta.title or out["title"]
        # logline 只存在 pack.meta；project 保留短索引用空串避免双写
        out["logline"] = ""
        for ep in pack.episodes or []:
            out["episodes"].append(
                {
                    "n": int(ep.n),
                    "title": ep.title or pack.meta.title,
                    "seconds": int(ep.seconds or pack.meta.seconds_per_episode or 0) or None,
                }
            )
        out["series"] = {
            "episode_count": len(pack.episodes or []),
            "seconds_per_episode": int(pack.meta.seconds_per_episode or 60),
            "source": "series_pack",
        }
    else:
        out["logline"] = str(project.get("logline") or "").strip()
        for ep in project.get("episodes") or []:
            if not isinstance(ep, dict):
                continue
            out["episodes"].append(
                {
                    "n": int(ep.get("n") or 0),
                    "title": str(ep.get("title") or "").strip(),
                    "seconds": ep.get("seconds"),
                }
            )
        if isinstance(project.get("series"), dict):
            out["series"] = project["series"]
    # 成片索引可选保留（生产产物指针，不算创意冗余）
    if isinstance(project.get("videos"), list):
        out["videos"] = project["videos"]
    return out


def write_export_views(slug: str, pack: Any) -> dict[str, str]:
    """可选：把 pack 渲染成给人读的 markdown，写入 exports/（非真相源）。"""
    from tools.drama_series_pack_materialize import write_bible_outline_from_pack

    docs = write_bible_outline_from_pack(slug, pack, dest="exports")
    return {
        "bible": str(docs.get("bible_rel") or f"{exports_dir_rel(slug)}/bible.md"),
        "outline": str(docs.get("outline_rel") or f"{exports_dir_rel(slug)}/outline.md"),
    }


def dump_layout_manifest(slug: str) -> dict[str, Any]:
    """调试用：当前项目文件角色。"""
    pack = has_series_pack(slug)
    return {
        "layout_version": LAYOUT_VERSION,
        "slug": slug,
        "creative_ssot": "series_pack.json" if pack else "legacy (bible/ep/shots)",
        "files": {
            "project": project_rel(slug),
            "series_pack": series_pack_rel(slug) if pack else None,
            "assets_runtime": characters_rel(slug),
            "episode_production": "videos/epNN/shots.json (+ mix)",
            "exports": exports_dir_rel(slug),
            "deprecated_as_ssot": [
                "bible.md",
                "outline.md",
                "episodes/epNN.md",
                "step1_script/*.md",
            ],
        },
    }


def _is_usable_script(text: str | None) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False
    # exports/root stubs are not episode scripts
    if raw.startswith("# 已迁移"):
        return False
    return "### Shot" in raw or "### shot" in raw.lower()


def script_markdown_from_doc(doc: dict[str, Any]) -> str:
    """从 shots.json 生产态合成可读 Markdown（非真相源，供兼容旧渲染入口）。"""
    if not isinstance(doc, dict):
        return ""
    shots = [s for s in (doc.get("shots") or []) if isinstance(s, dict)]
    if not shots:
        return ""
    title = str(doc.get("title") or f"第{int(doc.get('episode') or 0)}集").strip()
    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    lines = [
        f"# {title}",
        f"- 时长: {meta.get('时长') or ''}",
        f"- 配乐: {meta.get('配乐') or ''}",
        "",
        "## 分镜",
        "",
    ]
    for s in shots:
        n = int(s.get("n") or 0)
        dur = s.get("duration")
        try:
            dur_s = f"{float(dur):g}s" if dur is not None else ""
        except (TypeError, ValueError):
            dur_s = str(dur or "")
        head = f"### Shot {n}" + (f" ({dur_s})" if dur_s else "")
        lines.append(head)
        still = str(s.get("still") or s.get("画面") or "").strip()
        if still:
            lines.append(f"- 画面: {still}")
        motion = str(s.get("motion") or "").strip()
        if motion:
            lines.append(f"- motion: {motion}")
        loc = str(s.get("地点") or "").strip()
        if loc:
            lines.append(f"- 地点: {loc}")
        roles = s.get("角色") or []
        if isinstance(roles, list) and roles:
            lines.append(f"- 角色: {'、'.join(str(x) for x in roles if x)}")
        sub = str(s.get("字幕") or "").strip()
        if sub:
            lines.append(f"- 字幕: {sub}")
        narr = str(s.get("旁白") or "").strip()
        if narr:
            lines.append(f"- 旁白: {narr}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def resolve_episode_script(
    slug: str,
    episode: int,
    *,
    existing: str | None = None,
    persist: bool = False,
) -> str | None:
    """解析分集剧本：ep.md → shots.json → series_pack（按此优先级）。

    ep.md 已废弃为真相源，但若仍有可用 ### Shot 内容则直接返回。
    """
    if _is_usable_script(existing):
        return str(existing).rstrip() + "\n"

    n = int(episode)
    # 1) on-disk ep.md
    try:
        from tools.drama_shots import script_rel

        path = resolve_safe(script_rel(slug, n))
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            if _is_usable_script(text):
                return text if text.endswith("\n") else text + "\n"
    except Exception:
        pass

    # 2) shots.json production doc
    try:
        from tools.drama_shots import load_doc

        doc = load_doc(slug, n)
        synthesized = script_markdown_from_doc(doc or {})
        if _is_usable_script(synthesized):
            if persist:
                _persist_episode_script(slug, n, synthesized)
            return synthesized
    except Exception:
        pass

    # 3) series_pack creative SSOT
    pack = load_pack_or_none(slug)
    if pack is None:
        return None
    try:
        from tools.drama_series_pack_materialize import materialize_series_pack_episode

        # Prefer non-destructive synthesize: build markdown without full rematerialize
        ep = next((e for e in (pack.episodes or []) if int(e.n) == n), None)
        if ep is None:
            return None
        cast_name = {c.id: c.name for c in (pack.cast or [])}
        loc_name = {x.id: x.name for x in (pack.locations or [])}
        prop_name = {p.id: p.name for p in (pack.props or [])}
        from tools.drama_series_pack_materialize import pack_shot_to_legacy

        shots = [
            pack_shot_to_legacy(
                s,
                cast_name_by_id=cast_name,
                loc_name_by_id=loc_name,
                prop_name_by_id=prop_name,
            )
            for s in (ep.shots or [])
        ]
        style = getattr(pack, "style", None)
        meta = {
            "时长": f"{getattr(ep, 'seconds', None) or getattr(pack.meta, 'seconds_per_episode', 60)}s",
            "配乐": " / ".join(
                x
                for x in (
                    getattr(style, "bgm_mood", "") if style else "",
                    getattr(style, "bgm_instruments", "") if style else "",
                )
                if x
            ),
        }
        doc = {
            "title": getattr(ep, "title", None) or getattr(pack.meta, "title", "") or f"第{n}集",
            "episode": n,
            "meta": meta,
            "shots": shots,
        }
        synthesized = script_markdown_from_doc(doc)
        if _is_usable_script(synthesized):
            if persist:
                # Ensure shots.json exists so produce can skip markdown sync
                try:
                    materialize_series_pack_episode(slug, pack, n)
                except Exception:
                    _persist_episode_script(slug, n, synthesized)
            return synthesized
    except Exception:
        return None
    return None


def _persist_episode_script(slug: str, episode: int, body: str) -> None:
    try:
        from tools.drama_shots import script_rel

        path = resolve_safe(script_rel(slug, int(episode)))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(body).rstrip() + "\n", encoding="utf-8")
    except Exception:
        pass


def ensure_episode_ready(slug: str, episode: int) -> dict[str, Any]:
    """保证分集有 shots.json（必要时从 series_pack 物化）；返回 load_doc 结果。"""
    from tools.drama_shots import load_doc

    n = int(episode)
    doc = load_doc(slug, n)
    if doc and doc.get("shots"):
        return doc

    pack = None
    pack_err: Exception | None = None
    try:
        from tools.drama_series_pack_gen import load_saved_series_pack

        pack = load_saved_series_pack(slug)
    except Exception as exc:
        pack_err = exc
        pack = None

    if pack is not None:
        ep = next((e for e in (pack.episodes or []) if int(e.n) == n), None)
        if ep is not None:
            from tools.drama_series_pack_materialize import materialize_series_pack_episode

            materialize_series_pack_episode(slug, pack, n)
            doc = load_doc(slug, n)
            if doc and doc.get("shots"):
                return doc
        raise FileNotFoundError(
            f"series_pack 有文件但缺少第 {n} 集 episodes；请重新生成或 save_episode"
        )

    if has_series_pack(slug) and pack_err is not None:
        raise FileNotFoundError(f"series_pack 校验失败，无法物化分集：{pack_err}") from pack_err
    raise FileNotFoundError("没有分集剧本，请先 save_episode 或生成 series_pack")
