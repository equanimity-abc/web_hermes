"""Smart resume: classify failures and narrow dirty layers."""

from __future__ import annotations

from tools.drama_resume import (
    advance_from_failure,
    classify_failure,
    diagnose_shot,
    inspect_shot_state,
    prepare_episode_resume,
    refine_plan_for_locks,
    strip_locked_dirty,
)


def test_classify_i2v_sensitive_needs_scene():
    c = classify_failure(
        "Shot 2 需要真 I2V，但得到 none（provider=seedance；HTTP 400: "
        "InputImageSensitiveContentDetected.PrivacyInformation: real person）"
    )
    assert c["stage"] == "scene"
    assert "scene" in c["dirty"]


def test_classify_output_video_sensitive_resumes_motion():
    c = classify_failure(
        "Shot 1 需要真 I2V，但得到 none（provider=seedance；"
        "HTTP 400: OutputVideoSensitiveContentDetected）"
    )
    assert c["stage"] == "i2v"
    assert c["dirty"] == ["motion", "clip"]
    assert c["resume_from"] == "motion"
    assert "scene" not in c["dirty"]


def test_classify_lip_failure():
    c = classify_failure("第1镜专业档口型失败（lip_source=fallback）：pixverse: FAILED")
    assert c["stage"] == "lip"
    assert c["dirty"] == ["lip", "clip"]


def test_diagnose_shot_narrows_to_motion():
    shot = {
        "n": 2,
        "assets": {"scene": "a.png", "voice": "a.mp3", "clip": "a.mp4"},
        "i2v_source": "none",
        "qc": {
            "produce_ok": False,
            "produce_error": "Shot 2 需要真 I2V，但得到 none（provider=seedance）",
        },
        "dirty": ["scene", "overlay", "voice", "motion", "clip"],
    }
    plan = diagnose_shot(shot)
    assert plan is not None
    assert plan["resume_from"] == "motion"
    assert "scene" not in plan["dirty"]
    assert "voice" not in plan["dirty"]


def test_strip_locked_dirty_helper():
    shot = {"locked": ["scene", "motion"]}
    assert strip_locked_dirty(shot, ["scene", "motion", "clip", "lip"]) == ["clip", "lip"]
    assert strip_locked_dirty({"locked": ["shot"]}, ["scene", "voice", "clip"]) == []


def test_refine_plan_sensitive_with_locked_scene():
    shot = {"locked": ["scene"], "assets": {"scene": "s.png"}}
    plan = refine_plan_for_locks(
        shot,
        {
            "stage": "scene",
            "dirty": ["scene", "overlay", "motion", "clip"],
            "resume_from": "scene",
            "hint": "敏感",
        },
    )
    assert "scene" not in plan["dirty"]
    assert plan["resume_from"] == "motion"
    assert "解锁" in str(plan.get("hint") or "")


def test_prepare_episode_resume_writes_narrow_dirty(tmp_path, monkeypatch):
    doc = {
        "shots": [
            {
                "n": 1,
                "字幕": "你好",
                "assets": {"scene": "s.png", "voice": "v.mp3", "clip": "c.mp4"},
                "identity": {"status": "ok", "pass": True, "required": True},
                "i2v_source": "ai",
                "lip_source": "fallback",
                "qc": {
                    "produce_ok": False,
                    "produce_error": "口型失败 pixverse",
                    "produce_stage": "lip",
                },
                "dirty": ["scene", "voice", "motion", "clip"],
            }
        ]
    }
    saved: list = []

    monkeypatch.setattr("tools.drama_shots.load_doc", lambda slug, ep: doc)
    monkeypatch.setattr("tools.drama_shots.find_shot", lambda d, n: next(s for s in d["shots"] if s["n"] == n))
    monkeypatch.setattr(
        "tools.drama_shots.merge_save_shot",
        lambda slug, ep, shot: saved.append(dict(shot)),
    )
    monkeypatch.setattr("tools.drama_audio.load_mix", lambda slug, ep: {})
    monkeypatch.setattr("tools.drama_audio.has_bgm", lambda mix: False)
    monkeypatch.setattr("tools.workspace.resolve_safe", lambda rel: tmp_path / "missing.mp4")

    report = prepare_episode_resume("demo", 1)
    assert report["failed_count"] == 1
    assert saved
    assert saved[0]["dirty"] == ["lip", "clip"]
    assert saved[0]["qc"]["resume_from"] == "lip"
