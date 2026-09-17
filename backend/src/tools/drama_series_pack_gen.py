"""两阶段 SeriesPack 生成：先锁资产规格，再写分镜。

流程：
① premise → Phase1 skeleton（meta/style/cast/locations/props/relationships）
② 校验资产可画性
③ Phase2 各集 shots（只引用资产 id，写 still/motion/camera/dialogue）
④ 合并 + 结构/语义校验；不合格可打回 LLM 一次
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from tools.drama_series_pack import (
    SCHEMA_VERSION,
    CAMERA_MOVES,
    SHOT_SIZES,
    SeriesPack,
    dump_series_pack,
    loads_series_pack,
)
from tools.drama_series_pack_validate import (
    PackIssue,
    assert_series_pack_valid,
    validate_series_pack,
)
from tools.workspace import resolve_safe

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.I)
_DraftFn = Callable[..., str]


PHASE1_SYSTEM = (
    "你是竖屏短剧视觉统筹。只输出一份 JSON 对象（不要 Markdown、不要解释）。\n"
    "任务：根据梗概生成 SeriesPack 的「资产骨架」，先锁定可画规格，不要写分镜。\n"
    "输出字段：\n"
    "{\n"
    '  "meta": {"title","logline","aspect":"9:16","seconds_per_episode","language":"zh-CN"},\n'
    '  "style": {"visual","palette","camera_default","audio_default":"native","bgm_mood","bgm_instruments"},\n'
    '  "cast": [{"id","name","gender","age_band","look_full","look_face","voice","voice_id","trait","catchphrase"}],\n'
    '  "locations": [{"id","name","plate","light","anchors","layout"}],\n'
    '  "props": [{"id","name","look","role"}],\n'
    '  "relationships": ["短名A → 短名B：关系"]\n'
    "}\n"
    "硬性规则：\n"
    "1) id 必须小写英文/数字/下划线，以字母开头（如 linwan）；name 用中文短名，禁止「愚公的孙女」当姓名；\n"
    "2) look_full=正面全身定妆一整句（只写人物本体，禁止手持道具）；look_face=正脸锚点；\n"
    "3) voice=性别+年龄+音域+语速+情绪(+方言)；audio_default 默认 native；\n"
    "4) plate=无人物竖屏空镜一整句，必须含「空镜」或「视频静帧」字样；anchors 1–3 个；\n"
    "5) 角色彼此在年龄段/发型发色/服装主色/独占锚点上拉开差距；\n"
    "6) 场景 1–3 个、道具宁少勿滥；禁止输出 episodes。\n"
)

PHASE2_SYSTEM = (
    "你是竖屏短剧分镜编剧。只输出 JSON 数组 episodes（不要 Markdown、不要解释）。\n"
    "输入已锁定资产包；你只能引用其中的 cast/locations/props 的 id，禁止发明新 id 或改外形。\n"
    "输出：\n"
    '[{"n":1,"title","seconds","beat","shots":[{'
    '"n","t_in","t_out","kind","cast","location","props",'
    '"shot_size","camera","still","motion","dialogue","vo","sfx","audio_mode"'
    "}]}]\n"
    "硬性规则：\n"
    "1) shot_size 只能是 "
    + "/".join(SHOT_SIZES)
    + "；camera 只能是 "
    + "/".join(CAMERA_MOVES)
    + "；\n"
    "2) still=冻结静帧（只给 Seedream），禁止过程词：然后/接着/渐渐/跑向/走向/切到/转场/淡入…；\n"
    "3) motion=相对 still 的动作时序（只给 Seedance）；dialogue/action/hook/reaction 必须有 motion；\n"
    "4) dialogue[].speaker 必须是本镜 cast 里的 id；禁止旧字段「画面」；\n"
    "5) 单集场景≤3、道具≤4；时间轴 t_in/t_out 连续覆盖本集秒数；\n"
    "6) still/motion 里用角色中文短名可以，但不得引入资产包以外的新角色或新场景名。\n"
)


def series_pack_rel(slug: str) -> str:
    return f"dramas/{slug}/series_pack.json"


def series_pack_path(slug: str) -> Path:
    return resolve_safe(series_pack_rel(slug))


def save_series_pack(slug: str, pack: SeriesPack) -> str:
    path = series_pack_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_series_pack(pack) + "\n", encoding="utf-8")
    return series_pack_rel(slug)


def load_saved_series_pack(slug: str) -> SeriesPack | None:
    path = series_pack_path(slug)
    if not path.is_file():
        return None
    return loads_series_pack(path.read_text(encoding="utf-8"))


def extract_json_payload(text: str) -> Any:
    """从 LLM 回复中提取 JSON（对象或数组）。"""
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("LLM 返回空内容")
    fence = _JSON_FENCE_RE.search(raw)
    if fence:
        raw = fence.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # 截取首个 {…} 或 […]
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start = raw.find(open_c)
        end = raw.rfind(close_c)
        if start >= 0 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("无法从 LLM 回复解析 JSON")


def _default_draft(slug: str, prompt: str, *, system: str) -> str:
    from tools.drama_script import draft_text_sync

    return draft_text_sync(slug, prompt, system=system)


def _issues_text(issues: list[PackIssue], *, limit: int = 12) -> str:
    lines = [f"- [{i.level}/{i.code}] {i.path}: {i.message}" for i in issues[:limit]]
    return "\n".join(lines) if lines else "(无)"


def generate_asset_skeleton(
    slug: str,
    premise: str,
    *,
    title: str = "",
    seconds_per_episode: int = 60,
    draft_fn: _DraftFn | None = None,
    repair_notes: str = "",
) -> dict[str, Any]:
    """Phase1：只生成资产骨架（无 episodes）。"""
    draft = draft_fn or _default_draft
    user = (
        f"剧名提示：{title or '（可自拟）'}\n"
        f"每集目标时长：{seconds_per_episode}s\n"
        f"故事梗概：{premise}\n"
    )
    if repair_notes:
        user += f"\n上次校验失败，请按下列问题修正后重新输出完整 JSON：\n{repair_notes}\n"
    raw = draft(slug, user, system=PHASE1_SYSTEM)
    data = extract_json_payload(raw)
    if not isinstance(data, dict):
        raise ValueError("Phase1 必须返回 JSON 对象")
    data.pop("episodes", None)
    data["schema_version"] = SCHEMA_VERSION
    meta = data.setdefault("meta", {})
    if isinstance(meta, dict):
        meta.setdefault("aspect", "9:16")
        meta.setdefault("language", "zh-CN")
        meta.setdefault("seconds_per_episode", seconds_per_episode)
        if title and not str(meta.get("title") or "").strip():
            meta["title"] = title
        if premise and not str(meta.get("logline") or "").strip():
            meta["logline"] = premise[:200]
    # 用空 episodes 先做资产结构校验
    data["episodes"] = []
    pack = loads_series_pack(data)
    issues = validate_series_pack(pack)
    errors = [i for i in issues if i.level == "error"]
    if errors:
        raise ValueError(f"Phase1 资产校验失败：{_issues_text(errors)}")
    out = json.loads(dump_series_pack(pack))
    out.pop("episodes", None)
    return out


def generate_episodes_for_assets(
    slug: str,
    assets: dict[str, Any],
    *,
    episode_count: int = 1,
    seconds_per_episode: int = 60,
    draft_fn: _DraftFn | None = None,
    repair_notes: str = "",
) -> list[dict[str, Any]]:
    """Phase2：在锁定资产上生成 episodes[].shots。"""
    draft = draft_fn or _default_draft
    asset_view = {
        "meta": assets.get("meta"),
        "style": assets.get("style"),
        "cast": [
            {"id": c.get("id"), "name": c.get("name"), "trait": c.get("trait")}
            for c in (assets.get("cast") or [])
            if isinstance(c, dict)
        ],
        "locations": [
            {"id": x.get("id"), "name": x.get("name"), "anchors": x.get("anchors")}
            for x in (assets.get("locations") or [])
            if isinstance(x, dict)
        ],
        "props": [
            {"id": p.get("id"), "name": p.get("name")}
            for p in (assets.get("props") or [])
            if isinstance(p, dict)
        ],
        "relationships": assets.get("relationships") or [],
    }
    user = (
        f"请生成 {episode_count} 集，每集约 {seconds_per_episode} 秒。\n"
        f"已锁定资产（只许引用 id）：\n{json.dumps(asset_view, ensure_ascii=False)}\n"
    )
    if repair_notes:
        user += f"\n上次校验失败，请按下列问题修正后重新输出完整 episodes JSON 数组：\n{repair_notes}\n"
    raw = draft(slug, user, system=PHASE2_SYSTEM)
    data = extract_json_payload(raw)
    if isinstance(data, dict) and isinstance(data.get("episodes"), list):
        episodes = data["episodes"]
    elif isinstance(data, list):
        episodes = data
    else:
        raise ValueError("Phase2 必须返回 episodes 数组或含 episodes 的对象")
    if not episodes:
        raise ValueError("Phase2 episodes 为空")
    return episodes


def merge_series_pack(assets: dict[str, Any], episodes: list[dict[str, Any]]) -> SeriesPack:
    merged = dict(assets)
    merged["schema_version"] = SCHEMA_VERSION
    merged["episodes"] = episodes
    return assert_series_pack_valid(merged)


def generate_series_pack_from_premise(
    slug: str,
    premise: str,
    *,
    title: str = "",
    episode_count: int = 1,
    seconds_per_episode: int = 60,
    max_repairs: int = 1,
    draft_fn: _DraftFn | None = None,
    persist: bool = True,
) -> SeriesPack:
    """端到端两阶段生成；校验失败时最多打回 LLM max_repairs 次。"""
    text = str(premise or "").strip()
    if not text:
        raise ValueError("premise 不能为空")
    ep_n = max(1, int(episode_count or 1))
    ep_sec = max(15, min(180, int(seconds_per_episode or 60)))

    repair = ""
    assets: dict[str, Any] | None = None
    for attempt in range(max_repairs + 1):
        try:
            assets = generate_asset_skeleton(
                slug,
                text,
                title=title,
                seconds_per_episode=ep_sec,
                draft_fn=draft_fn,
                repair_notes=repair,
            )
            break
        except Exception as exc:
            if attempt >= max_repairs:
                raise
            repair = str(exc)
    assert assets is not None

    repair = ""
    pack: SeriesPack | None = None
    for attempt in range(max_repairs + 1):
        try:
            episodes = generate_episodes_for_assets(
                slug,
                assets,
                episode_count=ep_n,
                seconds_per_episode=ep_sec,
                draft_fn=draft_fn,
                repair_notes=repair,
            )
            pack = merge_series_pack(assets, episodes)
            break
        except Exception as exc:
            if attempt >= max_repairs:
                raise
            repair = str(exc)
    assert pack is not None

    if persist:
        save_series_pack(slug, pack)
    return pack
