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

    # 阿里云百炼（DashScope）：出图 / 图生视频 / 高拟真配音
    # 通用端点（wanx / qwen-image / qwen-tts 走这里）
    DASHSCOPE_API_KEY: str = os.getenv("DASHSCOPE_API_KEY", "")
    DASHSCOPE_BASE_URL: str = os.getenv(
        "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com"
    )
    DASHSCOPE_IMAGE_MODEL: str = os.getenv("DASHSCOPE_IMAGE_MODEL", "qwen-image-plus")
    DASHSCOPE_I2V_MODEL: str = os.getenv("DASHSCOPE_I2V_MODEL", "wanx2.1-i2v-turbo")
    DASHSCOPE_TTS_MODEL: str = os.getenv("DASHSCOPE_TTS_MODEL", "qwen-audio-3.0-tts-plus")
    # 可灵(Kling)等第三方模型走专属 MaaS 端点（如 ws-xxx.cn-beijing.maas.aliyuncs.com）。
    # 提交带 X-DashScope-Async；查询结果 GET /api/v1/tasks/{id} 不带该头。
    DASHSCOPE_MAAS_BASE_URL: str = os.getenv("DASHSCOPE_MAAS_BASE_URL", "")
    KLING_IMAGE_MODEL: str = os.getenv(
        "KLING_IMAGE_MODEL", "kling/kling-v3-omni-image-generation"
    )
    KLING_VIDEO_MODEL: str = os.getenv(
        "KLING_VIDEO_MODEL", "kling/kling-v3-video-generation"
    )
    # 可灵 omni 视频模型：支持首帧图生视频 / 参考生视频
    KLING_OMNI_VIDEO_MODEL: str = os.getenv(
        "KLING_OMNI_VIDEO_MODEL", "kling/kling-v3-omni-video-generation"
    )
    # PixVerse 对口型模型（输入视频+音频 → 口型同步视频）
    PIXVERSE_LIP_MODEL: str = os.getenv(
        "PIXVERSE_LIP_MODEL", "pixverse/pixverse-lipsync"
    )

    # LatentSync（最高画质开源口型，经 Replicate）
    REPLICATE_API_TOKEN: str = os.getenv("REPLICATE_API_TOKEN", "")
    REPLICATE_LIP_MODEL: str = os.getenv("REPLICATE_LIP_MODEL", "bytedance/latentsync")
    REPLICATE_LIP_VERSION: str = os.getenv("REPLICATE_LIP_VERSION", "")

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

    # 后台渲染 worker 池（S4）：整集级任务互斥；镜头级任务可并行。
    # 出图墙与整集重渲的镜头级并发都用此值。
    DRAMA_MAX_WORKERS: int = int(os.getenv("DRAMA_MAX_WORKERS", "4"))
    # 同一 slug:episode 下镜头级任务（i2v/lip/keys/rerender）最大并发数。
    DRAMA_SHOT_CONCURRENCY: int = int(os.getenv("DRAMA_SHOT_CONCURRENCY", "3"))
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

    # 口型（质量优先）：latentsync | pixverse | musetalk | http | mock
    # 默认 max：优先 LatentSync(Replicate) → PixVerse(百炼) → 自建网关；默认禁止伪波形 mock
    LIP_PROVIDER: str = os.getenv("LIP_PROVIDER", "pixverse")
    LIP_API_URL: str = os.getenv("LIP_API_URL", "")
    LIP_API_KEY: str = os.getenv("LIP_API_KEY", "")
    LIP_QUALITY: str = os.getenv("LIP_QUALITY", "max")
    LIP_ALLOW_MOCK: str = os.getenv("LIP_ALLOW_MOCK", "0")
    LIP_ENSURE_MOTION: str = os.getenv("LIP_ENSURE_MOTION", "1")
    LIP_INFERENCE_STEPS: int = int(os.getenv("LIP_INFERENCE_STEPS", "30"))
    LIP_GUIDANCE_SCALE: float = float(os.getenv("LIP_GUIDANCE_SCALE", "1.5"))
    LIP_POLL_TIMEOUT: float = float(os.getenv("LIP_POLL_TIMEOUT", "600"))

    # 高拟真 TTS（S3）：真 TTS 走自建 HTTP 网关；未配置时诚实回退 edge-tts。
    # 适配器契约：multipart POST { text, voice } 或 JSON { text, voice, model }
    # 返回 audio 字节流。
    TTS_API_URL: str = os.getenv("TTS_API_URL", "")
    TTS_API_KEY: str = os.getenv("TTS_API_KEY", "")


config = Config()
