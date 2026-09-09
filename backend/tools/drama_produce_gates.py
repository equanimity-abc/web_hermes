"""Produce readiness gates + series continuity (P0/P1)."""

from __future__ import annotations

from typing import Any

from tools.workspace import resolve_safe


def identity_kpi(doc: dict[str, Any] | None) -> dict[str, Any]:
    """Per-episode identity pass rate + longest consecutive pass streak."""
    shots = [s for s in ((doc or {}).get("shots") or []) if isinstance(s, dict)]
    ordered = sorted(shots, key=lambda s: int(s.get("n") or 0))
    scored = 0
    passed = 0
    streak = 0
    best = 0
    fails: list[int] = []
    for shot in ordered:
        ident = shot.get("identity") if isinstance(shot.get("identity"), dict) else {}
        status = str(ident.get("status") or "")
        if status in ("", "skipped", "n/a", "na"):
            continue
        scored += 1
        ok = status == "ok" and bool(ident.get("pass"))
        if ok:
            passed += 1
            streak += 1
            best = max(best, streak)
        else:
            fails.append(int(shot.get("n") or 0))
            streak = 0
    rate = round(passed / scored, 4) if scored else None
    return {
        "scored": scored,
        "passed": passed,
        "failed": fails,
        "pass_rate": rate,
        "consecutive_pass": best,
        "ok": bool(scored and rate is not None and rate >= 0.8 and best >= min(5, scored)),
    }


def identity_kpi_min_scored() -> int:
    """Minimum scored shots before KPI becomes a hard gate (avoid cold start)."""
    return 3


def identity_kpi_blocker(doc: dict[str, Any] | None) -> str:
    """Human-readable blocker when episode identity KPI fails studio bar; else empty."""
    kpi = identity_kpi(doc)
    scored = int(kpi.get("scored") or 0)
    if scored < identity_kpi_min_scored():
        return ""
    if kpi.get("ok"):
        return ""
    rate = kpi.get("pass_rate")
    rate_s = f"{float(rate):.0%}" if rate is not None else "n/a"
    fails = kpi.get("failed") or []
    fail_s = ",".join(str(x) for x in fails[:8]) or "—"
    return (
        f"身份 KPI 未达标（通过率 {rate_s}，最长连过 {kpi.get('consecutive_pass') or 0}，"
        f"需≥80% 且连过≥{min(5, scored)}；失败镜 {fail_s}）。请重渲失败镜 scene 后再发布。"
    )


def dirty_identity_kpi_fails(doc: dict[str, Any] | None) -> list[int]:
    """Mark identity-failed shots dirty for scene/motion/clip requeue; return shot numbers."""
    kpi = identity_kpi(doc)
    fails = [int(x) for x in (kpi.get("failed") or []) if int(x) > 0]
    if not fails or not isinstance(doc, dict):
        return []
    by_n = {int(s.get("n") or 0): s for s in (doc.get("shots") or []) if isinstance(s, dict)}
    touched: list[int] = []
    for n in fails:
        shot = by_n.get(n)
        if not shot:
            continue
        dirty = list(shot.get("dirty") or [])
        for layer in ("scene", "motion", "clip", "lip"):
            if layer not in dirty and layer not in (shot.get("locked") or []):
                dirty.append(layer)
        shot["dirty"] = dirty
        touched.append(n)
    return touched


def produce_blockers(
    slug: str,
    episode: int,
    *,
    doc: dict[str, Any] | None = None,
    force: bool = False,
) -> list[str]:
    """Reasons to refuse HQ produce unless force=True."""
    if force:
        return []
    from tools.drama_audio import has_bgm, load_mix
    from tools.drama_shots import load_doc

    n = int(episode)
    blockers: list[str] = []
    doc = doc or load_doc(slug, n) or {}
    shots = [s for s in (doc.get("shots") or []) if isinstance(s, dict)]
    script = ""
    try:
        from tools.drama_studio import _read_text, load_project_file

        project = load_project_file(slug) or {}
        ep_meta = next(
            (e for e in (project.get("episodes") or []) if int(e.get("n") or 0) == n),
            {},
        )
        rel = str(ep_meta.get("path") or f"dramas/{slug}/episodes/ep{n:02d}.md")
        script = _read_text(rel) or ""
    except Exception:
        script = ""
    if not shots and not str(script or "").strip():
        blockers.append("无分镜/剧本：请先生成并保存结构化剧本")
    elif not shots and str(script or "").strip():
        blockers.append("尚未解析分镜：请先 parse_shots / 保存剧本")

    mix = load_mix(slug, n)
    intent = str(mix.get("bgm_intent") or "").strip()
    if not intent:
        meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
        intent = str(meta.get("配乐") or "").strip()
    if shots and not has_bgm(mix) and not intent:
        blockers.append("未挂 BGM 且无配乐意图：请在剧本写「配乐」或上传免版税曲")

    if n > 1:
        from tools.drama_characters import load_characters

        prev = n - 1
        prev_doc = load_doc(slug, prev)
        if not prev_doc or not (prev_doc.get("shots") or []):
            blockers.append(f"系列连续性：缺少 EP{prev:02d} 分镜，请先完成上一集")
        cards = [
            c
            for c in load_characters(slug)
            if str(c.get("category") or "character") == "character"
        ]
        if cards and not any(c.get("ref_locked") for c in cards):
            blockers.append("系列连续性：尚无锁定定妆，EP>1 前请先锁角色参考图")

    # Resume / re-export: when enough identity scores exist, KPI must pass.
    kpi_msg = identity_kpi_blocker(doc)
    if kpi_msg:
        blockers.append(kpi_msg)

    return blockers


def series_continuity_blockers(slug: str, episode: int) -> list[str]:
    """EP>1 advisory + hard notes for status card (includes soft video check)."""
    hard = produce_blockers(slug, episode, force=False)
    n = int(episode)
    if n <= 1:
        return []
    out = [b for b in hard if "系列连续性" in b]
    prev = n - 1
    prev_video = resolve_safe(f"dramas/{slug}/videos/ep{prev:02d}.mp4")
    if not prev_video.is_file():
        out.append(f"系列连续性：EP{prev:02d} 尚未导出成片（建议先完成上一集再产本集）")
    return out


def write_series_status(slug: str, episode: int, blockers: list[str] | None = None) -> str:
    rel = f"dramas/{slug}/series_status.md"
    n = int(episode)
    lines = [f"# 系列状态 · 焦点 EP{n:02d}", ""]
    if blockers:
        lines.append("## 阻断")
        for b in blockers:
            lines.append(f"- {b}")
        lines.append("")
    else:
        lines.append("- 连续性检查通过（或 EP01 无前置）")
        lines.append("")
    path = resolve_safe(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return rel


def assert_produce_ready(
    slug: str,
    episode: int,
    *,
    force: bool = False,
    doc: dict[str, Any] | None = None,
) -> None:
    blockers = produce_blockers(slug, episode, force=force, doc=doc)
    try:
        write_series_status(slug, int(episode), blockers)
    except Exception:
        pass
    if blockers:
        raise ValueError(
            "产片被状态卡拦截（传入 force=true 可覆盖）：" + "；".join(blockers[:6])
        )
