"""메뉴 데이터 운영용 엔드포인트 (팀 내부 확인용)."""
from fastapi import APIRouter, Query

from app.services import unmatched_log
from app.services.menu_knowledge import build_known_ingredients

router = APIRouter(prefix="/menus", tags=["menus"])


@router.get("/unmatched")
def unmatched(limit: int = Query(50, le=500), status: str | None = None):
    """공공데이터·자체 DB에 없어 AI 추론으로 처리된 메뉴 목록 (빈도순).

    자주 나오는 메뉴부터 검수해 메뉴 DB에 추가하면 커버리지가 올라간다.
    """
    return {"stats": unmatched_log.stats(), "items": unmatched_log.top(limit, status)}


@router.get("/lookup")
def lookup(name: str):
    """메뉴 하나가 어떤 데이터로 판정되는지 확인 (검수용)."""
    k = build_known_ingredients(name)
    if not k:
        return {"menu": name, "matched": False, "data_source": None,
                "message": "데이터 없음 — AI 추론으로 처리되며 검수 대상입니다."}
    return {
        "menu": name, "matched": True, "data_source": k.get("data_source"),
        "base_menu": k["base_menu"], "family": k.get("family", []),
        "ingredients": [{"name": i["name"], "tags": i["tags"], "certainty": i["certainty"],
                         "ratio_percent": i.get("ratio_percent")} for i in k["ingredients"]],
    }
