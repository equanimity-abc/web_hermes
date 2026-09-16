"""Format HQ shot failures for chat/UI + Seedance manual curl verification."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


# 用户可见产线步骤（火山单轨）：剧本 → 角色 → 画面 → 视频 → 成片
# 配音为视频页可选能力（默认关，Seedance 自带声）。
# value = (步骤名, 默认细分)
_STAGE_LABELS: dict[str, tuple[str, str]] = {
    "script": ("剧本", "分集剧本"),
    "cast": ("角色", "定妆参考"),
    "scene": ("画面", "场景出图"),
    "identity": ("画面", "角色一致性"),
    "voice": ("视频", "手动配音"),
    "i2v": ("视频", "图生视频"),
    "flicker": ("视频", "画面检测"),
    "lip": ("视频", "口型"),
    "export": ("成片", "拼接导出"),
    "aborted": ("成片", "任务中止"),
    "unknown": ("成片", "其它"),
}


def classify_failure_side(err: str) -> str:
    """Return input | output | peer | other."""
    s = str(err or "")
    low = s.lower()
    if "加速收尾" in s or "peerabort" in low or "cancelled:" in low:
        return "peer"
    if "outputvideosensitive" in low or "outputimagesensitive" in low:
        return "output"
    if (
        "inputimagesensitive" in low
        or "inputvideosensitive" in low
        or "privacyinformation" in low
        or ("real person" in low and "output" not in low)
    ):
        return "input"
    if "sensitive" in low or "敏感" in s:
        return "sensitive"
    return "other"


def side_label_zh(side: str) -> str:
    return {
        "input": "输入侧内容安全",
        "output": "输出侧内容安全",
        "peer": "连带取消",
        "sensitive": "内容安全拦截",
        "other": "其它",
    }.get(side, "其它")


def classify_failure_locus(err: str) -> dict[str, str]:
    """Map error → step / detail / cleaned reason for UI."""
    from tools.drama_resume import classify_failure

    err = str(err or "").strip()
    side = classify_failure_side(err)
    stage = str(classify_failure(err).get("stage") or "unknown")
    step, detail = _STAGE_LABELS.get(stage, _STAGE_LABELS["unknown"])

    if side == "output":
        step, detail = "视频", "输出侧内容安全"
    elif side == "input":
        step, detail = "画面", "输入侧内容安全"
    elif side == "sensitive" and stage not in ("flicker", "identity", "lip", "voice"):
        detail = "内容安全拦截"
    elif side == "peer":
        step, detail = "成片", "任务中止"

    reason = _clean_reason(err, stage=stage, side=side)
    return {
        "stage": stage,
        "side": side,
        "step": step,
        "detail": detail,
        "reason": reason,
    }


def _clean_reason(err: str, *, stage: str = "", side: str = "") -> str:
    """Strip redundant wrappers; keep the actionable core."""
    s = str(err or "").strip()
    s = re.sub(r"^cancelled:\s*", "", s, flags=re.I)

    # 画面抖动：用白话说明（相邻帧相似度，越低越抖）
    m = re.search(
        r"(?:闪烁\s*SSIM|相邻帧相似度)\s*([\d.]+)\s*<\s*([\d.]+)",
        s,
        re.I,
    )
    if m or (stage == "flicker" and re.search(r"ssim\s*[\d.]+", s, re.I)):
        if not m:
            m = re.search(r"(?:闪烁\s*)?SSIM\s*([\d.]+)\s*<\s*([\d.]+)", s, re.I)
        if m:
            return (
                f"相邻帧相似度 {m.group(1)} < {m.group(2)}，"
                f"生成视频画面抖动过大（请重做本镜视频，不重配音）"
            )

    m = re.search(r"第\s*\d+\s*镜.+?未通过[（(](.+)[）)]\s*[，,]?\s*禁止自动重试\s*$", s)
    if m:
        s = m.group(1).strip()
    else:
        m = re.search(r"第\s*\d+\s*镜(.+?)未通过[（(](.+)[）)]\s*$", s)
        if m:
            s = m.group(2).strip()
    s = re.sub(r"[，,]\s*禁止自动重试\s*$", "", s)
    s = re.sub(r"^Shot\s*\d+\s*[：:]\s*", "", s, flags=re.I)
    s = re.sub(r"^需要真\s*I2V[；;]\s*", "", s, flags=re.I)
    s = s.replace("请重做运动（不重配音）", "请重做本镜视频，不重配音")
    s = s.replace("请重做运动", "请重做本镜视频")
    return s.strip() or str(err or "").strip()[:500]


def _workspace_play_url(rel: str) -> str:
    path = str(rel or "").strip().replace("\\", "/")
    if not path:
        return ""
    from urllib.parse import quote

    return f"/api/workspace/file?path={quote(path, safe='/')}"


def _rel_ok(rel: str) -> bool:
    path = str(rel or "").strip()
    if not path:
        return False
    try:
        from tools.workspace import resolve_safe

        p = resolve_safe(path)
        return p.is_file() and p.stat().st_size > 50
    except Exception:
        return False


def collect_shot_failure_media(
    slug: str,
    episode: int,
    shot_n: int,
    *,
    stage: str = "",
    shot: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Pick preview image/video for the failed step so UI can show what failed."""
    from tools.drama_shots import find_shot, load_doc, shot_assets

    slug = str(slug or "").strip()
    ep = int(episode or 0)
    sn = int(shot_n or 0)
    if not slug or ep < 1 or sn < 1:
        return []

    doc = load_doc(slug, ep) if slug else None
    row = shot if isinstance(shot, dict) else (find_shot(doc, sn) if doc else None)
    assets = {}
    if isinstance(row, dict) and isinstance(row.get("assets"), dict):
        assets = dict(row.get("assets") or {})
    sa = shot_assets(slug, ep, sn) if slug else {}
    for k in ("scene", "motion", "lip", "voice", "clip", "overlay"):
        if not assets.get(k) and sa.get(k):
            assets[k] = sa.get(k)

    # 按失败阶段优先展示「出错的那一层」；再附参考层
    prefer: list[tuple[str, str, str]] = []
    st = str(stage or "")
    if st in ("flicker", "i2v", "lip"):
        prefer = [
            ("motion", "失败视频（运动）", "video"),
            ("lip", "失败视频（口型）", "video"),
            ("clip", "失败成片片段", "video"),
            ("scene", "参考画面", "image"),
        ]
    elif st in ("scene", "identity"):
        prefer = [
            ("scene", "失败画面", "image"),
            ("motion", "参考视频", "video"),
        ]
    elif st == "voice":
        prefer = [
            ("voice", "失败配音", "audio"),
            ("scene", "参考画面", "image"),
        ]
    elif st == "export":
        prefer = [
            ("clip", "失败成片片段", "video"),
            ("motion", "参考运动视频", "video"),
            ("scene", "参考画面", "image"),
        ]
    else:
        prefer = [
            ("motion", "失败视频", "video"),
            ("scene", "失败画面", "image"),
            ("clip", "失败成片片段", "video"),
            ("lip", "失败口型视频", "video"),
        ]

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key, title, typ in prefer:
        rel = str(assets.get(key) or "").strip()
        if not rel or rel in seen or not _rel_ok(rel):
            continue
        seen.add(rel)
        url = _workspace_play_url(rel)
        if not url:
            continue
        out.append(
            {
                "type": typ,
                "url": url,
                "path": rel.replace("\\", "/"),
                "title": f"Shot {sn} · {title}",
                "slug": slug,
                "episode": ep,
                "shot": sn,
                "layer": key,
            }
        )
        if len(out) >= 2:
            break
    return out


def _request_id(err: str) -> str:
    m = re.search(r"Request id:\s*([A-Za-z0-9]+)", str(err or ""), re.I)
    if m:
        return m.group(1)
    m = re.search(r"\b(021\d{10,}[A-Za-z0-9]*)\b", str(err or ""))
    return m.group(1) if m else ""


def _ark_base_for_curl() -> str:
    try:
        from config import config

        return str(getattr(config, "ARK_BASE_URL", "") or "https://ark.cn-beijing.volces.com/api/plan/v3").rstrip(
            "/"
        )
    except Exception:
        return "https://ark.cn-beijing.volces.com/api/plan/v3"


def _ark_video_model() -> str:
    try:
        from config import config
        from tools.providers.ark_providers import _resolve_seedance_model

        return _resolve_seedance_model(getattr(config, "ARK_VIDEO_MODEL", ""))
    except Exception:
        return "doubao-seedance-2-0-260128"


def write_seedance_verify_payload(
    slug: str,
    episode: int,
    shot_n: int,
    *,
    shot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write a JSON body for Seedance I2V curl; returns paths + curl lines (no API key)."""
    from tools.drama_i2v import _motion_prompt, motion_seconds
    from tools.drama_shots import find_shot, load_doc, shot_assets
    from tools.providers.ark_providers import _image_path_to_data_uri, _seedance_duration
    from tools.workspace import resolve_safe, workspace_root

    slug = str(slug or "").strip()
    ep = int(episode)
    sn = int(shot_n)
    doc = load_doc(slug, ep) if slug else None
    row = shot if isinstance(shot, dict) else (find_shot(doc, sn) if doc else None)
    if not isinstance(row, dict):
        row = {"n": sn}
    row = dict(row)
    row["_slug"] = slug
    row["_episode"] = ep

    assets = row.get("assets") if isinstance(row.get("assets"), dict) else {}
    sa = shot_assets(slug, ep, sn) if slug else {}
    scene_rel = str(assets.get("scene") or sa.get("scene") or "").strip()
    scene_path: Path | None = None
    if scene_rel:
        try:
            scene_path = resolve_safe(scene_rel)
        except Exception:
            scene_path = None
    if scene_path is None or not scene_path.is_file():
        return {
            "ok": False,
            "error": f"Shot {sn} 缺少 scene 文件，无法生成 curl payload",
            "shot": sn,
        }

    model = _ark_video_model()
    prompt = _motion_prompt(row)
    duration = _seedance_duration(motion_seconds(row))
    image_url = _image_path_to_data_uri(scene_path, max_side=1536)
    if not image_url:
        return {"ok": False, "error": f"Shot {sn} scene 编码失败", "shot": sn}

    content: list[dict] = [
        {"type": "text", "text": prompt},
        {
            "type": "image_url",
            "image_url": {"url": image_url},
            "role": "first_frame",
        },
    ]
    # 与生产线一致：对白镜挂 TTS reference_audio（curl 调试用）
    try:
        from tools.providers.ark_providers import (
            _audio_path_to_data_uri,
            _seedance_want_ref_audio,
            _shot_voice_path,
            _probe_voice_seconds,
        )

        if _seedance_want_ref_audio(row):
            vp = _shot_voice_path(row)
            audio_url = _audio_path_to_data_uri(vp) if vp is not None else None
            if audio_url and vp is not None:
                vs = _probe_voice_seconds(vp)
                if vs <= 0 or 1.8 <= vs <= 15.5:
                    if vs > 0:
                        duration = _seedance_duration(max(duration, vs))
                    content[0]["text"] = (
                        f"{prompt}。角色按参考音频说话，口型与语音节奏精准同步，自然张合，"
                        "不要额外旁白字幕。"
                    )
                    content.append(
                        {
                            "type": "audio_url",
                            "audio_url": {"url": audio_url},
                            "role": "reference_audio",
                        }
                    )
    except Exception:
        pass

    body = {
        "model": model,
        "content": content,
        "duration": duration,
        "ratio": "adaptive",
        # 挂了 reference_audio 才关；否则默认模型自带声
        "generate_audio": not any(
            isinstance(c, dict) and c.get("role") == "reference_audio" for c in content
        ),
    }

    out_dir = workspace_root() / "dramas" / slug / "videos" / f"ep{ep:02d}" / ".verify"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload_path = out_dir / f"shot{sn:02d}_seedance_payload.json"
    meta_path = out_dir / f"shot{sn:02d}_seedance_meta.json"
    payload_path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    meta = {
        "slug": slug,
        "episode": ep,
        "shot": sn,
        "scene_rel": scene_rel,
        "model": model,
        "duration": duration,
        "prompt": prompt,
        "payload": str(payload_path.relative_to(workspace_root())).replace("\\", "/"),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    base = _ark_base_for_curl()
    payload_posix = str(payload_path).replace("\\", "/")
    curl_submit = (
        f'curl -sS "{base}/contents/generations/tasks" '
        f'-H "Authorization: Bearer $ARK_API_KEY" '
        f'-H "Content-Type: application/json" '
        f'-d @"{payload_posix}"'
    )
    curl_poll = (
        f'curl -sS "{base}/contents/generations/tasks/TASK_ID" '
        f'-H "Authorization: Bearer $ARK_API_KEY"'
    )
    # Windows PowerShell friendly twin
    curl_submit_ps = (
        f'curl.exe -sS "{base}/contents/generations/tasks" '
        f'-H "Authorization: Bearer $env:ARK_API_KEY" '
        f'-H "Content-Type: application/json" '
        f'-d "@{payload_path}"'
    )
    curl_poll_ps = (
        f'curl.exe -sS "{base}/contents/generations/tasks/TASK_ID" '
        f'-H "Authorization: Bearer $env:ARK_API_KEY"'
    )

    return {
        "ok": True,
        "shot": sn,
        "scene_rel": scene_rel,
        "model": model,
        "prompt": prompt,
        "payload_path": str(payload_path),
        "payload_rel": meta["payload"],
        "curl_submit": curl_submit,
        "curl_poll": curl_poll,
        "curl_submit_ps": curl_submit_ps,
        "curl_poll_ps": curl_poll_ps,
        "base_url": base,
    }


def build_shot_failure_card(
    slug: str,
    episode: int,
    shot_n: int,
    error: str,
    *,
    shot: dict[str, Any] | None = None,
    with_curl: bool = True,
) -> dict[str, Any]:
    """One failed shot → UI card fields."""
    err = str(error or "").strip()
    locus = classify_failure_locus(err)
    side = locus["side"]
    rid = _request_id(err)
    media = collect_shot_failure_media(
        slug, episode, shot_n, stage=str(locus.get("stage") or ""), shot=shot
    )
    card: dict[str, Any] = {
        "shot": int(shot_n),
        "side": side,
        "side_zh": side_label_zh(side),
        "stage": locus["stage"],
        "step": locus["step"],
        "detail": locus["detail"],
        "reason": locus["reason"],
        "error": err[:500],
        "request_id": rid,
        "is_root": side != "peer",
        "media": media,
    }
    if with_curl and slug and (
        side in ("input", "output", "sensitive")
        or locus["stage"] in ("i2v", "scene")
    ):
        try:
            verify = write_seedance_verify_payload(slug, episode, shot_n, shot=shot)
            card["verify"] = verify
        except Exception as exc:
            card["verify"] = {"ok": False, "error": str(exc)[:200]}
    return card


def format_hq_failures_for_ui(
    failed_shots: list[dict[str, Any]],
    *,
    slug: str = "",
    episode: int = 0,
) -> str:
    """Fail Loud text：集 → 分镜 → 步骤 → 细分 → 原因（无「下一步」建议）。"""
    cards: list[dict[str, Any]] = []
    for row in failed_shots or []:
        if not isinstance(row, dict):
            continue
        sn = int(row.get("shot") or 0)
        if sn < 1:
            continue
        cards.append(
            build_shot_failure_card(
                slug,
                int(episode or 0),
                sn,
                str(row.get("error") or ""),
                with_curl=False,
            )
        )
    if not cards:
        ep_line = f"第{int(episode)}集 · " if int(episode or 0) > 0 else ""
        return f"{ep_line}产线失败（无镜号明细）"

    roots = [c for c in cards if c.get("is_root")]
    root = roots[0] if roots else cards[0]
    root = build_shot_failure_card(
        slug,
        int(episode or 0),
        int(root["shot"]),
        str(root.get("error") or ""),
        with_curl=True,
    )

    ep = int(episode or 0)
    sn = int(root["shot"])
    lines = [
        f"第{ep}集 · Shot {sn}" if ep > 0 else f"Shot {sn}",
        f"步骤：{root.get('step') or '成片'}",
        f"细分：{root.get('detail') or '其它'}",
        f"原因：{root.get('reason') or root.get('error') or ''}",
    ]
    if root.get("request_id"):
        lines.append(f"RequestId：{root['request_id']}")
    media = root.get("media") if isinstance(root.get("media"), list) else []
    for item in media:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("layer") or "预览")
        url = str(item.get("url") or "")
        if url:
            lines.append(f"预览（{title}）：{url}")

    verify = root.get("verify") if isinstance(root.get("verify"), dict) else {}
    attach_curl = root.get("stage") in ("i2v", "scene") or root.get("side") in (
        "input",
        "output",
        "sensitive",
    )
    if attach_curl and verify.get("ok"):
        lines.append("手验提交：")
        lines.append(str(verify.get("curl_submit_ps") or verify.get("curl_submit") or ""))
        lines.append("手验轮询（替换 <TASK_ID>）：")
        lines.append(
            str(verify.get("curl_poll_ps") or verify.get("curl_poll") or "").replace(
                "TASK_ID", "<TASK_ID>"
            )
        )
        if verify.get("payload_path"):
            lines.append(f"payload：{verify.get('payload_path')}")
    elif attach_curl and verify.get("error"):
        lines.append(f"手验未生成：{verify.get('error')}")
    return "\n".join(lines).strip()


def format_hq_failure_bundle(
    failed_shots: list[dict[str, Any]],
    *,
    slug: str = "",
    episode: int = 0,
) -> dict[str, Any]:
    """Text + media for queue progress / chat attachments."""
    text = format_hq_failures_for_ui(failed_shots, slug=slug, episode=episode)
    media: list[dict[str, Any]] = []
    for row in failed_shots or []:
        if not isinstance(row, dict):
            continue
        sn = int(row.get("shot") or 0)
        if sn < 1:
            continue
        card = build_shot_failure_card(
            slug, int(episode or 0), sn, str(row.get("error") or ""), with_curl=False
        )
        if card.get("is_root"):
            media = list(card.get("media") or [])
            break
    if not media and failed_shots:
        row0 = failed_shots[0] if isinstance(failed_shots[0], dict) else {}
        sn = int(row0.get("shot") or 0)
        if sn > 0:
            card = build_shot_failure_card(
                slug, int(episode or 0), sn, str(row0.get("error") or ""), with_curl=False
            )
            media = list(card.get("media") or [])
    return {"text": text, "media": media, "failure_media": media}
