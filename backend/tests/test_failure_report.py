"""HQ failure report: episode → step → detail → reason + preview media."""

from __future__ import annotations

from tools.drama_failure_report import (
    classify_failure_locus,
    classify_failure_side,
    format_hq_failures_for_ui,
    side_label_zh,
)


def test_classify_output_vs_input_vs_peer():
    assert (
        classify_failure_side("HTTP 400: OutputVideoSensitiveContentDetected")
        == "output"
    )
    assert (
        classify_failure_side(
            "InputImageSensitiveContentDetected.PrivacyInformation: real person"
        )
        == "input"
    )
    assert (
        classify_failure_side("cancelled:因其它镜头失败，加速收尾（本镜未继续昂贵步骤）")
        == "peer"
    )


def test_classify_locus_flicker_uses_pipeline_steps():
    locus = classify_failure_locus(
        "第1镜闪烁验收未通过（闪烁 SSIM 0.8061 < 0.84，请重做运动（不重配音）），禁止自动重试"
    )
    assert locus["step"] == "视频"
    assert locus["detail"] == "画面抖动检测"
    assert "相邻帧相似度" in locus["reason"]
    assert "0.8061" in locus["reason"]
    assert "SSIM" not in locus["reason"]
    assert "禁止自动重试" not in locus["reason"]


def test_format_hq_failures_structured(monkeypatch):
    monkeypatch.setattr(
        "tools.drama_failure_report.write_seedance_verify_payload",
        lambda *a, **k: {
            "ok": True,
            "shot": 2,
            "payload_path": "D:/tmp/shot02.json",
            "curl_submit_ps": 'curl.exe -sS "https://example/tasks" -d @shot02.json',
            "curl_poll_ps": 'curl.exe -sS "https://example/tasks/TASK_ID"',
            "curl_submit": "curl ...",
            "curl_poll": "curl poll...",
        },
    )
    monkeypatch.setattr(
        "tools.drama_failure_report.collect_shot_failure_media",
        lambda *a, **k: [
            {
                "type": "video",
                "url": "/api/workspace/file?path=dramas/45-1/x.mp4",
                "title": "Shot 2 · 失败视频（运动）",
            }
        ],
    )
    text = format_hq_failures_for_ui(
        [
            {
                "shot": 2,
                "error": "Shot 2 需要真 I2V；OutputVideoSensitiveContentDetected Request id: 021789",
            },
            {
                "shot": 3,
                "error": "cancelled:因其它镜头失败，加速收尾（本镜未继续昂贵步骤）",
            },
        ],
        slug="45-1",
        episode=1,
    )
    assert "第1集 · Shot 2" in text
    assert "步骤：视频" in text
    assert "细分：输出侧内容安全" in text
    assert "原因：" in text
    assert "021789" in text
    assert "预览（" in text
    assert "手验提交：" in text
    assert "下一步" not in text
    assert side_label_zh("output") == "输出侧内容安全"


def test_format_flicker_no_curl_block(monkeypatch):
    called = {"n": 0}

    def _boom(*a, **k):
        called["n"] += 1
        raise AssertionError("flicker must not build seedance curl")

    monkeypatch.setattr("tools.drama_failure_report.write_seedance_verify_payload", _boom)
    monkeypatch.setattr(
        "tools.drama_failure_report.collect_shot_failure_media",
        lambda *a, **k: [
            {
                "type": "video",
                "url": "/api/workspace/file?path=dramas/45-1/motion.mp4",
                "title": "Shot 1 · 失败视频（运动）",
            }
        ],
    )
    text = format_hq_failures_for_ui(
        [
            {
                "shot": 1,
                "error": "第1镜闪烁验收未通过（闪烁 SSIM 0.8061 < 0.84，请重做运动（不重配音）），禁止自动重试",
            }
        ],
        slug="45-1",
        episode=1,
    )
    assert called["n"] == 0
    assert "第1集 · Shot 1" in text
    assert "步骤：视频" in text
    assert "细分：画面抖动检测" in text
    assert "相邻帧相似度" in text
    assert "预览（" in text
    assert "手验" not in text
    assert "下一步" not in text
