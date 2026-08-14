"""应用配置 - 从环境变量加载"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_BACKEND_DIR = Path(__file__).resolve().parent


class Config:
    # DeepSeek
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

    # Server
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", 8000))

    # CORS (允许前端开发服务器跨域)
    CORS_ORIGINS: list[str] = os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://localhost:3000"
    ).split(",")

    # 会话 JSON 目录（相对 backend/ 或绝对路径）
    SESSION_DATA_DIR: Path = Path(
        os.getenv("SESSION_DATA_DIR", str(_BACKEND_DIR / "data" / "sessions"))
    )

    # Agent 文件工具沙箱（相对路径均相对此目录）
    WORKSPACE_DIR: Path = Path(
        os.getenv("WORKSPACE_DIR", str(_BACKEND_DIR / "data" / "workspace"))
    )

    # 跨会话长期记忆
    MEMORY_DIR: Path = Path(
        os.getenv("MEMORY_DIR", str(_BACKEND_DIR / "data" / "memory"))
    )

    # Agent loop
    AGENT_MAX_TURNS: int = int(os.getenv("AGENT_MAX_TURNS", "32"))

    # Context compression（按字符粗估，超限则摘要旧轮次）
    CONTEXT_MAX_CHARS: int = int(os.getenv("CONTEXT_MAX_CHARS", "24000"))
    CONTEXT_KEEP_RECENT: int = int(os.getenv("CONTEXT_KEEP_RECENT", "12"))

    # 分镜画面（pollinations 免费图生；none 则只用运镜底图）
    IMAGE_GEN_PROVIDER: str = os.getenv("IMAGE_GEN_PROVIDER", "pollinations")
    IMAGE_GEN_MODEL: str = os.getenv("IMAGE_GEN_MODEL", "flux")


config = Config()
