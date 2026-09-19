"""Two-phase SeriesPack generation + semantic validator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.drama_series_pack import load_series_pack_file, loads_series_pack
from tools.drama_series_pack_gen import (
    extract_json_payload,
    generate_series_pack_from_premise,
    merge_series_pack,
)
from tools.drama_series_pack_validate import (
    assert_series_pack_valid,
    validate_series_pack,
)

EXAMPLE = Path(__file__).resolve().parents[1] / "src" / "data" / "series_pack.example.json"


def test_example_passes_semantic_validator():
    pack = load_series_pack_file(EXAMPLE)
    issues = validate_series_pack(pack)
    errors = [i for i in issues if i.level == "error"]
    assert errors == []


def test_motion_new_cast_is_warning_with_path():
    raw = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    # shot 1 cast is only linwan; inject 守卫 into motion
    raw["episodes"][0]["shots"][0]["motion"] = "林晚抬眼，守卫冲入画面"
    pack = loads_series_pack(raw)
    issues = validate_series_pack(pack)
    hits = [i for i in issues if i.code == "motion_new_cast"]
    assert hits
    assert all(i.level == "warning" for i in hits)
    assert hits[0].path == "episodes[1].shots[1].motion"


def test_merge_does_not_block_on_motion_new_cast():
    example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    assets = {k: example[k] for k in ("meta", "style", "cast", "locations", "props", "relationships")}
    episodes = json.loads(json.dumps(example["episodes"]))
    episodes[0]["shots"][0]["motion"] = "林晚抬眼，守卫冲入画面"
    pack = merge_series_pack(assets, episodes)  # warning 不阻断
    assert pack.episodes[0].shots[0].motion == "林晚抬眼，守卫冲入画面"


def test_merge_error_includes_path():
    example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    assets = {k: example[k] for k in ("meta", "style", "cast", "locations", "props", "relationships")}
    assets["cast"][1]["look_full"] = (
        "三十岁男子，瓜子脸，墨黑长直发披肩，白底朱红滚边长袍，正面全身站立，浅色纯底"
    )
    episodes = json.loads(json.dumps(example["episodes"]))
    with pytest.raises(ValueError) as ei:
        merge_series_pack(assets, episodes)
    msg = str(ei.value)
    assert "look_collision" in msg
    assert "cast." in msg


def test_look_collision_detected():
    raw = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    raw["cast"][1]["look_full"] = (
        "三十岁男子，瓜子脸，墨黑长直发披肩，白底朱红滚边长袍，正面全身站立，浅色纯底"
    )
    pack = loads_series_pack(raw)
    issues = validate_series_pack(pack)
    assert any(i.code == "look_collision" for i in issues)


def test_extract_json_from_fence():
    text = '说明如下\n```json\n{"a": 1}\n```\n'
    assert extract_json_payload(text) == {"a": 1}


def test_two_phase_generation_with_mock_draft(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    assets = {
        k: example[k]
        for k in ("schema_version", "meta", "style", "cast", "locations", "props", "relationships")
    }
    episodes = example["episodes"]

    calls: list[str] = []

    def fake_draft(slug: str, prompt: str, *, system: str = "") -> str:
        calls.append(system[:24])
        if "不要写分镜" in system:
            return json.dumps(assets, ensure_ascii=False)
        return json.dumps(episodes, ensure_ascii=False)

    from tools import workspace as ws

    monkeypatch.setattr(ws, "workspace_root", lambda: tmp_path)

    slug = "pack-demo"
    (tmp_path / "dramas" / slug).mkdir(parents=True, exist_ok=True)

    pack = generate_series_pack_from_premise(
        slug,
        "广寒宫侍女月蚀夜盗月核逃亡",
        title="广寒夜奔",
        episode_count=1,
        seconds_per_episode=12,
        draft_fn=fake_draft,
        persist=True,
        max_repairs=0,
    )
    assert pack.meta.title == "广寒夜奔"
    assert len(pack.episodes[0].shots) == 3
    assert len(calls) >= 2
    saved = tmp_path / "dramas" / slug / "series_pack.json"
    assert saved.is_file()
    again = assert_series_pack_valid(saved.read_text(encoding="utf-8"))
    assert again.cast[0].id == "linwan"


def test_merge_rejects_unknown_location():
    example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    assets = {k: example[k] for k in ("meta", "style", "cast", "locations", "props", "relationships")}
    episodes = json.loads(json.dumps(example["episodes"]))
    episodes[0]["shots"][0]["location"] = "missing_loc"
    with pytest.raises(Exception):
        merge_series_pack(assets, episodes)


def test_extract_json_error_reports_context_and_reason():
    with pytest.raises(ValueError) as ei:
        extract_json_payload("抱歉，我无法生成分镜。", phase="phase2")
    msg = str(ei.value)
    assert "无法从 LLM 回复解析 JSON" in msg
    assert "Phase2 分镜数组" in msg
    assert "未见 JSON 结构" in msg
    assert "chars=" in msg
    assert "头: " in msg
    assert "尾: " in msg


def test_extract_json_error_flags_truncation():
    # 没有任何闭合括号的截断 → 直接/回退都无法解析，必须报“疑似截断”
    raw = '[{"n":1,"shots":[{"n":1,"still":"愚公拄拐立于山前'
    with pytest.raises(ValueError) as ei:
        extract_json_payload(raw, phase="phase2")
    assert "疑似被 max_tokens 截断" in str(ei.value)


def test_extract_json_failure_dumps_raw(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from tools import workspace as ws

    monkeypatch.setattr(ws, "workspace_root", lambda: tmp_path)
    raw = '[{"n":1,"shots":[{"n":1,"still":"愚公拄拐立于山前'
    with pytest.raises(ValueError) as ei:
        extract_json_payload(raw, phase="phase2", slug="dump-demo")
    msg = str(ei.value)
    assert "dramas/dump-demo/logs/series_pack_phase2_last.txt" in msg
    dumped = tmp_path / "dramas" / "dump-demo" / "logs" / "series_pack_phase2_last.txt"
    assert dumped.is_file()
    text = dumped.read_text(encoding="utf-8")
    assert raw in text
    assert "chars=" in text


def test_dump_raw_failure_is_best_effort(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from tools import workspace as ws

    monkeypatch.setattr(ws, "workspace_root", lambda: tmp_path)
    # 非法 slug 使 resolve_safe 抛错 → 落盘失败仅告警，不得掩盖原始解析错误
    with pytest.raises(ValueError) as ei:
        extract_json_payload("no json here", phase="phase2", slug="../..")
    msg = str(ei.value)
    assert "无法从 LLM 回复解析 JSON" in msg
    assert "raw=(落盘失败)" in msg
