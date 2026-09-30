from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import AuthContext, optional_auth
from app.models.schemas import AnalyzeRequest
from app.services import analysis_service
from app.services.profile_service import resolve_profile

router = APIRouter(tags=["analyze"])


@router.post("/analyze")
def analyze_menu(body: AnalyzeRequest, auth: AuthContext | None = Depends(optional_auth)):
    if not body.menus and not (body.ocr_text and body.ocr_text.strip()):
        raise HTTPException(status_code=422, detail="menus 또는 ocr_text 중 하나는 필요합니다.")

    profile, row = resolve_profile(auth, body.profile)
    results = analysis_service.analyze(body.menus, body.ocr_text, profile, skip_ai=body.skip_ai)

    scan_log_id = None
    if auth and row and not body.skip_ai:  # 즉시 판정은 중간 결과라 기록하지 않는다
        res = auth.client.table("scan_logs").insert({
            "profile_id": row["id"],
            "scan_image_url": body.scan_image_url,
            "raw_ocr_text": body.ocr_text or "\n".join(m.name for m in body.menus or []),
            "analysis_result": {"results": results},
        }).execute()
        scan_log_id = res.data[0]["id"] if res.data else None

    return {
        "scan_log_id": scan_log_id,
        "profile_applied": not profile.is_empty(),
        "results": results,
        "disclaimer": "성분 비율(ratio_percent)은 AI 추정치이며, 최종 판단은 반드시 직원 확인 후 하세요.",
    }
