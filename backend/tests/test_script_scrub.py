"""Tests for scrubbing LLM prose out of episode script markdown."""

from __future__ import annotations

from tools.drama_script import format_episode_markdown, scrub_script_markdown


def test_scrub_strips_preamble_and_postamble():
    raw = """好的，我已经按你的要求修改了剧本：

# 嫦娥奔月
- 时长: 30s
- 钩子: 月宫异象
- 悬念: 玉兔失踪

## 分镜
### Shot 1 (0-3s)
- 画面: 嫦娥立于月宫门口
- 字幕: 嫦娥: 今夜不对劲
- 旁白:
- 角色: 嫦娥

### Shot 2 (3-8s)
- 画面: 玉兔慌张跑来
- 字幕: 玉兔: 姐姐快看
- 角色: 嫦娥、玉兔

希望这个版本更符合你的预期！如需继续调整请告诉我。
"""
    cleaned = scrub_script_markdown(raw)
    assert cleaned.lstrip().startswith("# 嫦娥奔月")
    assert "好的，我已经" not in cleaned
    assert "希望这个版本" not in cleaned
    assert "### Shot 1" in cleaned
    assert "### Shot 2" in cleaned
    assert "- 画面: 嫦娥立于月宫门口" in cleaned


def test_scrub_strips_markdown_fence():
    raw = """```markdown
# 标题
- 时长: 15s
- 钩子: 开场

## 分镜
### Shot 1 (0-5s)
- 画面: 夜色
- 字幕: 旁白: 很久以前
- 角色:
```

主要改动：
1. 缩短了时长
2. 强化了钩子
"""
    cleaned = scrub_script_markdown(raw)
    assert cleaned.lstrip().startswith("# 标题")
    assert "```" not in cleaned
    assert "主要改动" not in cleaned
    assert "强化了钩子" not in cleaned


def test_format_episode_markdown_compact():
    md = format_episode_markdown(
        {
            "title": "测试",
            "meta": {"时长": "12s", "钩子": "钩", "悬念": "悬"},
            "shots": [
                {
                    "n": 1,
                    "timing": "0-4s",
                    "画面": "A",
                    "字幕": "B",
                    "旁白": "",
                    "角色": "C",
                }
            ],
        }
    )
    assert md == (
        "# 测试\n"
        "- 时长: 12s\n"
        "- 钩子: 钩\n"
        "- 悬念: 悬\n"
        "\n"
        "## 分镜\n"
        "### Shot 1 (0-4s)\n"
        "- 画面: A\n"
        "- 字幕: B\n"
        "- 角色: C\n"
    )
