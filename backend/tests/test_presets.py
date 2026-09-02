"""S8: preset schema + provider-name honesty self-check."""

from __future__ import annotations

from tools.drama_config import PRESET_IDS, load_preset
from tools.drama_models import NODE_KEYS, normalize_models, provider_health


def test_all_presets_are_loadable():
    for pid in PRESET_IDS:
        preset = load_preset(pid)
        assert preset.get("id") == pid
        assert isinstance(preset.get("models"), dict)


def test_preset_providers_are_name_honest():
    """No preset may claim a commercial backend that is silently aliased/missing.

    health must classify every configured provider as live, idle, or a degrade
    that is *explicit* (gated/missing) — never an undocumented silent alias.
    """
    for pid in PRESET_IDS:
        preset = load_preset(pid)
        models = normalize_models({**preset.get("models", {}), "preset": pid})
        health = provider_health(models)
        statuses = {it["status"] for it in health["items"]}
        # Every entry must resolve to an explicit status.
        assert not (statuses - {"live", "idle", "gated", "missing"}), pid


def test_preset_nodes_are_valid():
    from tools.drama_models import SHOT_KINDS

    for pid in PRESET_IDS:
        preset = load_preset(pid)
        models = preset.get("models", {})
        for node in models:
            assert node in NODE_KEYS or node == "providers", f"{pid}: bad node {node}"
        # image/motion must cover every shot kind.
        for map_name in ("image", "motion"):
            keys = set(models.get(map_name, {}).keys())
            assert set(SHOT_KINDS) <= keys, f"{pid}: {map_name} incomplete"
            extra = keys - set(SHOT_KINDS)
            if map_name == "image":
                assert extra <= {"character_ref"}, f"{pid}: unexpected image keys {extra}"
            else:
                assert not extra, f"{pid}: unexpected motion keys {extra}"
