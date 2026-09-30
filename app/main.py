from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db.supabase_client import require_supabase, supabase
from app.routers import analyze, menus, ocr, profile_card, qna, stt

app = FastAPI(title="K-Food Safety Guide API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ocr.router)
app.include_router(analyze.router)
app.include_router(qna.router)
app.include_router(stt.router)
app.include_router(profile_card.router)
app.include_router(menus.router)


@app.get("/")
def root():
    return {"message": "K-Food Backend API is running!"}


@app.get("/health")
def health_check():
    return {"status": "ok", "supabase_configured": supabase is not None, "groq_configured": bool(settings.GROQ_API_KEY)}


@app.get("/profiles/test")
def test_profiles():
    # TODO(한석호): 배포 전 삭제 권장 — RLS 적용 후에는 익명 키로 빈 배열만 반환됨
    response = require_supabase().table("profiles").select("*").execute()
    return response.data
