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
    # 热重载会断开进行中的 SSE 长连接，漫剧长任务场景默认关闭
    RELOAD: bool = os.getenv("RELOAD", "0") in ("1", "true", "True", "yes")

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
    # 每次 LLM 调用算一轮（一轮可并发多次 tool_calls）。后台任务提交后必须「移交」
    # 让用户查工作台，禁止在 loop 里反复 poll_job 等任务完成——那会白白烧光轮次。
    AGENT_MAX_TURNS: int = int(os.getenv("AGENT_MAX_TURNS", "64"))
    # LLM 单次请求超时（秒）。过大会让「停止」按钮长时间无响应（请求挂起时取消取不到控制权）。
    LLM_TIMEOUT: float = float(os.getenv("LLM_TIMEOUT", "60"))

    # Context compression（按字符粗估，超限则摘要旧轮次）
    CONTEXT_MAX_CHARS: int = int(os.getenv("CONTEXT_MAX_CHARS", "24000"))
    CONTEXT_KEEP_RECENT: int = int(os.getenv("CONTEXT_KEEP_RECENT", "12"))

    # 后台渲染 worker 池（S4）：同集按 slug:episode 互斥，跨集/跨项目并行出图。
    # 出图墙与整集重渲的镜头级并发都用此值。
    DRAMA_MAX_WORKERS: int = int(os.getenv("DRAMA_MAX_WORKERS", "2"))
    # 外部生成 provider 的默认限流（次/分钟），rpm=0 表示不限。
    DRAMA_RPM_DEFAULT: int = int(os.getenv("DRAMA_RPM_DEFAULT", "0"))

    # 分镜画面（pollinations 免费图生；none 则只用运镜底图）
    IMAGE_GEN_PROVIDER: str = os.getenv("IMAGE_GEN_PROVIDER", "pollinations")
    IMAGE_GEN_MODEL: str = os.getenv("IMAGE_GEN_MODEL", "flux")

    # 角色一致性出图（S1）：通用 HTTP 适配器协议。
    # 未配置 URL 时诚实回退 pollinations；配置后即走真一致性模型（img2img / IP-Adapter）。
    # 适配器契约：multipart POST { image: 参考图(可多个), prompt, seed, width, height, model }
    CONSISTENT_IMAGE_URL: str = os.getenv("CONSISTENT_IMAGE_URL", "")
    CONSISTENT_IMAGE_KEY: str = os.getenv("CONSISTENT_IMAGE_KEY", "")
    CONSISTENT_IMAGE_MODEL: str = os.getenv("CONSISTENT_IMAGE_MODEL", "char-consistent")

    # I2V（D8 + S2）：真 I2V 走自建网关（异步提交→轮询→下载）；失败回退静图 zoompan
    # none | mock | fail | http | kling | hailuo
    I2V_PROVIDER: str = os.getenv("I2V_PROVIDER", "none")
    I2V_MODEL: str = os.getenv("I2V_MODEL", "default")
    I2V_API_URL: str = os.getenv("I2V_API_URL", "")       # 提交端点（multipart 提交，返回 job_id 或直接结果）
    I2V_API_KEY: str = os.getenv("I2V_API_KEY", "")        # Bearer token（自建网关鉴权）
    I2V_POLL_INTERVAL: float = float(os.getenv("I2V_POLL_INTERVAL", "2.0"))
    I2V_POLL_TIMEOUT: float = float(os.getenv("I2V_POLL_TIMEOUT", "300.0"))
    I2V_SECONDS: float = float(os.getenv("I2V_SECONDS", "2.5"))

    # 口型（Q2 + S3）：仅 dialogue CU/MCU；none|mock|fail|http|musetalk|wav2lip
    LIP_PROVIDER: str = os.getenv("LIP_PROVIDER", "mock")
    LIP_API_URL: str = os.getenv("LIP_API_URL", "")
    LIP_API_KEY: str = os.getenv("LIP_API_KEY", "")

    # 高拟真 TTS（S3）：真 TTS 走自建 HTTP 网关；未配置时诚实回退 edge-tts。
    # 适配器契约：multipart POST { text, voice } 或 JSON { text, voice, model }
    # 返回 audio 字节流。
    TTS_API_URL: str = os.getenv("TTS_API_URL", "")
    TTS_API_KEY: str = os.getenv("TTS_API_KEY", "")


config = Config()
