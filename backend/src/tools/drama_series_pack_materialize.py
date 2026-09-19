"""SeriesPack → 下游资产 / shots：只拷贝字段，禁止 LLM/规则扩写外形与场景。

正式产物（高内聚）::

- dramas/{slug}/series_pack.json     创意唯一真相源
- dramas/{slug}/characters.json      资产运行态（定妆路径/锁）
- dramas/{slug}/videos/epNN/shots.json  分集生产态（候选/QC/mix）
- dramas/{slug}/project.json         项目壳

可选导出（非真相源）::

- dramas/{slug}/exports/bible.md · outline.md
"""

from __future__ import annotations

import json
from typing import Any

from tools.drama_series_pack import SeriesPack, loads_series_pack
from tools.drama_series_pack_gen import load_saved_series_pack, series_pack_rel
from tools.drama_series_pack_validate import assert_series_pack_valid
from tools.workspace import resolve_safe


def format_dialogue_subtitle(lines: list[Any], cast_name_by_id: dict[str, str]) -> str:
    """dialogue[] → 旧「字幕」多行文本（仅拼接，不改写台词）。"""
    out: list[str] = []
    for line in lines or []:
        if hasattr(line, "speaker"):
            speaker = str(line.speaker or "").strip()
            text = str(line.text or "").strip()
            emotion = str(getattr(line, "emotion", "") or "").strip()
        elif isinstance(line, dict):
            speaker = str(line.get("speaker") or "").strip()
            text = str(line.get("text") or "").strip()
            emotion = str(line.get("emotion") or "").strip()
        else:
            continue
        if not text:
            continue
        name = cast_name_by_id.get(speaker, speaker)
        if emotion:
            out.append(f"{name}（{emotion}）：{text}")
        else:
            out.append(f"{name}：{text}")
    return "\n".join(out)


def pack_shot_to_legacy(
    shot: Any,
    *,
    cast_name_by_id: dict[str, str],
    loc_name_by_id: dict[str, str],
    prop_name_by_id: dict[str, str],
) -> dict[str, Any]:
    """ShotSpec → shots.json 单镜：画面=still 原样拷贝；motion/shot_size 另存。"""
    n = int(shot.n)
    t_in = float(shot.t_in)
    t_out = float(shot.t_out)
    duration = max(0.1, t_out - t_in)
    still = str(shot.still or "").strip()
    motion = str(shot.motion or "").strip()
    loc_id = str(shot.location or "").strip()
    loc_name = loc_name_by_id.get(loc_id, loc_id)
    prop_names = [prop_name_by_id.get(pid, pid) for pid in (shot.props or [])]
    # 角色栏用 pack id（与 characters.json id 对齐，materialize 时按 pack id 建卡）
    cast_ids = [str(cid) for cid in (shot.cast or [])]
    speaker = ""
    if shot.dialogue:
        speaker = str(shot.dialogue[0].speaker or "")
    return {
        "n": n,
        "start": t_in,
        "end": t_out,
        "duration": duration,
        "timing": f"{t_in:g}-{t_out:g}s",
        "画面": still,  # 兼容旧流水线：Seedream 读「画面」= still
        "still": still,
        "motion": motion,
        "shot_size": str(shot.shot_size or ""),
        "地点": loc_name,
        "location_id": loc_id,
        "道具": prop_names,
        "prop_ids": [str(pid) for pid in (shot.props or [])],
        "角色": cast_ids,
        "字幕": format_dialogue_subtitle(list(shot.dialogue or []), cast_name_by_id),
        "旁白": str(shot.vo or "").strip(),
        "kind": str(shot.kind or ""),
        "camera": str(shot.camera or ""),  # 中文运镜枚举，禁止映射成 punch_in
        "size": str(shot.shot_size or ""),
        "speaker": speaker,
        "audio_mode": str(shot.audio_mode or "") if shot.audio_mode else "",
        "sfx": str(shot.sfx or "").strip(),
        "source": "series_pack",
    }


def materialize_series_pack_assets(slug: str, pack: SeriesPack) -> dict[str, Any]:
    """只拷贝 cast/locations/props → characters.json，不扩写 look/plate。"""
    from tools.drama_cast_graph import upsert_relationship_edges
    from tools.drama_characters import load_characters, upsert_character

    created = {"characters": [], "scenes": [], "props": [], "relationships": []}
    id_map: dict[str, str] = {}

    for member in pack.cast:
        look = str(member.look_full or "").strip()
        face = str(member.look_face or "").strip()
        payload: dict[str, Any] = {
            "id": member.id,
            "name": member.name,
            "category": "character",
            "look": look,  # 原样
            "look_face": face,
            "gender": member.gender if member.gender in ("male", "female") else "",
            "age_band": member.age_band or "",
            "catchphrase": member.catchphrase or "",
            "trait": member.trait or "",
            "pack_id": member.id,
            "voice_hint": member.voice or "",
        }
        if member.voice_id:
            payload["voice"] = member.voice_id
        rec = upsert_character(slug, payload)
        cid = str(rec.get("id") or member.id)
        id_map[member.id] = cid
        created["characters"].append(cid)

    for loc in pack.locations:
        plate = str(loc.plate or "").strip()
        # look = plate 原样；光影/锚点仅附加已存在字段，不改写 plate 正文
        extras = []
        if loc.light:
            extras.append(f"光影：{loc.light}")
        if loc.anchors:
            extras.append("标志物：" + "、".join(loc.anchors))
        if loc.layout:
            extras.append(f"布局：{loc.layout}")
        look = plate if not extras else plate + "。" + "；".join(extras)
        rec = upsert_character(
            slug,
            {
                "id": loc.id,
                "name": loc.name,
                "category": "scene",
                "look": look,
                "pack_id": loc.id,
                "aliases": [loc.name],
            },
        )
        created["scenes"].append(str(rec.get("id") or loc.id))
        id_map[loc.id] = str(rec.get("id") or loc.id)

    for prop in pack.props:
        rec = upsert_character(
            slug,
            {
                "id": prop.id,
                "name": prop.name,
                "category": "prop",
                "look": str(prop.look or "").strip(),
                "pack_id": prop.id,
                "aliases": [prop.name],
                "role": prop.role or "",
            },
        )
        created["props"].append(str(rec.get("id") or prop.id))
        id_map[prop.id] = str(rec.get("id") or prop.id)

    # relationships: "A → B：rel" may use names; store as edges by name
    edges: list[dict[str, str]] = []
    for raw in pack.relationships or []:
        text = str(raw or "").strip()
        if "→" not in text:
            continue
        left, right = text.split("→", 1)
        frm = left.strip()
        if "：" in right or ":" in right:
            sep = "：" if "：" in right else ":"
            to, rel = right.split(sep, 1)
        else:
            to, rel = right, ""
        edges.append({"from": frm.strip(), "to": to.strip(), "rel": rel.strip()})
    if edges:
        upsert_relationship_edges(slug, edges)
        created["relationships"] = edges

    # Ensure cards exist
    _ = load_characters(slug)
    return {"created": created, "id_map": id_map}


def materialize_series_pack_episode(slug: str, pack: SeriesPack, episode: int) -> dict[str, Any]:
    """拷贝一集 shots → shots.json（画面=still，附带 motion）。"""
    from tools.drama_shots import normalize_doc, save_doc
    from tools.drama_step_contract import publish_script_step

    ep = next((e for e in pack.episodes if int(e.n) == int(episode)), None)
    if ep is None:
        raise ValueError(f"SeriesPack 无第 {episode} 集")

    cast_name = {c.id: c.name for c in pack.cast}
    loc_name = {x.id: x.name for x in pack.locations}
    prop_name = {p.id: p.name for p in pack.props}

    shots = [
        pack_shot_to_legacy(
            s,
            cast_name_by_id=cast_name,
            loc_name_by_id=loc_name,
            prop_name_by_id=prop_name,
        )
        for s in ep.shots
    ]
    style = pack.style
    meta = {
        "时长": f"{ep.seconds or pack.meta.seconds_per_episode}s",
        "钩子": "",
        "悬念": "",
        "配乐": " / ".join(x for x in (style.bgm_mood, style.bgm_instruments) if x),
        "beat": ep.beat or "",
        "schema": "series_pack",
        "visual": style.visual,
        "audio_default": style.audio_default,
    }
    doc = normalize_doc(
        {
            "slug": slug,
            "episode": int(episode),
            "title": ep.title or pack.meta.title,
            "meta": meta,
            "shots": shots,
            "source": "series_pack",
        },
        slug,
        int(episode),
    )
    save_doc(doc)

    # 同步一份极简 Markdown（人读索引）；step1 以 shots 为准
    md_lines = [
        f"# {doc.get('title') or pack.meta.title}",
        f"- 时长: {meta['时长']}",
        f"- 配乐: {meta['配乐']}",
        "",
        "## 分镜（SeriesPack 拷贝，禁止扩写）",
        "",
    ]
    for s in shots:
        md_lines.append(f"### Shot {s['n']} ({s['duration']}s)")
        md_lines.append(f"- still: {s.get('still') or s.get('画面')}")
        md_lines.append(f"- motion: {s.get('motion') or ''}")
        md_lines.append(f"- 地点: {s.get('地点')}")
        md_lines.append(f"- 角色: {'、'.join(s.get('角色') or [])}")
        if s.get("字幕"):
            md_lines.append(f"- 字幕: {s['字幕']}")
        md_lines.append("")
    script_body = "\n".join(md_lines).rstrip() + "\n"

    from tools.drama_shots import json_rel, script_rel

    script_path = resolve_safe(script_rel(slug, int(episode)))
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(script_body, encoding="utf-8")
    try:
        publish_script_step(
            slug,
            int(episode),
            script_rel=script_rel(slug, int(episode)),
            shots_rel=json_rel(slug, int(episode)),
            doc=doc,
            from_ui=True,
        )
    except Exception:
        # step1 契约失败不阻断 videos/epNN/shots.json（save_doc 已写）
        pass

    return {
        "ok": True,
        "slug": slug,
        "episode": int(episode),
        "count": len(shots),
        "title": doc.get("title"),
        "source": "series_pack",
    }


def sync_asset_to_series_pack(slug: str, rec: dict[str, Any]) -> bool:
    """把角色/场景/道具卡字段写回 series_pack.json（有则更新，无包则跳过）。"""
    from tools.drama_characters import normalize_category
    from tools.drama_series_pack import dump_series_pack, loads_series_pack
    from tools.drama_series_pack_gen import load_saved_series_pack, save_series_pack

    pack = load_saved_series_pack(slug)
    if pack is None:
        return False
    data = json.loads(dump_series_pack(pack))
    pack_id = str(rec.get("pack_id") or rec.get("id") or "").strip()
    name = str(rec.get("name") or "").strip()
    cat = normalize_category(rec.get("category"))
    changed = False

    if cat == "character":
        for row in data.get("cast") or []:
            if not isinstance(row, dict):
                continue
            if str(row.get("id") or "") not in {pack_id, str(rec.get("id") or "")} and str(
                row.get("name") or ""
            ) != name:
                continue
            if name:
                row["name"] = name
            look = str(rec.get("look") or "").strip()
            if look:
                row["look_full"] = look
            face = str(rec.get("look_face") or "").strip()
            if face:
                row["look_face"] = face
            gender = str(rec.get("gender") or "").strip()
            if gender in ("male", "female", "other"):
                row["gender"] = gender
            age = str(rec.get("age_band") or "").strip()
            if age:
                row["age_band"] = age
            voice_hint = str(rec.get("voice_hint") or "").strip()
            if voice_hint:
                row["voice"] = voice_hint
            voice_id = str(rec.get("voice") or "").strip()
            if voice_id:
                row["voice_id"] = voice_id
            trait = str(rec.get("trait") or "").strip()
            if trait:
                row["trait"] = trait
            catchphrase = str(rec.get("catchphrase") or "").strip()
            row["catchphrase"] = catchphrase
            changed = True
            break
    elif cat == "scene":
        for row in data.get("locations") or []:
            if not isinstance(row, dict):
                continue
            if str(row.get("id") or "") not in {pack_id, str(rec.get("id") or "")} and str(
                row.get("name") or ""
            ) != name:
                continue
            if name:
                row["name"] = name
            look = str(rec.get("look") or "").strip()
            if look:
                # look 可能带「光影/标志物」后缀；若含空镜/静帧则整段回写 plate
                row["plate"] = look
            changed = True
            break
    elif cat == "prop":
        for row in data.get("props") or []:
            if not isinstance(row, dict):
                continue
            if str(row.get("id") or "") not in {pack_id, str(rec.get("id") or "")} and str(
                row.get("name") or ""
            ) != name:
                continue
            if name:
                row["name"] = name
            look = str(rec.get("look") or "").strip()
            if look:
                row["look"] = look
            role = str(rec.get("role") or rec.get("trait") or "").strip()
            if role:
                row["role"] = role
            changed = True
            break

    if not changed:
        return False
    try:
        updated = loads_series_pack(data)
    except Exception:
        # plate 等校验失败时仍尽量落盘原始 JSON（避免挡住定妆重生成）
        path = resolve_safe(series_pack_rel(slug))
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return True
    save_series_pack(slug, updated)
    return True


def write_bible_outline_from_pack(
    slug: str,
    pack: SeriesPack,
    *,
    dest: str = "exports",
) -> dict[str, str]:
    """从 SeriesPack 生成可读 markdown。

    dest=\"exports\"（默认）：写入 ``exports/``，根目录 bible/outline 仅留迁移提示。
    dest=\"root\"：兼容旧行为，直接写根目录（不推荐）。
    """
    cast_lines = ["# 人设圣经", "", "## 风格", pack.style.visual, ""]
    cast_lines.append("## 角色")
    for c in pack.cast:
        cast_lines.extend(
            [
                f"### {c.name}",
                f"- id: {c.id}",
                f"- 外形: {c.look_full}",
                f"- 正脸: {c.look_face}",
                f"- 音色: {c.voice}",
                f"- 性格: {c.trait}" if c.trait else "",
                "",
            ]
        )
    cast_lines.append("## 角色关系")
    for rel in pack.relationships or []:
        cast_lines.append(f"- {rel}")
    cast_lines.extend(["", "## 场景"])
    for loc in pack.locations:
        cast_lines.extend(
            [
                f"### {loc.name}",
                f"- id: {loc.id}",
                f"- 底板: {loc.plate}",
                f"- 光影: {loc.light}",
                f"- 标志物: {'、'.join(loc.anchors)}",
                "",
            ]
        )
    if pack.props:
        cast_lines.append("## 道具")
        for prop in pack.props:
            cast_lines.extend(
                [
                    f"### {prop.name}",
                    f"- id: {prop.id}",
                    f"- 外形: {prop.look}",
                    f"- 作用: {prop.role}" if prop.role else "",
                    "",
                ]
            )
    if pack.style.bgm_mood or pack.style.bgm_instruments:
        cast_lines.extend(
            [
                "## 配乐基调",
                f"- 情绪风格: {pack.style.bgm_mood}",
                f"- 乐器与节奏: {pack.style.bgm_instruments}",
                "",
            ]
        )
    bible = "\n".join(line for line in cast_lines if line is not None).rstrip() + "\n"

    outline_lines = [
        "# 故事大纲",
        f"- 剧名: {pack.meta.title}",
        f"- 一句话卖点: {pack.meta.logline}",
        f"- 时长: 每集约 {pack.meta.seconds_per_episode}s",
        "",
    ]
    for ep in pack.episodes:
        outline_lines.append(
            f"- EP{ep.n:02d} {ep.title or ''}: {ep.beat or f'{len(ep.shots)} 镜'}"
        )
    outline = "\n".join(outline_lines).rstrip() + "\n"

    root = resolve_safe(f"dramas/{slug}")
    root.mkdir(parents=True, exist_ok=True)
    stub = (
        "# 已迁移\n\n"
        "本文件不再是剧本真相源。请编辑 `series_pack.json`；"
        "可读导出见 `exports/`。\n"
    )
    if dest == "root":
        (root / "bible.md").write_text(bible, encoding="utf-8")
        (root / "outline.md").write_text(outline, encoding="utf-8")
        bible_rel = f"dramas/{slug}/bible.md"
        outline_rel = f"dramas/{slug}/outline.md"
    else:
        export_dir = root / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        (export_dir / "bible.md").write_text(bible, encoding="utf-8")
        (export_dir / "outline.md").write_text(outline, encoding="utf-8")
        (root / "bible.md").write_text(stub, encoding="utf-8")
        (root / "outline.md").write_text(stub, encoding="utf-8")
        bible_rel = f"dramas/{slug}/exports/bible.md"
        outline_rel = f"dramas/{slug}/exports/outline.md"

    return {"bible": bible, "outline": outline, "bible_rel": bible_rel, "outline_rel": outline_rel}


def sync_project_episodes_from_pack(slug: str, pack: SeriesPack) -> dict[str, Any]:
    """更新 project.json 壳字段（集索引）；创意正文不进 project。"""
    from tools.drama_layout import slim_project_shell
    from tools.drama_studio import load_project, save_project

    try:
        project = load_project(slug)
    except Exception:
        project = {"slug": slug, "title": pack.meta.title, "episodes": []}
        root = resolve_safe(f"dramas/{slug}")
        root.mkdir(parents=True, exist_ok=True)
    videos = project.get("videos")
    manual = project.get("manual_voice")
    created = project.get("created_at")
    project = slim_project_shell(project, pack)
    if created:
        project["created_at"] = created
    if videos is not None:
        project["videos"] = videos
    if manual is not None:
        project["manual_voice"] = bool(manual)
    save_project(slug, project)
    return project


def materialize_series_pack(
    slug: str,
    pack: SeriesPack | dict[str, Any] | str | None = None,
    *,
    episodes: list[int] | None = None,
    write_bible: bool = False,
) -> dict[str, Any]:
    """端到端：校验 → 资产运行态 → 分集生产态。默认不把 bible/outline 当真相源。"""
    if pack is None:
        loaded = load_saved_series_pack(slug)
        if loaded is None:
            raise FileNotFoundError(f"缺少 {series_pack_rel(slug)}")
        pack_obj = loaded
    elif isinstance(pack, SeriesPack):
        pack_obj = pack
    else:
        pack_obj = loads_series_pack(pack)

    pack_obj = assert_series_pack_valid(pack_obj)
    assets = materialize_series_pack_assets(slug, pack_obj)

    ep_nums = episodes
    if ep_nums is None:
        ep_nums = [int(e.n) for e in pack_obj.episodes]
    ep_results = []
    for n in ep_nums:
        ep_results.append(materialize_series_pack_episode(slug, pack_obj, n))

    from tools.drama_series_pack_gen import save_series_pack

    save_series_pack(slug, pack_obj)
    docs = write_bible_outline_from_pack(slug, pack_obj, dest="exports") if write_bible else {}
    project = sync_project_episodes_from_pack(slug, pack_obj)

    return {
        "ok": True,
        "slug": slug,
        "pack": series_pack_rel(slug),
        "assets": assets,
        "episodes": ep_results,
        "bible_chars": len(docs.get("bible") or ""),
        "outline_chars": len(docs.get("outline") or ""),
        "exports": {k: docs[k] for k in ("bible_rel", "outline_rel") if k in docs},
        "project_episodes": project.get("episodes") or [],
        "layout": "series_pack_ssot",
    }


def copy_still_prompt(shot: dict[str, Any], *, style_visual: str = "") -> str:
    """Seedream：只拼 still（或兼容 画面），禁止把 motion 混进静帧。"""
    still = str(shot.get("still") or shot.get("画面") or "").strip()
    bits = [b for b in (still, style_visual, "竖屏9:16视频静帧") if b]
    return "。".join(bits) + ("。" if bits else "")


def copy_motion_prompt(shot: dict[str, Any], *, style_visual: str = "") -> str:
    """Seedance：只拼 motion + 景别 + 运镜，禁止用静帧散文冒充运动。"""
    motion = str(shot.get("motion") or "").strip()
    if not motion:
        # 兼容旧镜：退回 画面，但调用方应尽快迁移
        motion = str(shot.get("画面") or "").strip()
    size = str(shot.get("shot_size") or shot.get("size") or "").strip()
    camera = str(shot.get("camera") or "").strip()
    bits = [b for b in (motion, f"景别{size}" if size else "", f"运镜{camera}" if camera else "", style_visual) if b]
    return "。".join(bits) + ("。" if bits else "")
