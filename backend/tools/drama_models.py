"""Shot-kind model router (Q0–Q3).

Project-level `models.json` is the research card + routing table.
Q3 binds motion ladder L0–L3 to kind. L2 is lip (dialogue); L3 is action
dual-keyframe. Expensive I2V providers stay unavailable until a complete card.
"""

from __future__ import annotations

import json
from typing import Any

from tools.workspace import resolve_safe

SHOT_KINDS = (
    "establishing",
    "insert",
    "dialogue",
    "reaction",
    "action",
    "crowd",
    "title",
)
SHOT_SIZES = ("WS", "MS", "MCU", "CU", "ECU")
KIND_DEFAULT_SIZE = {
    "establishing": "WS",
    "insert": "CU",
    "dialogue": "MCU",
    "reaction": "CU",
    "action": "MS",
    "crowd": "WS",
    "title": "WS",
}
# Built-in ladder before models.json overlay (L4 is Q6 solo action + keys).
KIND_LADDER = {
    "establishing": "L0",
    "insert": "L0",
    "dialogue": "L2",
    "reaction": "L1",
    "action": "L3",
    "crowd": "L0",
    "title": "L0",
}
L0_KINDS = frozenset(k for k, v in KIND_LADDER.items() if v == "L0")
LADDER_RANK = {"L0": 0, "L1": 1, "L2": 2, "L3": 3, "L4": 4, "L5": 5}
Q0_MAX_LADDER = "L1"
Q3_MAX_LADDER = "L3"
Q6_MAX_LADDER = "L4"
EXPENSIVE_I2V = frozenset({"kling", "hailuo"})
MAX_EXPENSIVE_I2V = 2
CURRENCY = "CNY"
PRESET_IDS = ("cheap", "balanced", "pro")
DEFAULT_PRESET = "balanced"

# Nodes that can be individually configured (mirrors drama_config.NODE_KEYS).
NODE_KEYS = (
    "script",
    "image",
    "motion",
    "lip",
    "tts",
    "subtitle",
    "bgm",
    "sfx",
    "qc",
)

_RESEARCH_FIELDS = ("cost_per_shot", "fallback", "notes")


def models_rel(slug: str) -> str:
    return f"dramas/{slug}/models.json"


def normalize_kind(raw: Any) -> str:
    kind = str(raw or "").strip().lower()
    return kind if kind in SHOT_KINDS else ""


def normalize_size(raw: Any) -> str:
    size = str(raw or "").strip().upper()
    return size if size in SHOT_SIZES else ""


def normalize_ladder(raw: Any) -> str:
    ladder = str(raw or "").strip().upper()
    if ladder in LADDER_RANK:
        return ladder
    return ""


def infer_kind(shot: dict[str, Any]) -> str:
    existing = normalize_kind(shot.get("kind"))
    if existing:
        return existing
    dialogue = str(shot.get("对白") or "").strip()
    return "dialogue" if dialogue else "establishing"


def infer_size(shot: dict[str, Any]) -> str:
    existing = normalize_size(shot.get("size"))
    if existing:
        return existing
    return KIND_DEFAULT_SIZE.get(infer_kind(shot), "MS")


def infer_speaker(shot: dict[str, Any]) -> str:
    existing = str(shot.get("speaker") or "").strip()
    if existing:
        return existing
    roles = shot.get("角色") or []
    if isinstance(roles, list) and roles:
        return str(roles[0] or "").strip()
    if isinstance(roles, str) and roles.strip():
        return roles.split(",")[0].strip()
    return ""


def apply_shot_class(shot: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    """Fill kind/size/speaker. Locked kind is not overwritten unless force."""
    locked = set(shot.get("locked") or [])
    kind_locked = ("kind" in locked or "shot" in locked) and not force
    if kind_locked:
        shot["kind"] = normalize_kind(shot.get("kind")) or infer_kind({**shot, "kind": ""})
        shot["size"] = normalize_size(shot.get("size")) or infer_size(shot)
    else:
        seed = {**shot, "kind": "" if force else shot.get("kind"), "size": "" if force else shot.get("size")}
        shot["kind"] = infer_kind(seed)
        shot["size"] = infer_size({**seed, "kind": shot["kind"]})
    if not str(shot.get("speaker") or "").strip():
        shot["speaker"] = infer_speaker({**shot, "speaker": ""})
    else:
        shot["speaker"] = str(shot.get("speaker") or "").strip()
    return shot


def default_providers() -> dict[str, dict[str, Any]]:
    """Research cards. Only mock/l0 are available until a complete card is marked."""
    return {
        "l0": {
            "available": True,
            "cost_per_shot": 0,
            "rpm": 0,
            "timeout_s": 30,
            "fallback": "l0",
            "notes": "静图 Ken Burns（ffmpeg）。Q0 定场/群像/标题默认。",
        },
        "mock": {
            "available": True,
            "cost_per_shot": 0,
            "rpm": 0,
            "timeout_s": 180,
            "fallback": "l0",
            "notes": "本地 ffmpeg 模拟 I2V，仅验收链路。无商用输出。",
        },
        "http": {
            "available": False,
            "cost_per_shot": 0.5,
            "rpm": 20,
            "timeout_s": 120,
            "fallback": "mock",
            "notes": "自定义 I2V_API_URL。Q0 未接真服务，禁止 available=true 除非填调研卡。",
        },
        "pollinations": {
            "available": False,
            "cost_per_shot": 0,
            "rpm": 10,
            "timeout_s": 90,
            "fallback": "mock",
            "notes": "免费图生，非稳定 I2V。Q0 不作为运动主路径。",
        },
        "kling": {
            "available": False,
            "cost_per_shot": 2.5,
            "rpm": 10,
            "timeout_s": 180,
            "fallback": "mock",
            "notes": "可灵类动作 I2V，需商务 API。Q0 未开通。",
        },
        "hailuo": {
            "available": False,
            "cost_per_shot": 2.0,
            "rpm": 10,
            "timeout_s": 180,
            "fallback": "mock",
            "notes": "海螺/MiniMax 类 I2V。Q0 未开通。",
        },
        "musetalk": {
            "available": False,
            "cost_per_shot": 0.8,
            "rpm": 6,
            "timeout_s": 180,
            "fallback": "mock",
            "notes": "对话特写口型。Q2 默认 mock；无完整调研卡禁止 available。",
        },
        "wav2lip": {
            "available": False,
            "cost_per_shot": 0.4,
            "rpm": 6,
            "timeout_s": 180,
            "fallback": "mock",
            "notes": "开源口型，画质不稳。Q2 候选，Q0 未接。",
        },
        "pixverse": {
            "available": True,
            "cost_per_shot": 0.36,
            "rpm": 10,
            "timeout_s": 240,
            "fallback": "mock",
            "notes": "PixVerse 对口型 pixverse-lipsync（0.12元/秒，3秒约0.36），走专属 MaaS 端点。",
        },
        "pixverse-lipsync": {
            "available": True,
            "cost_per_shot": 0.36,
            "rpm": 10,
            "timeout_s": 240,
            "fallback": "mock",
            "notes": "PixVerse 对口型 pixverse-lipsync（0.12元/秒，3秒约0.36），走专属 MaaS 端点。",
        },
        "wanx": {
            "available": True,
            "cost_per_shot": 0.5,
            "rpm": 10,
            "timeout_s": 180,
            "fallback": "pollinations",
            "notes": "阿里百炼通义万相文生图（DASHSCOPE_API_KEY）。",
        },
        "wanx-video": {
            "available": True,
            "cost_per_shot": 2.5,
            "rpm": 10,
            "timeout_s": 300,
            "fallback": "mock",
            "notes": "阿里百炼通义万相图生视频（DASHSCOPE_API_KEY）。",
        },
        "cosyvoice": {
            "available": True,
            "cost_per_shot": 0.05,
            "rpm": 60,
            "timeout_s": 120,
            "fallback": "edge-tts",
            "notes": "阿里百炼语音合成/音色复刻（DASHSCOPE_API_KEY）。",
        },
        "kling-image": {
            "available": True,
            "cost_per_shot": 0.8,
            "rpm": 10,
            "timeout_s": 240,
            "fallback": "pollinations",
            "notes": "可灵满血图模型（图片生成+编辑融合），走专属 MaaS 端点。",
        },
        "kling-video": {
            "available": True,
            "cost_per_shot": 3.0,
            "rpm": 10,
            "timeout_s": 420,
            "fallback": "mock",
            "notes": "可灵视频生成（文生/图生/参考生视频），走专属 MaaS 端点。",
        },
    }


def default_models() -> dict[str, Any]:
    return {
        "currency": CURRENCY,
        "providers": default_providers(),
        "image": {
            "establishing": {"provider": "http", "model": "flux-scene", "cost_per_shot": 0.05},
            "insert": {"provider": "http", "model": "flux-scene", "cost_per_shot": 0.05},
            "dialogue": {"provider": "http", "model": "char-lora", "refs": ["character"], "cost_per_shot": 0.08},
            "reaction": {"provider": "http", "model": "char-lora", "refs": ["character"], "cost_per_shot": 0.08},
            "action": {"provider": "http", "model": "char-lora", "cost_per_shot": 0.08},
            "crowd": {"provider": "http", "model": "flux-scene", "cost_per_shot": 0.05},
            "title": {"provider": "http", "model": "flux-scene", "cost_per_shot": 0.02},
        },
        "motion": {
            "establishing": {"ladder": "L0", "provider": "l0"},
            "insert": {"ladder": "L0", "provider": "l0"},
            "dialogue": {"ladder": "L2", "provider": "mock", "fallback": "L1"},
            "reaction": {"ladder": "L1", "provider": "mock", "fallback": "L0"},
            "action": {"ladder": "L3", "provider": "kling", "fallback": "L1"},
            "crowd": {"ladder": "L0", "provider": "l0"},
            "title": {"ladder": "L0", "provider": "l0"},
        },
        "lip": {"provider": "musetalk", "only_kinds": ["dialogue"], "only_sizes": ["CU", "MCU", "ECU"], "fallback": "mock"},
        "bgm": {"provider": "library", "duck_db": -12, "license": "user_upload"},
        "sfx": {"provider": "library"},
        "qc": {
            "identity_min": 0.65,
            "ssim_min": 0.85,
            "lufs_target": -14,
            "lufs_min": -16,
            "lufs_max": -12,
            "true_peak_dbtp": -1,
            "lse_c_min": 0.0,
            "lse_d_max": 1.0,
        },
        "preset": DEFAULT_PRESET,
        "nodes": {},
        "script": {"provider": "deepseek", "model": "deepseek-v4-flash", "refine_model": "deepseek-reasoner"},
        "tts": {"provider": "edge-tts"},
        "subtitle": {"style": "static"},
        "budget": {
            "enabled": False,
            "per_episode": 0.0,
            "warn_at": 0.8,
            "note": "",
        },
    }


def research_complete(card: dict[str, Any]) -> bool:
    if not isinstance(card, dict):
        return False
    notes = str(card.get("notes") or "").strip()
    fallback = str(card.get("fallback") or "").strip()
    try:
        cost = float(card.get("cost_per_shot"))
    except (TypeError, ValueError):
        return False
    if cost < 0:
        return False
    return bool(notes and fallback)


def _coerce_providers(raw: Any) -> dict[str, dict[str, Any]]:
    base = default_providers()
    incoming = raw if isinstance(raw, dict) else {}
    out: dict[str, dict[str, Any]] = {}
    ids = list(base.keys()) + [k for k in incoming if k not in base]
    for pid in ids:
        card = {**base.get(pid, {}), **(incoming.get(pid) if isinstance(incoming.get(pid), dict) else {})}
        card["cost_per_shot"] = float(card.get("cost_per_shot") or 0)
        card["rpm"] = int(card.get("rpm") or 0)
        card["timeout_s"] = int(card.get("timeout_s") or 60)
        card["fallback"] = str(card.get("fallback") or "mock").strip() or "mock"
        card["notes"] = str(card.get("notes") or "").strip()
        available = bool(card.get("available"))
        if available and not research_complete(card):
            available = False
        # Q0: never auto-enable unpaid commercial endpoints.
        if pid in ("kling", "hailuo", "musetalk", "wav2lip") and not research_complete(card):
            available = False
        card["available"] = available
        out[pid] = card
    return out


def normalize_models(raw: Any) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    base = default_models()
    motion_in = data.get("motion") if isinstance(data.get("motion"), dict) else {}
    image_in = data.get("image") if isinstance(data.get("image"), dict) else {}
    motion: dict[str, Any] = {}
    image: dict[str, Any] = {}
    for kind in SHOT_KINDS:
        md = {**(base["motion"].get(kind) or {}), **(motion_in.get(kind) if isinstance(motion_in.get(kind), dict) else {})}
        md["ladder"] = normalize_ladder(md.get("ladder")) or KIND_LADDER[kind]
        md["provider"] = str(md.get("provider") or ("l0" if KIND_LADDER[kind] == "L0" else "mock"))
        if md.get("fallback"):
            md["fallback"] = str(md["fallback"])
        motion[kind] = md
        im = {**(base["image"].get(kind) or {}), **(image_in.get(kind) if isinstance(image_in.get(kind), dict) else {})}
        image[kind] = im
    currency = str(data.get("currency") or CURRENCY).strip().upper() or CURRENCY
    preset = str(data.get("preset") or DEFAULT_PRESET).strip().lower()
    if preset not in PRESET_IDS:
        preset = DEFAULT_PRESET
    nodes = data.get("nodes") if isinstance(data.get("nodes"), dict) else {}
    return {
        "currency": currency,
        "preset": preset,
        "nodes": nodes,
        "providers": _coerce_providers(data.get("providers")),
        "image": image,
        "motion": motion,
        "lip": {**base["lip"], **(data.get("lip") if isinstance(data.get("lip"), dict) else {})},
        "bgm": {**base["bgm"], **(data.get("bgm") if isinstance(data.get("bgm"), dict) else {})},
        "sfx": {**base["sfx"], **(data.get("sfx") if isinstance(data.get("sfx"), dict) else {})},
        "script": {**base["script"], **(data.get("script") if isinstance(data.get("script"), dict) else {})},
        "tts": {**base["tts"], **(data.get("tts") if isinstance(data.get("tts"), dict) else {})},
        "subtitle": {**base["subtitle"], **(data.get("subtitle") if isinstance(data.get("subtitle"), dict) else {})},
        "qc": {**base["qc"], **(data.get("qc") if isinstance(data.get("qc"), dict) else {})},
        "budget": {**base["budget"], **(data.get("budget") if isinstance(data.get("budget"), dict) else {})},
    }


def cost_entry(
    *,
    provider: str,
    layer: str,
    cost: float,
    shot: int | None = None,
) -> dict[str, Any]:
    """Build one structured cost-log entry (shared shape, no side effects)."""
    from tools.drama_shots import utc_now

    return {
        "shot": int(shot) if shot else None,
        "layer": str(layer),
        "provider": str(provider),
        "cost": round(max(0.0, float(cost)), 4),
        "at": utc_now(),
    }


def record_cost(
    slug: str,
    episode: int,
    *,
    provider: str,
    layer: str,
    cost: float,
    shot: int | None = None,
) -> dict[str, Any] | None:
    """Append one actual spend entry to the episode cost log (P1-9).

    Lives on the episode doc (shots.json) so it is part of the workbench truth
    source. Returns None if the doc does not exist yet (nothing to record).
    """
    from tools.drama_shots import load_doc, save_doc

    doc = load_doc(slug, int(episode))
    if doc is None:
        return None
    entries = doc.get("cost_log")
    if not isinstance(entries, list):
        entries = []
    entries.append(cost_entry(provider=provider, layer=layer, cost=cost, shot=shot))
    doc["cost_log"] = entries
    save_doc(doc)
    return doc.get("cost_log")


def append_cost(
    doc: dict[str, Any],
    *,
    provider: str,
    layer: str,
    cost: float,
    shot: int | None = None,
) -> dict[str, Any]:
    """Append a cost entry into an in-memory episode doc (no disk write).

    Used by the bulk render loop so each shot's spend is recorded exactly once
    without reloading/saving shots.json per shot.
    """
    entries = doc.get("cost_log")
    if not isinstance(entries, list):
        entries = []
        doc["cost_log"] = entries
    entry = cost_entry(provider=provider, layer=layer, cost=cost, shot=shot)
    entries.append(entry)
    return entry


def actual_episode_cost(slug: str, episode: int) -> float:
    """Sum recorded actual spend for an episode (0 when nothing recorded)."""
    from tools.drama_shots import load_doc

    doc = load_doc(slug, int(episode))
    if not doc:
        return 0.0
    entries = doc.get("cost_log")
    if not isinstance(entries, list):
        return 0.0
    total = 0.0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            total += float(entry.get("cost") or 0)
        except (TypeError, ValueError):
            continue
    return round(total, 4)


def budget_state(
    slug: str,
    episode: int | None = None,
    shots: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """R7: per-episode estimated spend + budget gate (warn/block).

    spent = i2v estimate + lip estimate + image estimate from the current
    shot list. When budget.enabled and spent > per_episode, generation of
    expensive layers is blocked until the budget is raised or disabled.
    """
    from tools.drama_shots import load_doc

    doc = load_models(slug)
    b = doc.get("budget") or {}
    try:
        enabled = bool(b.get("enabled"))
        per_episode = float(b.get("per_episode") or 0)
        warn_at = float(b.get("warn_at") or 0.8)
    except (TypeError, ValueError):
        enabled = False
        per_episode = 0.0
        warn_at = 0.8
    if per_episode < 0:
        per_episode = 0.0
    warn_at = max(0.05, min(warn_at, 1.0))

    if not shots and episode:
        d = load_doc(slug, episode)
        shots = (d or {}).get("shots") or []
    shots = shots or []
    ep_doc = load_doc(slug, episode) if episode else None
    est = estimate_episode_i2v(slug, shots, episode=episode, doc=ep_doc)
    spent = round(float(est.get("i2v_estimate") or 0) + float(est.get("lip_estimate") or 0) + float(est.get("image_estimate") or 0), 4)
    actual_spent = actual_episode_cost(slug, episode) if episode else 0.0

    if not enabled or per_episode <= 0:
        return {
            "enabled": False,
            "per_episode": round(per_episode, 2),
            "warn_at": warn_at,
            "spent": spent,
            "actual_spent": actual_spent,
            "remaining": None,
            "ratio": None,
            "warn": False,
            "blocked": False,
            "reason": "预算未启用",
            "currency": str(doc.get("currency") or CURRENCY),
        }

    remaining = round(per_episode - spent, 4)
    ratio = round(spent / per_episode, 4) if per_episode > 0 else 0.0
    blocked = ratio >= 1.0
    warn = ratio >= warn_at and not blocked
    reason = ""
    if blocked:
        reason = f"本集预算已超支（已估 {spent} / {per_episode}），请先调高预算或关闭闸门"
    elif warn:
        reason = f"本集预算已用 {ratio * 100:.0f}%（{spent} / {per_episode}），接近上限"
    return {
        "enabled": True,
        "per_episode": round(per_episode, 2),
        "warn_at": warn_at,
        "spent": spent,
        "actual_spent": actual_spent,
        "remaining": remaining,
        "ratio": ratio,
        "warn": warn,
        "blocked": blocked,
        "reason": reason,
        "currency": str(doc.get("currency") or CURRENCY),
    }


def load_models(slug: str) -> dict[str, Any]:
    rel = models_rel(slug)
    path = resolve_safe(rel)
    if not path.is_file():
        doc = default_models()
        save_models(slug, doc)
        return doc
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    doc = normalize_models(raw)
    return doc


def save_models(slug: str, doc: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_models(doc)
    path = resolve_safe(models_rel(slug))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return normalized


def set_provider_available(slug: str, provider_id: str, available: bool) -> dict[str, Any]:
    doc = load_models(slug)
    pid = str(provider_id or "").strip()
    card = (doc.get("providers") or {}).get(pid)
    if not isinstance(card, dict):
        raise ValueError(f"未知 provider：{pid}")
    if available and not research_complete(card):
        raise ValueError(f"{pid} 调研卡不完整（需要 notes / fallback / cost_per_shot），不能标 available")
    card["available"] = bool(available)
    doc["providers"][pid] = card
    return save_models(slug, doc)


def cap_ladder(ladder: str, *, max_ladder: str = Q3_MAX_LADDER) -> str:
    rank = LADDER_RANK.get(normalize_ladder(ladder) or "L0", 0)
    max_rank = LADDER_RANK.get(normalize_ladder(max_ladder) or Q3_MAX_LADDER, 3)
    if rank <= 0:
        return "L0"
    if rank > max_rank:
        return max_ladder
    for name, value in LADDER_RANK.items():
        if value == rank:
            return name
    return "L0"


def cap_ladder_q0(ladder: str) -> str:
    return cap_ladder(ladder, max_ladder=Q0_MAX_LADDER)


def planned_ladder(shot: dict[str, Any], models: dict[str, Any] | None = None) -> str:
    kind = infer_kind(shot)
    route = ((models or {}).get("motion") or {}).get(kind) or {}
    return normalize_ladder(route.get("ladder")) or KIND_LADDER.get(kind, "L1")


def effective_motion_ladder(shot: dict[str, Any], *, slug: str | None = None, models: dict[str, Any] | None = None) -> str:
    """Planned kind ladder. L4 only when a solo action shot has 3+ key poses."""
    kind = infer_kind(shot)
    if kind in L0_KINDS:
        return "L0"
    if kind == "action":
        from tools.drama_keys import keys_ready

        if keys_ready(shot, slug=slug):
            return "L4"
    if models is None and slug:
        models = load_models(str(slug))
    planned = planned_ladder(shot, models)
    if planned == "L0":
        return "L0"
    return cap_ladder(planned)


def i2v_run_ladder(shot: dict[str, Any], *, slug: str | None = None, models: dict[str, Any] | None = None) -> str:
    """Ladder actually used for I2V. L2 (lip) falls back to L1 idle; L3 may fall to L1."""
    models = models or (load_models(str(slug)) if slug else None)
    planned = effective_motion_ladder(shot, slug=slug, models=models)
    if planned == "L0":
        return "L0"
    if planned == "L4":
        return "L4"
    kind = infer_kind(shot)
    route = ((models or {}).get("motion") or {}).get(kind) or {}
    fallback = normalize_ladder(route.get("fallback")) or "L1"
    if fallback in ("L0", "L2"):
        fallback = "L1" if planned != "L0" else "L0"
    if planned == "L2":
        return fallback if fallback != "L2" else "L1"
    if planned == "L3":
        wanted = str(route.get("provider") or "kling")
        if models and provider_usable(models, wanted):
            return "L3"
        return fallback if fallback in ("L1", "L3") else "L1"
    return "L1"


def provider_usable(models: dict[str, Any], provider_id: str) -> bool:
    card = (models.get("providers") or {}).get(provider_id) or {}
    return bool(card.get("available")) and research_complete(card)


def resolve_provider(models: dict[str, Any], provider_id: str, *, hops: int = 0) -> str:
    pid = str(provider_id or "mock").strip() or "mock"
    if hops > 6:
        return "l0"
    if provider_usable(models, pid):
        return pid
    card = (models.get("providers") or {}).get(pid) or {}
    fallback = str(card.get("fallback") or "mock")
    if fallback == pid:
        return "l0"
    return resolve_provider(models, fallback, hops=hops + 1)


def provider_cost(models: dict[str, Any], provider_id: str) -> float:
    card = (models.get("providers") or {}).get(provider_id) or {}
    try:
        return max(0.0, float(card.get("cost_per_shot") or 0))
    except (TypeError, ValueError):
        return 0.0


def estimate_i2v(slug: str, shot: dict[str, Any], *, models: dict[str, Any] | None = None) -> dict[str, Any]:
    models = models or load_models(slug)
    kind = infer_kind(shot)
    planned = planned_ladder(shot, models)
    run = i2v_run_ladder(shot, models=models)
    currency = str(models.get("currency") or CURRENCY)
    route = (models.get("motion") or {}).get(kind) or {}
    if run == "L0" or planned == "L0":
        return {
            "kind": kind,
            "ladder": "L0",
            "planned_ladder": planned,
            "provider": "l0",
            "cost_per_shot": 0,
            "currency": currency,
            "will_run": False,
            "expensive": False,
            "reason": "定场类镜头强制 L0 静图运镜",
        }
    if run == "L4" or planned == "L4":
        return {
            "kind": kind,
            "ladder": "L4",
            "planned_ladder": "L4",
            "provider": "mock",
            "cost_per_shot": 0,
            "currency": currency,
            "will_run": True,
            "expensive": False,
            "reason": "单人 action 稀疏关键帧补间（降级 mock/光流）",
        }
    wanted = str(route.get("provider") or "mock")
    provider = resolve_provider(models, wanted)
    expensive = provider in EXPENSIVE_I2V and provider_usable(models, provider)
    cost = provider_cost(models, provider) if run != "L0" else 0
    reason = ""
    if planned == "L3" and run != "L3":
        reason = f"L3 贵模型不可用，回退 {run}/{provider}"
    elif planned == "L2":
        reason = "对话镜口型走 L2；I2V 仅为 L1 idle"
    return {
        "kind": kind,
        "ladder": run,
        "planned_ladder": planned,
        "provider": provider,
        "cost_per_shot": round(cost, 4),
        "currency": currency,
        "will_run": True,
        "expensive": expensive,
        "reason": reason,
    }


def estimate_episode_i2v(
    slug: str,
    shots: list[dict[str, Any]],
    *,
    episode: int | None = None,
    doc: dict[str, Any] | None = None,
) -> dict[str, Any]:
    models = load_models(slug)
    currency = str(models.get("currency") or CURRENCY)
    total = 0.0
    l1 = 0
    l0 = 0
    l3 = 0
    l4 = 0
    expensive = 0
    deferred = 0
    for shot in shots:
        info = estimate_i2v(slug, shot, models=models)
        if info.get("will_run"):
            if info.get("expensive") and expensive >= MAX_EXPENSIVE_I2V:
                deferred += 1
                info = {**info, "expensive": False, "provider": resolve_provider(models, "mock"), "cost_per_shot": 0}
            total += float(info.get("cost_per_shot") or 0)
            if info.get("ladder") == "L3":
                l3 += 1
            elif info.get("ladder") == "L4":
                l4 += 1
            else:
                l1 += 1
            if info.get("expensive"):
                expensive += 1
        else:
            l0 += 1
    from tools.drama_lip import estimate_episode_lip
    from tools.drama_styles import estimate_episode_image

    lip = estimate_episode_lip(slug, shots)
    image = estimate_episode_image(slug, shots, episode=episode, doc=doc)
    return {
        "currency": currency,
        "i2v_estimate": round(total, 4),
        "l1_shots": l1,
        "l0_shots": l0,
        "l3_shots": l3,
        "l4_shots": l4,
        "expensive_shots": expensive,
        "expensive_cap": MAX_EXPENSIVE_I2V,
        "expensive_deferred": deferred,
        "shot_count": len(shots),
        "lip_estimate": lip.get("lip_estimate") or 0,
        "lip_shots": lip.get("lip_shots") or 0,
        "image_estimate": image.get("image_estimate") or 0,
        "image_character_shots": image.get("image_character_shots") or 0,
        "image_scene_shots": image.get("image_scene_shots") or 0,
        "style_id": image.get("style_id") or "",
        "style_title": image.get("style_title") or "",
    }


def public_models(doc: dict[str, Any]) -> dict[str, Any]:
    return normalize_models(doc)


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``patch`` into ``base``; nested dicts merge by key."""
    out: dict[str, Any] = dict(base)
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _load_episode_doc(slug: str, episode: int) -> dict[str, Any] | None:
    from tools.drama_shots import load_doc

    return load_doc(slug, int(episode))


def models_with_overrides(
    slug: str,
    *,
    shot: dict[str, Any] | None = None,
    episode: int | None = None,
    doc: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Full three-layer effective models for a render decision.

    Layers (low → high): project models.json → episode style pack →
    episode `models_overrides` → per-shot `shot_models[n]`. The result is
    re-normalized so ladder/provider fallbacks stay valid.
    """
    from tools.drama_styles import load_style, overlay_style

    models = load_models(slug)

    ep_doc = doc
    style_id = ""
    if ep_doc is not None:
        style_id = str(ep_doc.get("style_id") or "")
    elif episode:
        ep_doc = _load_episode_doc(slug, int(episode))
        style_id = str((ep_doc or {}).get("style_id") or "")

    if style_id:
        style = load_style(slug, style_id)
        if style:
            models = overlay_style(models, style)

    ep_doc = ep_doc or {}
    node_ov = ep_doc.get("models_overrides")
    if isinstance(node_ov, dict):
        for node, value in node_ov.items():
            if node in NODE_KEYS and isinstance(value, dict):
                models[node] = _deep_merge(models.get(node) or {}, value)

    if shot:
        shot_models = ep_doc.get("shot_models")
        if isinstance(shot_models, dict):
            n = str(shot.get("n") or "").strip()
            ov = shot_models.get(n)
            if isinstance(ov, dict):
                for node, value in ov.items():
                    if node in NODE_KEYS and isinstance(value, dict):
                        models[node] = _deep_merge(models.get(node) or {}, value)

    return normalize_models(models)


# ---------------------------------------------------------------------------
# S0 honest layer: provider name <-> registered adapter alignment.
# ---------------------------------------------------------------------------

# S1/S2/S3: adapters that exist but need an env URL/key before they can produce
# a true output. Until configured, they honestly degrade (not "missing").
# capability -> provider -> config attribute name that must be non-empty.
_ENV_GATED: dict[str, dict[str, str]] = {
    "image": {
        "jimeng": "CONSISTENT_IMAGE_URL",
        "wanx": "DASHSCOPE_API_KEY",
        "dashscope": "DASHSCOPE_API_KEY",
        "kling": "DASHSCOPE_MAAS_BASE_URL",
        "kling-image": "DASHSCOPE_MAAS_BASE_URL",
    },
    "i2v": {
        "kling": "I2V_API_URL",
        "hailuo": "I2V_API_URL",
        "wanx-video": "DASHSCOPE_API_KEY",
        "dashscope-i2v": "DASHSCOPE_API_KEY",
        "kling-video": "DASHSCOPE_MAAS_BASE_URL",
        "kling-maas": "DASHSCOPE_MAAS_BASE_URL",
    },
    "tts": {
        "volcano": "TTS_API_URL",
        "ms": "TTS_API_URL",
        "azure": "TTS_API_URL",
        "dashscope-tts": "DASHSCOPE_API_KEY",
        "cosyvoice": "DASHSCOPE_API_KEY",
        "qwen-tts": "DASHSCOPE_API_KEY",
    },
    "lip": {
        "musetalk": "LIP_API_URL",
        "wav2lip": "LIP_API_URL",
        "pixverse": "DASHSCOPE_MAAS_BASE_URL",
        "pixverse-lipsync": "DASHSCOPE_MAAS_BASE_URL",
    },
}


def provider_health(models: dict[str, Any]) -> dict[str, Any]:
    """S0: report whether each node's configured provider name matches a real adapter.

    Returns a flat list of per-node/per-kind entries plus an `items` keyed by
    capability. Each entry has:
        written   what the node config says
        real      the actual adapter id it resolves to
        status    live | alias | missing | idle
        available whether the research card is available
        reason    human-readable degrade note (Chinese)
    """
    from tools.providers import registry

    snap = registry.registered_snapshot()
    providers = models.get("providers") if isinstance(models.get("providers"), dict) else {}

    def check(capability: str, written: Any, kind: str = "") -> dict[str, Any]:
        written = str(written or "").strip()
        entry = {
            "capability": capability,
            "kind": kind,
            "written": written,
            "real": "",
            "status": "",
            "available": False,
            "reason": "",
        }

        if not written:
            entry.update(status="idle", reason="未配置")
            return entry

        # S1/S2/S3: 适配器已装但缺 env 配置 → 诚实 gated（会降级到免费后端）。
        env_attr = _ENV_GATED.get(capability, {}).get(written)
        if env_attr:
            from config import config as _cfg

            if not str(getattr(_cfg, env_attr, "") or "").strip():
                entry.update(
                    real=written,
                    status="gated",
                    reason=f"{written} 适配器已装但未配置 {env_attr}，降级到免费后端",
                )
                return entry

        # 非商用名：名实相符，只看是否有适配器。
        has_adapter = bool(snap.get(capability, {}).get(written))
        if not has_adapter:
            entry.update(
                real=written,
                status="missing",
                reason=f"无 {capability} 适配器（{written}）",
            )
            return entry

        c = providers.get(written)
        available = bool(c.get("available")) if isinstance(c, dict) else True
        entry.update(real=written, status="live", available=available, reason="已接通")
        return entry

    items: list[dict[str, Any]] = []
    # tts / lip / subtitle are scalar nodes.
    for node, cap in (("tts", "tts"), ("lip", "lip")):
        cfg = models.get(node) if isinstance(models.get(node), dict) else {}
        items.append(check(cap, cfg.get("provider"), kind=""))

    # image / motion are per-kind maps.
    for kind in SHOT_KINDS:
        img = (models.get("image") if isinstance(models.get("image"), dict) else {}).get(kind) or {}
        mot = (models.get("motion") if isinstance(models.get("motion"), dict) else {}).get(kind) or {}
        items.append(check("image", img.get("provider"), kind=kind))
        items.append(check("i2v", mot.get("provider"), kind=kind))

    by_cap: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_cap.setdefault(item["capability"], []).append(item)

    healthy = all(it["status"] in ("live", "idle") for it in items)
    return {
        "healthy": healthy,
        "degraded_count": sum(1 for it in items if it["status"] in ("missing", "gated")),
        "items": items,
        "by_capability": by_cap,
    }
