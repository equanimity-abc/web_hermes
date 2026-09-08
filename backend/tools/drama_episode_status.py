"""Short episode status card for Agent / workbench (Week4)."""

from __future__ import annotations

from typing import Any

from tools.workspace import resolve_safe


def status_rel(slug: str, episode: int) -> str:
    return f"dramas/{slug}/videos/ep{int(episode):02d}/episode_status.md"


def build_episode_status(slug: str, episode: int, doc: dict[str, Any] | None = None) -> str:
    from tools.drama_audio import has_bgm, load_mix
    from tools.drama_shots import load_doc

    n = int(episode)
    doc = doc or load_doc(slug, n) or {}
    shots = [s for s in (doc.get("shots") or []) if isinstance(s, dict)]
    dirty = [int(s.get("n") or 0) for s in shots if (s.get("dirty") or [])]
    failed = [
        int(s.get("n") or 0)
        for s in shots
        if isinstance(s.get("qc"), dict) and s.get("qc", {}).get("produce_ok") is False
    ]
    scene_ok = sum(1 for s in shots if (s.get("assets") or {}).get("scene"))
    voice_ok = sum(1 for s in shots if (s.get("assets") or {}).get("voice"))
    mix = load_mix(slug, n)
    intent = str(mix.get("bgm_intent") or (doc.get("meta") or {}).get("配乐") or "").strip()
    lines = [
        f"# EP{n:02d} 状态卡",
        "",
        f"- 镜头总数: {len(shots)}",
        f"- 已有画面: {scene_ok}/{len(shots)}",
        f"- 已有配音: {voice_ok}/{len(shots)}",
        f"- 脏镜: {', '.join(str(x) for x in dirty) or '无'}",
        f"- 产线失败镜: {', '.join(str(x) for x in failed) or '无'}",
        f"- QC: {(doc.get('qc') or {}).get('verdict') or '待修'}",
        f"- BGM: {'已挂' if has_bgm(mix) else '未挂'}"
        + (f"（意图：{intent}）" if intent else ""),
        "",
        "## 导演下一步",
    ]
    if not shots:
        lines.append("1. 先生成/保存结构化剧本（角色/场景/道具/配乐/分镜）")
    elif dirty or failed:
        lines.append("1. rerender_dirty 重渲失败/脏镜")
        lines.append("2. 通过后 export_timeline")
    elif not has_bgm(mix):
        lines.append("1. 上传真实免版税 BGM（专业档禁止 lavfi 占位曲）")
        lines.append("2. export_timeline 导出")
    else:
        lines.append("1. export_timeline 导出整集")
        lines.append("2. 若需改单镜：选镜 → 重渲对应层")
    return "\n".join(lines).rstrip() + "\n"


def write_episode_status(slug: str, episode: int, doc: dict[str, Any] | None = None) -> str:
    text = build_episode_status(slug, episode, doc=doc)
    rel = status_rel(slug, episode)
    path = resolve_safe(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return rel
