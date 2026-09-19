"""SeriesPack：短剧唯一文字真相源（剧本工程规格）。

本模块定义结构化剧包 schema，下游资产 / 静帧 / 视频 / 配音只许引用字段，
禁止二次扩写外形与场景。

字段设计对齐火山方舟：
- still → Seedream 首帧（姿态冻结）
- motion + camera + shot_size → Seedance 图生视频
- dialogue / voice → Seedance 自带声或 Seed Audio
- look_full / plate → Seedream 资产图
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "1.0.0"

CameraMove = Literal["推", "拉", "摇", "移", "跟", "升", "降", "环绕", "固定"]
ShotSize = Literal["远景", "全景", "中景", "近景", "特写"]
ShotKind = Literal[
    "hook",
    "dialogue",
    "action",
    "reaction",
    "insert",
    "establishing",
    "title",
    "crowd",
]
AudioMode = Literal["native", "tts", "silent"]

# still 中禁止出现的过程/剪辑词（校验器用）
STILL_PROCESS_FORBIDDEN = frozenset(
    {
        "然后",
        "接着",
        "随后",
        "渐渐",
        "逐渐",
        "跑向",
        "走向",
        "走去",
        "跑去",
        "切到",
        "切镜",
        "切换",
        "转场",
        "淡入",
        "淡出",
        "切黑",
        "黑场",
        "叠化",
        "闪白",
    }
)

CAMERA_MOVES: tuple[str, ...] = ("推", "拉", "摇", "移", "跟", "升", "降", "环绕", "固定")
SHOT_SIZES: tuple[str, ...] = ("远景", "全景", "中景", "近景", "特写")

_GENDER_ALIASES: dict[str, Literal["male", "female", "other"]] = {
    "male": "male",
    "m": "male",
    "男": "male",
    "男性": "male",
    "男子": "male",
    "男生": "male",
    "female": "female",
    "f": "female",
    "女": "female",
    "女性": "female",
    "女子": "female",
    "女生": "female",
    "other": "other",
    "其他": "other",
    "中性": "other",
    "未知": "other",
}

_HANDHELD_LOOK_RE = re.compile(
    r"(手持|握着|拿着|扛着|背着|拄着|带着|挥舞|抡起)[^，；。、,\s]{0,16}"
)


def coerce_gender(value: Any) -> Literal["male", "female", "other"]:
    key = str(value or "").strip().lower()
    # keep CJK keys as-is for alias lookup
    raw = str(value or "").strip()
    if raw in _GENDER_ALIASES:
        return _GENDER_ALIASES[raw]
    if key in _GENDER_ALIASES:
        return _GENDER_ALIASES[key]
    if "女" in raw:
        return "female"
    if "男" in raw:
        return "male"
    return "other"


_KIND_ALIASES: dict[str, str] = {
    "hook": "hook",
    "dialogue": "dialogue",
    "action": "action",
    "reaction": "reaction",
    "insert": "insert",
    "establishing": "establishing",
    "title": "title",
    "crowd": "crowd",
    # LLM 常见中文/口语别名
    "钩子": "hook",
    "对白": "dialogue",
    "对话": "dialogue",
    "台词": "dialogue",
    "动作": "action",
    "反应": "reaction",
    "特写": "insert",
    "道具": "insert",
    "空镜": "establishing",
    "场景": "establishing",
    "定场": "establishing",
    "标题": "title",
    "字幕": "title",
    "人群": "crowd",
    "群像": "crowd",
}


def coerce_kind(value: Any) -> ShotKind:
    """把 LLM 常见的中文/口语 kind 归一为合法 ShotKind。"""
    raw = str(value or "").strip()
    key = raw.lower()
    if key in _KIND_ALIASES:
        return cast(ShotKind, _KIND_ALIASES[key])
    if raw in _KIND_ALIASES:
        return cast(ShotKind, _KIND_ALIASES[raw])
    return "establishing"


def coerce_palette(value: Any) -> list[str]:
    if isinstance(value, list):
        items = [str(x).strip() for x in value if str(x).strip()]
        return items[:5]
    text = str(value or "").strip()
    if not text:
        return []
    parts = re.split(r"[,，、/;；|+\n]+", text)
    items = [p.strip() for p in parts if p.strip()]
    if len(items) <= 1 and len(text) > 24:
        # 整句色板：截成短片段，避免整段塞进单元素超长
        items = [text[:40]]
    return items[:5]


def sanitize_look_full(value: str) -> str:
    """去掉 look_full 里的手持道具措辞，避免 LLM 脏输出阻断整包校验。"""
    original = str(value or "").strip()
    if not original:
        return original
    s = _HANDHELD_LOOK_RE.sub("", original)
    for bad in ("手持", "握着锄", "拿着刀", "扛着"):
        s = s.replace(bad, "")
    s = re.sub(r"[，、；]{2,}", "，", s)
    s = re.sub(r"^[\s，、；]+|[\s，、；]+$", "", s)
    cleaned = s.strip("，、； ")
    if len(cleaned) >= 20:
        return cleaned
    # 剥离后过短：补一句中性定妆锚点，仍禁止把道具措辞留回
    padded = (cleaned or "正面全身定妆") + "，站姿自然，浅色纯底，五官服装可辨"
    return padded[:400]


_DIALOGUE_FIELDS = ("speaker", "text", "emotion")
_DIALOGUE_TEXT_ALIASES = ("line", "台词", "字幕", "对白", "content")


def _coerce_dialogue_line(item: dict[str, Any]) -> dict[str, Any]:
    """dialogue[] 只保留 schema 字段，并吸收 line/字幕 等别名到 text。"""
    out = {k: item[k] for k in _DIALOGUE_FIELDS if k in item}
    if "text" not in out:
        for alias in _DIALOGUE_TEXT_ALIASES:
            if alias in item:
                out["text"] = item[alias]
                break
    return out


def normalize_series_pack_payload(data: dict[str, Any]) -> dict[str, Any]:
    """加载前纠偏 LLM 常见脏字段（gender/palette/look_full 及 kind/dialogue 字段名）。"""
    out = dict(data)
    style = out.get("style")
    if isinstance(style, dict):
        style = dict(style)
        if "palette" in style:
            style["palette"] = coerce_palette(style.get("palette"))
        out["style"] = style
    cast = out.get("cast")
    if isinstance(cast, list):
        rows = []
        for row in cast:
            if not isinstance(row, dict):
                rows.append(row)
                continue
            item = dict(row)
            if "gender" in item:
                item["gender"] = coerce_gender(item.get("gender"))
            if item.get("look_full"):
                item["look_full"] = sanitize_look_full(str(item["look_full"]))
            rows.append(item)
        out["cast"] = rows
    episodes = out.get("episodes")
    if isinstance(episodes, list):
        eps = []
        for ep in episodes:
            if not isinstance(ep, dict):
                eps.append(ep)
                continue
            ep_item = dict(ep)
            shots = ep_item.get("shots")
            if isinstance(shots, list):
                fixed_shots = []
                for shot in shots:
                    if not isinstance(shot, dict):
                        fixed_shots.append(shot)
                        continue
                    s = dict(shot)
                    if "kind" in s:
                        s["kind"] = coerce_kind(s.get("kind"))
                    dlg = s.get("dialogue")
                    if isinstance(dlg, list):
                        s["dialogue"] = [
                            _coerce_dialogue_line(x) if isinstance(x, dict) else x
                            for x in dlg
                        ]
                    fixed_shots.append(s)
                ep_item["shots"] = fixed_shots
            eps.append(ep_item)
        out["episodes"] = eps
    return out


class PackModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SeriesMeta(PackModel):
    title: str = Field(..., min_length=1, max_length=64)
    logline: str = ""
    aspect: Literal["9:16"] = "9:16"
    seconds_per_episode: int = Field(60, ge=15, le=180)
    language: str = "zh-CN"


class SeriesStyle(PackModel):
    """全片唯一视觉/声音总风格——下游只许原样粘贴。"""

    visual: str = Field(
        ...,
        min_length=8,
        max_length=200,
        description="全片画风一句，如：二次元赛璐璐竖屏短剧，清晰线稿，非写实",
    )
    palette: list[str] = Field(default_factory=list, max_length=5)
    camera_default: str = "中近景为主，少航拍"
    audio_default: AudioMode = "native"
    bgm_mood: str = ""
    bgm_instruments: str = ""

    @field_validator("palette", mode="before")
    @classmethod
    def _palette_list(cls, v: Any) -> list[str]:
        return coerce_palette(v)


class CastMember(PackModel):
    id: str = Field(..., pattern=r"^[a-z][a-z0-9_]{0,31}$")
    name: str = Field(..., min_length=1, max_length=16)
    gender: Literal["male", "female", "other"] = "other"
    age_band: str = Field("", max_length=32, description="如 18-22")
    look_full: str = Field(
        ...,
        min_length=20,
        max_length=400,
        description="正面全身定妆一整句，可直接喂 Seedream",
    )
    look_face: str = Field(
        ...,
        min_length=8,
        max_length=200,
        description="正脸锚点一整句（瞳色/眉/痣等）",
    )
    voice: str = Field(
        ...,
        min_length=8,
        max_length=200,
        description="性别+年龄+音域+语速+情绪(+方言)",
    )
    voice_id: str = ""
    trait: str = ""
    catchphrase: str = ""

    @field_validator("gender", mode="before")
    @classmethod
    def _gender_en(cls, v: Any) -> str:
        return coerce_gender(v)

    @field_validator("look_full", mode="before")
    @classmethod
    def _strip_handheld_props(cls, v: Any) -> str:
        return sanitize_look_full(str(v or ""))


class LocationSpec(PackModel):
    id: str = Field(..., pattern=r"^[a-z][a-z0-9_]{0,31}$")
    name: str = Field(..., min_length=1, max_length=32)
    plate: str = Field(
        ...,
        min_length=20,
        max_length=500,
        description="无人物竖屏空镜一整句，须含视频静帧用途",
    )
    light: str = Field(..., min_length=4, max_length=120)
    anchors: list[str] = Field(..., min_length=1, max_length=3)
    layout: str = Field("", max_length=200, description="前/中/后景")

    @field_validator("plate")
    @classmethod
    def _plate_must_be_empty(cls, v: str) -> str:
        if "有人" in v or "人物站" in v or "一名" in v or "一位" in v:
            raise ValueError("plate 必须是无人物空镜")
        if "静帧" not in v and "空镜" not in v:
            raise ValueError("plate 须标明空镜或视频静帧用途")
        return v


class PropSpec(PackModel):
    id: str = Field(..., pattern=r"^[a-z][a-z0-9_]{0,31}$")
    name: str = Field(..., min_length=1, max_length=32)
    look: str = Field(..., min_length=8, max_length=300)
    role: str = ""


class DialogueLine(PackModel):
    speaker: str = Field(..., description="cast.id")
    text: str = Field(..., min_length=1, max_length=120)
    emotion: str = ""


class ShotSpec(PackModel):
    n: int = Field(..., ge=1, le=40)
    t_in: float = Field(..., ge=0)
    t_out: float = Field(..., gt=0)
    kind: ShotKind = "dialogue"
    cast: list[str] = Field(default_factory=list)
    location: str = Field(..., min_length=1)
    props: list[str] = Field(default_factory=list)
    shot_size: ShotSize
    camera: CameraMove
    still: str = Field(
        ...,
        min_length=8,
        max_length=400,
        description="冻结静帧：只喂 Seedream，禁止过程词",
    )
    motion: str = Field(
        "",
        max_length=400,
        description="相对 still 的动作时序：只喂 Seedance；L0 静镜可空",
    )
    dialogue: list[DialogueLine] = Field(default_factory=list)
    vo: str = ""
    sfx: str = ""
    audio_mode: AudioMode | None = None

    @field_validator("still")
    @classmethod
    def _still_no_process(cls, v: str) -> str:
        for bad in STILL_PROCESS_FORBIDDEN:
            if bad in v:
                raise ValueError(f"still 禁止过程/剪辑词「{bad}」，过程写入 motion")
        return v

    @model_validator(mode="after")
    def _timing_and_motion(self) -> ShotSpec:
        if self.t_out <= self.t_in:
            raise ValueError("t_out 必须大于 t_in")
        if self.kind == "establishing":
            raise ValueError("禁止 establishing/空镜（每镜必须有主体动作，全部走 I2V）")
        if not str(self.motion or "").strip():
            raise ValueError(f"{self.kind} 镜必须填写 motion（全部走 I2V，禁止静止空镜）")
        for line in self.dialogue:
            if line.speaker not in self.cast:
                raise ValueError(f"dialogue.speaker={line.speaker} 不在本镜 cast 中")
        return self


class EpisodePack(PackModel):
    n: int = Field(..., ge=1, le=50)
    title: str = ""
    seconds: int | None = None
    beat: str = Field("", description="叙事节拍摘要，给人看")
    shots: list[ShotSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _shot_numbers(self) -> EpisodePack:
        nums = [s.n for s in self.shots]
        if nums and sorted(nums) != list(range(1, len(nums) + 1)):
            raise ValueError("shots.n 必须从 1 连续编号")
        return self


class SeriesPack(PackModel):
    """完整剧包：系列风格 + 资产规格 + 分集分镜。"""

    schema_version: str = SCHEMA_VERSION
    meta: SeriesMeta
    style: SeriesStyle
    cast: list[CastMember] = Field(..., min_length=1, max_length=12)
    locations: list[LocationSpec] = Field(..., min_length=1, max_length=8)
    props: list[PropSpec] = Field(default_factory=list, max_length=12)
    relationships: list[str] = Field(
        default_factory=list,
        description="如：linwan → yugong：孙女",
    )
    episodes: list[EpisodePack] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_ids_and_refs(self) -> SeriesPack:
        cast_ids = [c.id for c in self.cast]
        loc_ids = [x.id for x in self.locations]
        prop_ids = [p.id for p in self.props]
        if len(cast_ids) != len(set(cast_ids)):
            raise ValueError("cast.id 必须唯一")
        if len(loc_ids) != len(set(loc_ids)):
            raise ValueError("locations.id 必须唯一")
        if len(prop_ids) != len(set(prop_ids)):
            raise ValueError("props.id 必须唯一")
        names = [c.name for c in self.cast]
        if len(names) != len(set(names)):
            raise ValueError("cast.name 必须唯一")

        cast_set, loc_set, prop_set = set(cast_ids), set(loc_ids), set(prop_ids)
        for ep in self.episodes:
            locs_in_ep = {s.location for s in ep.shots}
            if len(locs_in_ep) > 3:
                raise ValueError(f"第{ep.n}集场景超过 3 个：{sorted(locs_in_ep)}")
            props_in_ep = {p for s in ep.shots for p in s.props}
            if len(props_in_ep) > 4:
                raise ValueError(f"第{ep.n}集道具超过 4 个：{sorted(props_in_ep)}")
            for shot in ep.shots:
                if shot.location not in loc_set:
                    raise ValueError(f"Shot {shot.n} location 未知：{shot.location}")
                for cid in shot.cast:
                    if cid not in cast_set:
                        raise ValueError(f"Shot {shot.n} cast 未知：{cid}")
                for pid in shot.props:
                    if pid not in prop_set:
                        raise ValueError(f"Shot {shot.n} props 未知：{pid}")
        return self


def series_pack_json_schema() -> dict[str, Any]:
    """导出 JSON Schema（供文档 / 外部校验）。"""
    return SeriesPack.model_json_schema()


def loads_series_pack(data: dict[str, Any] | str | bytes) -> SeriesPack:
    if isinstance(data, (str, bytes)):
        data = json.loads(data)
    if not isinstance(data, dict):
        raise TypeError("SeriesPack 须为 JSON 对象")
    return SeriesPack.model_validate(normalize_series_pack_payload(data))


def load_series_pack_file(path: str | Path) -> SeriesPack:
    raw = Path(path).read_text(encoding="utf-8")
    return loads_series_pack(raw)


def dump_series_pack(pack: SeriesPack, *, indent: int = 2) -> str:
    return pack.model_dump_json(indent=indent, exclude_none=True)


def write_json_schema_file(dest: str | Path) -> Path:
    path = Path(dest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(series_pack_json_schema(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path
