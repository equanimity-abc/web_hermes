"""SeriesPack 语义校验器（超出 Pydantic 结构约束的规则）。

规则来源：剧本 SSOT 方案
1. shots 引用的 cast/location/props 必须可解析（Pydantic 已覆盖）
2. still 禁止过程词（Pydantic 已覆盖）
3. motion 引入本镜以外角色名 / 其它场景名（warning，仅提示不阻断）
4. dialogue.speaker ∈ shot.cast（Pydantic 已覆盖）
5. 两角色 look_full 主色+发型不得雷同
6. plate 禁止人物（Pydantic 已覆盖）
7. 单集场景>3 或道具>4（Pydantic 已覆盖）
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import ValidationError

from tools.drama_series_pack import (
    STILL_PROCESS_FORBIDDEN,
    SeriesPack,
    loads_series_pack,
)

IssueLevel = Literal["error", "warning"]

# 粗粒度服装/发色关键词，用于 look 撞脸检测与 motion 扩写检测
_COLOR_TOKENS = (
    "朱红",
    "玄色",
    "墨黑",
    "冷白",
    "月白",
    "青白",
    "金色",
    "银色",
    "红色",
    "蓝色",
    "绿色",
    "紫色",
    "白色",
    "黑色",
    "灰色",
    "粉色",
    "橙色",
    "褐色",
    "棕色",
    "青色",
    "黄色",
)
_HAIR_TOKENS = (
    "长直发",
    "短发",
    "披肩",
    "马尾",
    "丸子头",
    "双髻",
    "短茬",
    "寸头",
    "卷发",
    "齐肩",
    "及腰",
    "散发",
    "束发",
    "辫子",
)


@dataclass(frozen=True)
class PackIssue:
    code: str
    message: str
    path: str = ""
    level: IssueLevel = "error"

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "level": self.level,
        }


def _tokens_in(text: str, vocabulary: tuple[str, ...]) -> set[str]:
    raw = str(text or "")
    return {t for t in vocabulary if t in raw}


def _look_signature(look_full: str) -> tuple[frozenset[str], frozenset[str]]:
    return (
        frozenset(_tokens_in(look_full, _COLOR_TOKENS)),
        frozenset(_tokens_in(look_full, _HAIR_TOKENS)),
    )


def validate_series_pack(
    data: SeriesPack | dict[str, Any] | str | bytes,
    *,
    structural: bool = True,
) -> list[PackIssue]:
    """返回全部问题；空列表表示通过。structural=True 时先跑 Pydantic。"""
    issues: list[PackIssue] = []
    pack: SeriesPack | None = None

    if isinstance(data, SeriesPack):
        pack = data
    else:
        try:
            pack = loads_series_pack(data)
        except ValidationError as exc:
            if not structural:
                return [
                    PackIssue(
                        code="schema",
                        message="无法解析为 SeriesPack",
                        path="",
                    )
                ]
            for err in exc.errors():
                loc = ".".join(str(x) for x in err.get("loc") or ())
                issues.append(
                    PackIssue(
                        code="schema",
                        message=str(err.get("msg") or "schema invalid"),
                        path=loc,
                    )
                )
            return issues
        except Exception as exc:
            return [
                PackIssue(
                    code="schema",
                    message=f"无法解析为 SeriesPack：{exc}",
                    path="",
                )
            ]

    assert pack is not None

    # Rule 5: look uniqueness (color ∩ hair)
    for i, a in enumerate(pack.cast):
        sig_a = _look_signature(a.look_full)
        if not sig_a[0] or not sig_a[1]:
            continue
        for b in pack.cast[i + 1 :]:
            sig_b = _look_signature(b.look_full)
            if sig_a[0] & sig_b[0] and sig_a[1] & sig_b[1]:
                issues.append(
                    PackIssue(
                        code="look_collision",
                        message=(
                            f"角色 {a.id}/{b.id} look_full 主色与发型关键词雷同："
                            f"色={sorted(sig_a[0] & sig_b[0])} 发={sorted(sig_a[1] & sig_b[1])}"
                        ),
                        path=f"cast.{a.id}",
                    )
                )

    cast_by_id = {c.id: c for c in pack.cast}
    loc_by_id = {x.id: x for x in pack.locations}
    name_to_cast = {c.name: c.id for c in pack.cast}
    name_to_loc = {x.name: x.id for x in pack.locations}

    for ep in pack.episodes:
        for shot in ep.shots:
            path = f"episodes[{ep.n}].shots[{shot.n}]"
            motion = str(shot.motion or "")
            still = str(shot.still or "")

            # Rule 2 double-check still process words (in case structural skipped)
            for bad in STILL_PROCESS_FORBIDDEN:
                if bad in still:
                    issues.append(
                        PackIssue(
                            code="still_process",
                            message=f"still 含过程词「{bad}」",
                            path=f"{path}.still",
                        )
                    )

            # Rule 3 (warning): motion 引入本镜以外角色/场景名只提示，不阻断成片。
            # 反应镜里「智叟讥讽愚公」这类提法很常见，硬闸会反复打回 LLM 也改不净。
            allowed_cast_names = {
                cast_by_id[cid].name for cid in shot.cast if cid in cast_by_id
            }
            for name, cid in name_to_cast.items():
                if name and name in motion and cid not in shot.cast:
                    issues.append(
                        PackIssue(
                            code="motion_new_cast",
                            message=f"motion 出现本镜以外角色名「{name}」",
                            path=f"{path}.motion",
                            level="warning",
                        )
                    )
            shot_loc = loc_by_id.get(shot.location)
            shot_loc_name = shot_loc.name if shot_loc else ""
            for name, lid in name_to_loc.items():
                if name and name in motion and lid != shot.location:
                    issues.append(
                        PackIssue(
                            code="motion_new_location",
                            message=f"motion 出现其它场景名「{name}」",
                            path=f"{path}.motion",
                            level="warning",
                        )
                    )

            # Clothing rewrite heuristic in motion
            if re.search(r"(换装|改穿|穿上|脱下)", motion):
                for color in _COLOR_TOKENS:
                    if color not in motion:
                        continue
                    allowed_looks = " ".join(
                        cast_by_id[cid].look_full for cid in shot.cast if cid in cast_by_id
                    )
                    if color not in allowed_looks:
                        issues.append(
                            PackIssue(
                                code="motion_new_costume",
                                message=f"motion 引入本镜定妆未声明的色词「{color}」",
                                path=f"{path}.motion",
                                level="warning",
                            )
                        )

            # Soft: still should mention allowed cast names or stay generic
            _ = allowed_cast_names, shot_loc_name

    return issues


def assert_series_pack_valid(
    data: SeriesPack | dict[str, Any] | str | bytes,
    *,
    allow_warnings: bool = True,
) -> SeriesPack:
    """校验通过则返回 SeriesPack；有 error 级问题则抛 ValueError。"""
    if isinstance(data, SeriesPack):
        pack = data
    else:
        pack = loads_series_pack(data)
    issues = validate_series_pack(pack)
    errors = list(issues) if not allow_warnings else [i for i in issues if i.level == "error"]
    if errors:
        detail = "; ".join(f"[{i.code}] {i.message}" for i in errors[:8])
        raise ValueError(f"SeriesPack 校验失败（{len(errors)}）：{detail}")
    return pack
