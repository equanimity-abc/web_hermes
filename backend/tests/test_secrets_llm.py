"""Secrets overlay + multi-provider LLM endpoint resolution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from config import config
from llm_client import default_llm_provider, llm_endpoint, script_provider_chain
from secrets_store import apply_secrets_to_config, load_secrets_file, public_secrets_status, save_secrets
from tools.providers.registry import has, load_all


@pytest.fixture()
def secrets_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "secrets.json"
    monkeypatch.setattr("secrets_store.SECRETS_PATH", path)
    # Isolate live keys so chain tests are deterministic.
    for key in ("DEEPSEEK_API_KEY", "KIMI_API_KEY", "ARK_API_KEY", "DASHSCOPE_API_KEY"):
        monkeypatch.setattr(config, key, "")
        monkeypatch.delenv(key, raising=False)
    return path


def test_save_secrets_masks_and_applies(secrets_tmp: Path):
    status = save_secrets({"KIMI_API_KEY": "sk-kimi-test-abcdef", "ARK_API_KEY": "ark-key-12345678"})
    assert secrets_tmp.is_file()
    raw = json.loads(secrets_tmp.read_text(encoding="utf-8"))
    assert raw["KIMI_API_KEY"].startswith("sk-kimi")
    assert config.KIMI_API_KEY.startswith("sk-kimi")
    assert config.ARK_API_KEY.startswith("ark-key")

    keys = {row["key"]: row for row in status["keys"]}
    assert keys["KIMI_API_KEY"]["configured"] is True
    assert keys["KIMI_API_KEY"]["source"] == "secrets"
    assert "…" in keys["KIMI_API_KEY"]["masked"]
    assert keys["KIMI_API_KEY"]["masked"] != raw["KIMI_API_KEY"]
    assert status["script_alternatives"][0]["model"]
    assert "doubao-seedream" in (status["providers"]["ark"]["image_model"] or "")


def test_script_provider_chain_interchangeable(secrets_tmp: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "ds-key")
    monkeypatch.setattr(config, "KIMI_API_KEY", "km-key")
    monkeypatch.setattr(config, "ARK_API_KEY", "")
    monkeypatch.setattr(config, "DEEPSEEK_MODEL", "deepseek-v4-pro")
    monkeypatch.setattr(config, "KIMI_MODEL", "kimi-k3")

    chain = script_provider_chain("deepseek")
    assert [c["provider"] for c in chain] == ["deepseek", "kimi"]
    assert chain[0]["model"] == "deepseek-v4-pro"
    assert chain[1]["model"] == "kimi-k3"

    chain_k = script_provider_chain("kimi")
    assert [c["provider"] for c in chain_k] == ["kimi", "deepseek"]


def test_script_chain_skips_missing_key(secrets_tmp: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "KIMI_API_KEY", "only-kimi")
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "")
    monkeypatch.setattr(config, "ARK_API_KEY", "")
    chain = script_provider_chain("deepseek")
    assert len(chain) == 1
    assert chain[0]["provider"] == "kimi"
    assert default_llm_provider() == "kimi"


def test_script_chain_prefers_ark(secrets_tmp: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "ARK_API_KEY", "ark-key")
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "ds-key")
    monkeypatch.setattr(config, "KIMI_API_KEY", "")
    chain = script_provider_chain("ark", ["ark", "deepseek", "kimi"])
    assert chain[0]["provider"] == "ark"
    assert chain[0]["model"] == "doubao-seed-character-260628"
    assert default_llm_provider() == "ark"



def test_ark_endpoint_models(secrets_tmp: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "ARK_API_KEY", "ark")
    ep = llm_endpoint("ark")
    assert ep["provider"] == "ark"
    assert "ark.cn-beijing" in ep["base_url"]
    assert ep["model"] == "doubao-seed-character-260628"
    assert ep["chat_path"] == "/chat/completions"


def test_ark_providers_register():
    load_all()
    assert has("image", "seedream")
    assert has("i2v", "seedance")
    assert has("tts", "seed-audio")
    assert has("image", "ark")


def test_ark_preset_honest():
    from tools.drama_config import load_preset
    from tools.drama_models import normalize_models, provider_health

    preset = load_preset("ark")
    models = normalize_models({**preset.get("models", {}), "preset": "ark"})
    health = provider_health(models)
    statuses = {it["status"] for it in health["items"]}
    assert not (statuses - {"live", "idle", "gated", "missing"})


def test_clear_secret_removes_file_entry(secrets_tmp: Path):
    save_secrets({"DEEPSEEK_API_KEY": "ds-abc-123456"})
    assert "DEEPSEEK_API_KEY" in load_secrets_file()
    save_secrets({"DEEPSEEK_API_KEY": ""})
    assert "DEEPSEEK_API_KEY" not in load_secrets_file()
    apply_secrets_to_config({})
    status = public_secrets_status()
    row = next(r for r in status["keys"] if r["key"] == "DEEPSEEK_API_KEY")
    assert row["source"] in ("empty", "env")
