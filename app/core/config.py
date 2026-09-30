"""환경변수 설정을 한 곳에서 관리한다."""
import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    SUPABASE_URL: str = os.environ.get("SUPABASE_URL", "")
    SUPABASE_KEY: str = os.environ.get("SUPABASE_KEY", "")
    GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "")

    # llama-4-scout(비전)는 2026-07-17, llama-3.3-70b는 2026-08-16에 Groq에서 종료됨
    GROQ_VISION_MODEL: str = os.environ.get("GROQ_VISION_MODEL", "qwen/qwen3.8-27b")
    GROQ_TEXT_MODEL: str = os.environ.get("GROQ_TEXT_MODEL", "openai/gpt-oss-120b")
    GROQ_STT_MODEL: str = os.environ.get("GROQ_STT_MODEL", "whisper-large-v3-turbo")

    CORS_ORIGINS: list[str] = [
        o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()
    ]

    # Groq base64 이미지 한도 4MB → 여유 있게 3MB로 압축
    MAX_IMAGE_BYTES: int = 3 * 1024 * 1024
    MAX_UPLOAD_BYTES: int = 15 * 1024 * 1024


settings = Settings()
