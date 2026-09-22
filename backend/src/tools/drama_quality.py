"""导出合规检查：仅保留 BGM 授权（上架合规）。质量/QC 门闸已全部移除。"""

from __future__ import annotations

from typing import Any


def assert_studio_bgm(slug: str, episode: int, *, force: bool = False) -> dict[str, Any]:
    """导出不得把 lavfi 程序化占位音当真实 BGM 上架（合规，非质量门闸）。"""
    import os

    from tools.drama_audio import has_bgm, load_catalog, load_mix
    from tools.drama_profiles import resolve_quality_profile

    if force:
        return {"ok": True, "forced": True}
    if resolve_quality_profile(slug) == "draft":
        return {"ok": True, "draft": True}
    if os.getenv("DRAMA_ALLOW_PROCEDURAL_BGM", "").strip().lower() in ("1", "true", "yes"):
        return {"ok": True, "allowed_env": True}

    mix = load_mix(slug, episode)
    if not has_bgm(mix):
        intent = str(mix.get("bgm_intent") or "").strip()
        raise ValueError(
            "导出需要真实配乐：请在成片页上传免版税/已授权 BGM"
            + (f"（剧本配乐意图：{intent}）" if intent else "")
            + "。当前曲库占位音为 lavfi 合成，不可作为上架成片。"
        )
    bgm = mix.get("bgm") if isinstance(mix.get("bgm"), dict) else {}
    procedural = bool(bgm.get("procedural"))
    if not procedural:
        # 交叉核对曲库行 / 标记
        tid = str(bgm.get("id") or "").strip()
        tracks = load_catalog(slug).get("tracks") or []
        hit = next((t for t in tracks if t.get("id") == tid), None)
        if hit and hit.get("procedural"):
            procedural = True
        else:
            path = str(bgm.get("path") or "")
            if path:
                try:
                    from tools.workspace import resolve_safe

                    p = resolve_safe(path)
                    if p.with_suffix(p.suffix + ".procedural").is_file():
                        procedural = True
                except ValueError:
                    pass
    if procedural:
        raise ValueError(
            "禁止使用 lavfi 程序化占位 BGM 导出。"
            "请上传真实免版税音频，或设置 DRAMA_ALLOW_PROCEDURAL_BGM=1（仅调试）。"
        )
    return {"ok": True, "procedural": False}
