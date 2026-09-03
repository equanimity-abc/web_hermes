"""应用配置 - 从环境变量加载"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_BACKEND_DIR = Path(__file__).resolve().parent


class Config:
    # DeepSeek（剧本/分镜：与 Kimi 可互相替代）
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")

    # Kimi 月之暗面（剧本/分镜：与 DeepSeek 可互相替代）
    KIMI_API_KEY: str = os.getenv("KIMI_API_KEY", "") or os.getenv("MOONSHOT_API_KEY", "")
    KIMI_BASE_URL: str = os.getenv("KIMI_BASE_URL", "https://api.moonshot.cn/v1")
    KIMI_MODEL: str = os.getenv("KIMI_MODEL", "kimi-k3")

    # 火山方舟 Ark（文本 / 生图 / 视频 / 音频）
    ARK_API_KEY: str = os.getenv("ARK_API_KEY", "") or os.getenv("VOLCENGINE_API_KEY", "")
    ARK_BASE_URL: str = os.getenv(
        "ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"
    )
    ARK_TEXT_MODEL: str = os.getenv("ARK_TEXT_MODEL", "doubao-seed-character-260628")
    ARK_TEXT_MODEL_ALT: str = os.getenv("ARK_TEXT_MODEL_ALT", "glm-5-2-260617")
    ARK_IMAGE_MODEL: str = os.getenv("ARK_IMAGE_MODEL", "doubao-seedream-5-0-pro-260628")
    ARK_VIDEO_MODEL: str = os.getenv("ARK_VIDEO_MODEL", "doubao-seedance-2-5-260628")
    ARK_AUDIO_MODEL: str = os.getenv("ARK_AUDIO_MODEL", "doubao-seed-audio-1-0")

    # 阿里云百炼（DashScope）：出图 / 图生视频 / 高拟真配音
    DASHSCOPE_API_KEY: str = os.getenv("DASHSCOPE_API_KEY", "")
    DASHSCOPE_BASE_URL: str = os.getenv(
        "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com"
    )
    DASHSCOPE_IMAGE_MODEL: str = os.getenv("DASHSCOPE_IMAGE_MODEL", "qwen-image-plus")
    DASHSCOPE_I2V_MODEL: str = os.getenv("DASHSCOPE_I2V_MODEL", "wanx2.1-i2v-turbo")
    DASHSCOPE_TTS_MODEL: str = os.getenv("DASHSCOPE_TTS_MODEL", "qwen-audio-3.0-tts-plus")
    DASHSCOPE_MAAS_BASE_URL: str = os.getenv("DASHSCOPE_MAAS_BASE_URL", "")
    KLING_IMAGE_MODEL: str = os.getenv(
        "KLING_IMAGE_MODEL", "kling/kling-v3-omni-image-generation"
    )
    KLING_VIDEO_MODEL: str = os.getenv(
        "KLING_VIDEO_MODEL", "kling/kling-v3-video-generation"
    )
    KLING_OMNI_VIDEO_MODEL: str = os.getenv(
        "KLING_OMNI_VIDEO_MODEL", "kling/kling-v3-omni-video-generation"
    )
    PIXVERSE_LIP_MODEL: str = os.getenv(
        "PIXVERSE_LIP_MODEL", "pixverse/pixverse-lipsync"
    )

    REPLICATE_API_TOKEN: str = os.getenv("REPLICATE_API_TOKEN", "")
    REPLICATE_LIP_MODEL: str = os.getenv("REPLICATE_LIP_MODEL", "bytedance/latentsync")
    REPLICATE_LIP_VERSION: str = os.getenv("REPLICATE_LIP_VERSION", "")

    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", 8000))
    RELOAD: bool = os.getenv("RELOAD", "0") in ("1", "true", "True", "yes")

    CORS_ORIGINS: list[str] = os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://localhost:3000"
    ).split(",")

    SESSION_DATA_DIR: Path = Path(
        os.getenv("SESSION_DATA_DIR", str(_BACKEND_DIR / "data" / "sessions"))
    )
    WORKSPACE_DIR: Path = Path(
        os.getenv("WORKSPACE_DIR", str(_BACKEND_DIR / "data" / "workspace"))
    )
    MEMORY_DIR: Path = Path(
        os.getenv("MEMORY_DIR", str(_BACKEND_DIR / "data" / "memory"))
    )

    AGENT_MAX_TURNS: int = int(os.getenv("AGENT_MAX_TURNS", "64"))
    LLM_TIMEOUT: float = float(os.getenv("LLM_TIMEOUT", "60"))

    CONTEXT_MAX_CHARS: int = int(os.getenv("CONTEXT_MAX_CHARS", "24000"))
    CONTEXT_KEEP_RECENT: int = int(os.getenv("CONTEXT_KEEP_RECENT", "12"))

    DRAMA_MAX_WORKERS: int = int(os.getenv("DRAMA_MAX_WORKERS", "4"))
    DRAMA_SHOT_CONCURRENCY: int = int(os.getenv("DRAMA_SHOT_CONCURRENCY", "8"))
    DRAMA_RPM_DEFAULT: int = int(os.getenv("DRAMA_RPM_DEFAULT", "0"))
    # Provider lane token buckets (Phase B). 0 = unlimited for that lane.
    DRAMA_RPM_ARK: int = int(os.getenv("DRAMA_RPM_ARK", "20"))
    DRAMA_RPM_DASHSCOPE: int = int(os.getenv("DRAMA_RPM_DASHSCOPE", "20"))
    DRAMA_RPM_LIP: int = int(os.getenv("DRAMA_RPM_LIP", "10"))

    IMAGE_GEN_PROVIDER: str = os.getenv("IMAGE_GEN_PROVIDER", "pollinations")
    IMAGE_GEN_MODEL: str = os.getenv("IMAGE_GEN_MODEL", "flux")

    CONSISTENT_IMAGE_URL: str = os.getenv("CONSISTENT_IMAGE_URL", "")
    CONSISTENT_IMAGE_KEY: str = os.getenv("CONSISTENT_IMAGE_KEY", "")
    CONSISTENT_IMAGE_MODEL: str = os.getenv("CONSISTENT_IMAGE_MODEL", "char-consistent")

    I2V_PROVIDER: str = os.getenv("I2V_PROVIDER", "none")
    I2V_MODEL: str = os.getenv("I2V_MODEL", "default")
    I2V_API_URL: str = os.getenv("I2V_API_URL", "")
    I2V_API_KEY: str = os.getenv("I2V_API_KEY", "")
    I2V_POLL_INTERVAL: float = float(os.getenv("I2V_POLL_INTERVAL", "2.0"))
    I2V_POLL_TIMEOUT: float = float(os.getenv("I2V_POLL_TIMEOUT", "300.0"))
    I2V_SECONDS: float = float(os.getenv("I2V_SECONDS", "2.5"))

    LIP_PROVIDER: str = os.getenv("LIP_PROVIDER", "pixverse")
    LIP_API_URL: str = os.getenv("LIP_API_URL", "")
    LIP_API_KEY: str = os.getenv("LIP_API_KEY", "")
    LIP_QUALITY: str = os.getenv("LIP_QUALITY", "max")
    LIP_ALLOW_MOCK: str = os.getenv("LIP_ALLOW_MOCK", "0")
    LIP_ENSURE_MOTION: str = os.getenv("LIP_ENSURE_MOTION", "1")
    LIP_INFERENCE_STEPS: int = int(os.getenv("LIP_INFERENCE_STEPS", "30"))
    LIP_GUIDANCE_SCALE: float = float(os.getenv("LIP_GUIDANCE_SCALE", "1.5"))
    LIP_POLL_TIMEOUT: float = float(os.getenv("LIP_POLL_TIMEOUT", "600"))

    TTS_API_URL: str = os.getenv("TTS_API_URL", "")
    TTS_API_KEY: str = os.getenv("TTS_API_KEY", "")


config = Config()
