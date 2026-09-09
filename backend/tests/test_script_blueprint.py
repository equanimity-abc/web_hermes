"""Tests for rich structured episode script blueprint."""

from __future__ import annotations

from tools.drama_script import format_episode_markdown, scrub_script_markdown
from tools.drama_script_blueprint import (
    build_episode_script_system,
    parse_asset_sections,
)
from tools.drama_video import parse_episode_markdown

SAMPLE = """# EP01 月下重逢
- 时长: 30s
- 钩子: 嫦娥看见后羿的影子
- 悬念: 玉兔灯突然碎裂
- 配乐: 古风空灵，笛声为主，开场低沉、中段紧张、结尾留白

## 角色设定
### 嫦娥
- 外形: 白衣仙女，黑色长发，清冷眉眼
- 性格: 隐忍而决绝
- 音色倾向: 女声温柔
- 口头禅: 别再来了

### 后羿
- 外形: 青铜甲战将，短发，伤疤过眉
- 性格: 执拗
- 音色倾向: 男声低沉

## 场景设定
### 月宫冷殿
- 描述: 白玉廊柱与冷青石地
- 光影色调: 冷蓝侧光
- 标志物: 玉阶、窗格月光

## 道具设定
### 玉兔灯
- 描述: 乳白白瓷兔形灯
- 材质外形: 半透明瓷，暖黄内光
- 剧情作用: 维系两人记忆的信物

## 分镜
### Shot 1 (0-3s)
- 画面: 月宫冷殿全景，嫦娥背对窗站立
- 地点: 月宫冷殿
- 道具: 玉兔灯
- 字幕: 嫦娥：别再来了
- 旁白: 月升之时，旧人未散
- 角色: 嫦娥

### Shot 2 (3-8s)
- 画面: 后羿剪影立于玉阶外
- 地点: 月宫冷殿
- 道具:
- 字幕: 后羿：我只想看你一眼
- 旁白:
- 角色: 后羿、嫦娥
"""


def test_parse_asset_sections_and_meta():
    parsed = parse_episode_markdown(SAMPLE)
    assert parsed["title"].startswith("EP01")
    assert "空灵" in parsed["meta"]["配乐"]
    assert len(parsed["cast"]) == 2
    assert parsed["cast"][0]["name"] == "嫦娥"
    assert "白衣" in parsed["cast"][0]["外形"]
    assert parsed["locations"][0]["name"] == "月宫冷殿"
    assert parsed["props"][0]["name"] == "玉兔灯"
    assert len(parsed["shots"]) == 2
    assert parsed["shots"][0]["地点"] == "月宫冷殿"
    assert "玉兔灯" in str(parsed["shots"][0]["道具"])


def test_format_roundtrip_keeps_blueprint():
    parsed = parse_episode_markdown(SAMPLE)
    rebuilt = format_episode_markdown(parsed)
    again = parse_episode_markdown(rebuilt)
    assert again["meta"]["配乐"] == parsed["meta"]["配乐"]
    assert [c["name"] for c in again["cast"]] == ["嫦娥", "后羿"]
    assert again["locations"][0]["name"] == "月宫冷殿"
    assert again["props"][0]["name"] == "玉兔灯"
    assert len(again["shots"]) == 2


def test_scrub_keeps_structured_body():
    noisy = "好的，这是改写后的剧本：\n\n" + SAMPLE + "\n\n主要改动：加强了悬念。"
    cleaned = scrub_script_markdown(noisy)
    assert cleaned.lstrip().startswith("#")
    assert "主要改动" not in cleaned
    parsed = parse_episode_markdown(cleaned)
    assert parsed["cast"]
    assert parsed["meta"].get("配乐")


def test_parse_asset_sections_standalone():
    assets = parse_asset_sections(SAMPLE)
    assert len(assets["cast"]) == 2
    assert assets["locations"][0]["光影色调"]
    assert assets["props"][0]["剧情作用"]


def test_build_episode_script_system_mentions_sections():
    system = build_episode_script_system(
        title_line="# 标题",
        ep_sec=60,
        shot_lo=8,
        shot_hi=14,
        series_rule="单集；",
    )
    assert "## 角色设定" in system
    assert "## 场景设定" in system
    assert "## 道具设定" in system
    assert "配乐:" in system
    assert "无人物竖屏主底板" in system
    assert "逐字一致" in system or "逐字" in system
    assert "禁止每镜发明新背景" in system or "另起炉灶" in system


def test_build_episode_user_prompt_stresses_shootable_env():
    from tools.drama_script_blueprint import build_episode_user_prompt

    prompt = build_episode_user_prompt(
        "嫦娥与后羿重逢",
        user_series="请编写单集剧本，目标时长 30 秒。",
        bible="## 主要场景\n- 月宫冷殿",
    )
    assert "主底板" in prompt
    assert "设定图" in prompt
    assert "逐字同名" in prompt
