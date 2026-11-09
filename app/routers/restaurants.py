from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.auth import AuthContext, optional_auth
from app.models.schemas import ProfileInput
from app.services import restaurant_service
from app.services.profile_service import resolve_profile

router = APIRouter(tags=["restaurants"])

RATING_ATTRIBUTION = "Google Maps"
DISCLAIMER = "재료는 메뉴판과 일반 레시피 기준 추정이며, 최종 판단은 반드시 직원 확인 후 하세요."
NO_PROFILE_NOTICE = "프로필(알레르기·식단)이 없어서 모든 메뉴가 SAFE로 보입니다. 프로필을 설정해야 판정이 적용됩니다."


def _meta(profile) -> dict:
    applied = not profile.is_empty()
    return {"profile_applied": applied, "notice": None if applied else NO_PROFILE_NOTICE,
            "disclaimer": DISCLAIMER, "rating_attribution": RATING_ATTRIBUTION}


class RestaurantSearch(BaseModel):
    q: str = ""                      # 식당 이름·지역·업종·메뉴명 (비우면 전체)
    only_edible: bool = False        # 먹을 수 있는(SAFE) 메뉴가 있는 식당만
    sort: Literal["rating", "edible"] = "rating"
    limit: int = Field(restaurant_service.MAX_RESULTS, ge=1, le=restaurant_service.MAX_RESULTS)  # 최대 20곳
    profile: ProfileInput | None = None   # 게스트용. 로그인 사용자는 DB 프로필을 쓴다


class RestaurantDetail(BaseModel):
    profile: ProfileInput | None = None


@router.post("/restaurants/search")
def search_restaurants(body: RestaurantSearch, auth: AuthContext | None = Depends(optional_auth)):
    """가기 전에 미리 알아보기: 저장된 식당을 내 프로필 기준으로 판정해 구글 평점순으로 보여준다."""
    profile, _ = resolve_profile(auth, body.profile)
    page = restaurant_service.search_page(profile, body.q, body.only_edible, body.sort, body.limit)
    return {**_meta(profile), **page}


@router.post("/restaurants/{restaurant_id}")
def restaurant_detail(restaurant_id: str, body: RestaurantDetail | None = None,
                      auth: AuthContext | None = Depends(optional_auth)):
    """식당 하나의 메뉴별 판정. results 항목은 /analyze의 results와 같은 형식이다."""
    profile, _ = resolve_profile(auth, body.profile if body else None)
    data = restaurant_service.detail(restaurant_id, profile)
    if data is None:
        raise HTTPException(status_code=404, detail="저장된 식당이 아닙니다.")
    return {**_meta(profile), **data}
