from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db.supabase_client import supabase
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

# 팀 내부 운영용(인증 없음) — 로컬에서만 ENABLE_OPS_ROUTES=1 로 켠다
if settings.ENABLE_OPS_ROUTES:
    app.include_router(menus.router)


@app.get("/")
def root():
    return {"message": "K-Food Backend API is running!"}


@app.get("/health")
def health_check():
    return {"status": "ok", "supabase_configured": supabase is not None, "groq_configured": bool(settings.GROQ_API_KEY)}