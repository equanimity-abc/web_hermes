"""Phase C motion / lip hard floors for studio profile."""

from __future__ import annotations

from typing import Any

from tools.drama_models import LADDER_RANK, effective_motion_ladder, infer_kind, normalize_ladder

# Minimum planned ladder for narrative kinds (Phase C).
KIND_FLOOR: dict[str, str] = {
    "dialogue": "L1",
    "reaction": "L1",
    "action": "L3",
}


def motion_floor_for_kind(kind: str) -> str | None:
    return KIND_FLOOR.get(str(kind or "").strip().lower())


def assert_motion_floor(shot: dict[str, Any], *, slug: str = "", models: dict[str, Any] | None = None) -> str:
    """Raise if planned ladder is below the professional floor for this kind."""
    kind = infer_kind(shot)
    floor = motion_floor_for_kind(kind)
    planned = effective_motion_ladder(shot, slug=slug or None, models=models)
    if not floor:
        return planned
    if LADDER_RANK.get(planned, 0) < LADDER_RANK.get(floor, 0):
        raise RuntimeError(
            f"Shot {shot.get('n')} kind={kind} 计划运动 {planned} 低于专业档下限 {floor}"
        )
    return planned


def studio_i2v_fallback(planned: str) -> str:
    """Same-tier fallback for Seedance/Kling failure — never silent L0."""
    planned = normalize_ladder(planned) or "L1"
    if planned in ("L0",):
        return "L0"
    if planned in ("L3", "L4"):
        return planned  # retry same tier; caller may try alt provider
    return "L1"


def lse_hard_gate_defaults() -> dict[str, float]:
    """Studio LSE thresholds (proxy correlation)."""
    return {"lse_c_min": 0.15, "lse_d_max": 0.9}
