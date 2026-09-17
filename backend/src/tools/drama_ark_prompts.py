"""火山方舟提示词规范（Seedream / Seedance / Seed Audio）。

依据官方指南提炼的短剧可用写法：
- Seedream：自然语言「主体 + 行为/姿态 + 环境 + 风格光影构图」；视频首帧写明「视频静帧」
- Seedance：公式「主体 + 运动时序 + 环境 + 运镜/景别 + 美学」；图生视频强调与首帧主体一致
- Seedance 自带声：对白写清说话人视觉特征 + 台词；音色描述「性别+年龄+属性+语速+情绪」
- 手动配音 + reference_audio：关模型出声，提示口型跟参考音频

本模块只负责拼装文案；调用方仍走既有 Seedream / Seedance API。
"""

from __future__ import annotations

import re
from typing import Any

# 中文运镜（SeriesPack）直接透传；旧 punch_in 码映射到中文
CAMERA_ZH: dict[str, str] = {
    "punch_in": "镜头缓慢前推至近景",
    "punch_shake": "手持轻微抖动的冲击运镜，节奏紧绷",
    "pan_right": "镜头向右平移跟随主体",
    "pan_left": "镜头向左平移跟随主体",
    "rise": "镜头平稳上摇升起",
    "fall": "镜头平稳下摇俯冲",
    "pull_out": "镜头缓慢拉远至中全景",
}
_CAMERA_ZH_ENUM = frozenset({"推", "拉", "摇", "移", "跟", "升", "降", "环绕", "固定"})

_NO_TEXT = "禁止任何文字、姓名、标签、编号、水印、字幕、界面元素"
_DIALOGUE_RE = re.compile(
    r"(?:^|[\n；;])\s*(?:【[^】]{1,12}】|\[[^\]]{1,12}\])?"
    r"(?P<name>[^:：\s「『“\"]{1,16})"
    r"(?:\s*[（(][^）)]{0,40}[）)])?"
    r"\s*[:：]\s*(?P<line>.+)",
)


def camera_motion_zh(camera: str | None) -> str:
    key = str(camera or "punch_in").strip() or "punch_in"
    if key in _CAMERA_ZH_ENUM:
        return "镜头固定" if key == "固定" else f"镜头{key}"
    return CAMERA_ZH.get(key, "镜头保持稳定，主体运动清晰")


def _join_zh(parts: list[str]) -> str:
    """连贯中文短句，避免英文逗号堆砌。"""
    cleaned: list[str] = []
    for p in parts:
        s = str(p or "").strip().strip("，,。；; ")
        if s:
            cleaned.append(s)
    return "。".join(cleaned) + ("。" if cleaned else "")


def _clean_scene(raw: str) -> str:
    scene = str(raw or "").strip()
    if not scene:
        return ""
    # 去掉与 Seedance 冲突的「切黑/转场」等后期指令
    for bad in ("切黑", "黑场", "淡入淡出", "转场", "叠化", "闪白"):
        scene = scene.replace(bad, "")
    scene = re.sub(r"[，。；;]+$", "", scene.strip())
    return scene


def _dialogue_lines(shot: dict[str, Any]) -> list[tuple[str, str]]:
    raw = str(shot.get("字幕") or shot.get("对白") or "").strip()
    if not raw:
        return []
    out: list[tuple[str, str]] = []
    for chunk in re.split(r"[\n]+", raw):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = _DIALOGUE_RE.search(chunk) or _DIALOGUE_RE.match(chunk)
        if m:
            name = str(m.group("name") or "").strip()
            line = str(m.group("line") or "").strip().strip("「」『』\"“”")
            if line:
                out.append((name, line))
            continue
        # 无说话人前缀：整段当旁白/独白
        line = chunk.strip("「」『』\"“”")
        if line:
            out.append(("", line))
    return out[:4]


def build_seedream_t2i_prompt(
    *,
    subject: str,
    action: str = "",
    environment: str = "",
    aesthetics: str = "",
    use_case: str = "",
    style_guard: str = "",
    extras: list[str] | None = None,
) -> str:
    """Seedream 文生图：主体 + 行为 + 环境 + 美学（官方自然语言公式）。"""
    bits: list[str] = []
    if use_case:
        bits.append(use_case)
    core = "，".join(p for p in (subject, action, environment) if p)
    if core:
        bits.append(core)
    if aesthetics:
        bits.append(aesthetics)
    if style_guard:
        bits.append(style_guard)
    for x in extras or []:
        if x:
            bits.append(str(x).strip())
    bits.append(_NO_TEXT)
    return _join_zh(bits)


def build_seedream_video_still_prompt(
    *,
    title: str,
    scene: str,
    character_clause: str = "",
    location_clause: str = "",
    prop_clause: str = "",
    kinetic: str = "",
    spatial_clause: str = "",
    memory_clause: str = "",
    style_clause: str = "",
    identity_lock: str = "",
    style_guard: str = "",
) -> str:
    """分镜静帧：明确「视频静帧 / Seedance 首帧」，并保持角色/场景锚点。"""
    scene = _clean_scene(scene) or "竖屏短剧中近景人物"
    bits = [
        "竖屏9:16视频静帧画面，可作为 Seedance 图生视频首帧",
        f"剧集「{title}」" if title else "",
        scene,
        location_clause,
        prop_clause,
        character_clause,
        spatial_clause,
        memory_clause,
        kinetic,
        identity_lock,
        style_clause,
        "构图稳定、主体清晰、光影明确，细节丰富但不堆砌空泛形容词",
        f"竖屏漫剧条漫插画，{style_guard}" if style_guard else "竖屏漫剧条漫插画",
        "戏剧性轮廓光，人物清晰可见，非空镜非黑屏",
        _NO_TEXT,
    ]
    return _join_zh([b for b in bits if b])


def build_seedance_i2v_prompt(
    shot: dict[str, Any],
    *,
    look_clause: str = "",
    style_guard: str = "",
    generate_audio: bool = True,
    manual_voice: bool = False,
) -> str:
    """Seedance 图生视频：优先 motion（SeriesPack），否则回退 画面。"""
    motion = str(shot.get("motion") or "").strip()
    scene = _clean_scene(motion or str(shot.get("画面") or ""))
    size = str(shot.get("shot_size") or shot.get("size") or "").strip()
    camera = camera_motion_zh(shot.get("camera"))
    bits: list[str] = [
        "基于首帧参考图生成竖屏9:16短剧镜头",
        "生成视频中的主体必须与首帧参考图中的主体完全一致，五官、发型、服装与体态不变",
    ]
    if look_clause:
        bits.append(f"角色外形锚点：{look_clause}")
    if scene:
        bits.append(f"画面运动：{scene}")
    else:
        bits.append("主体做出与剧情匹配的自然微动作与表情变化")
    if size:
        bits.append(f"景别：{size}")
    bits.append(f"运镜：{camera}")
    if style_guard:
        bits.append(style_guard)
    bits.append("运动流畅自然，幅度适中，禁止闪烁跳切与画外乱入新角色")

    lines = _dialogue_lines(shot)
    if lines and generate_audio and not manual_voice:
        # Seedance 原生音频：写清谁在说什么（用外形指代）
        voice_bits: list[str] = []
        for name, line in lines:
            who = f"画面中的「{name}」" if name else "画面中的角色"
            voice_bits.append(f"{who}开口说：「{line}」")
        bits.append("对白与口型：" + "；".join(voice_bits))
        bits.append("口型与语音节奏精准同步，情绪与表情跟台词一致，不要额外旁白字幕烧录进画面")
    elif lines and manual_voice:
        bits.append("角色按参考音频说话，口型与语音节奏精准同步，自然张合，不要额外旁白字幕")
    else:
        bits.append("本镜以动作与环境声为主，如无对白则不要凭空编造长台词")

    bits.append(_NO_TEXT)
    return _join_zh(bits)


def build_seedance_ref_audio_suffix() -> str:
    return "角色按参考音频说话，口型与语音节奏精准同步，自然张合，不要额外旁白字幕"


def build_character_ref_prompt_zh(
    *,
    look: str,
    gender: str = "",
    style_guard: str = "",
) -> str:
    """角色定妆：单人正面全身，自然语言 + 硬约束。"""
    bits = [
        "一张正方形二次元角色设定图，画面中只有一个动漫角色，仅一个姿势，禁止多个视角",
        "正面全身站立，居中构图，人物从头到脚完整可见，占画面主体",
        f"性别为{gender}" if gender else "",
        f"外形：{look}",
        "双手自然垂放或空闲，禁止手持任何道具、工具、武器、农具、锄头、镐头",
        "禁止出现锄头/工具/场景杂物/第二人/动物抢戏",
        "均匀浅色纯色背景，无分栏、无多格、无线条、无网格",
        "完整上色二次元立绘，不是半身、不是特写",
        style_guard,
        _NO_TEXT,
    ]
    return "，".join(b for b in bits if b)


def build_prop_ref_prompt_zh(
    *,
    look: str,
    colors: str = "",
    square: bool = True,
    style_guard: str = "",
) -> str:
    frame = "正方形道具设定图" if square else "竖屏9:16道具设定图"
    bits = [
        frame,
        f"外形：{look}",
        f"配色：{colors}" if colors else "",
        "纯白满幅背景占满画面，无黑边白边留白",
        "产品展示风格，高清细节，标志性轮廓清晰可复现",
        "禁止人物、禁止场景杂物抢戏",
        style_guard,
        _NO_TEXT,
    ]
    return "，".join(b for b in bits if b)


def build_location_plate_prompt_zh(
    *,
    name: str,
    look: str,
    colors: str = "",
    style_guard: str = "",
) -> str:
    bits = [
        "竖屏9:16空镜场景底板，视频静帧可用作 Seedance 定场首帧",
        f"地点「{name}」",
        f"环境：{look}",
        f"色调：{colors}" if colors else "",
        "无人物、无剪影、无动物、无车辆驾驶者",
        "固定机位可复现构图，建筑轮廓与地面材质清晰",
        "动漫背景插画，色块分明，禁止写实摄影风景照",
        style_guard,
        "满幅构图无黑边",
        _NO_TEXT,
    ]
    return "，".join(b for b in bits if b)


# 剧本「画面」字段写作提示（注入编剧 system prompt）
SHOT_FRAME_WRITING_RULE = (
    "画面写法（对接 Seedream 静帧 + Seedance 图生视频）："
    "用一句连贯自然语言写「主体 + 动作时序 + 景别/运镜 + 可见环境标志物」；"
    "运镜只用推/拉/摇/移/跟/升/降/环绕等；"
    "禁止切黑/转场/叠化等后期指令；禁止空泛堆砌「绝美/震撼」；"
    "对白镜写清谁在画面中、表情与口型可读的中近景。"
)
