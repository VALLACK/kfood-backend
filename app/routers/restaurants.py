from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import AuthContext, optional_auth
from app.models.schemas import ProfileInput
from app.services import restaurant_service
from app.services.profile_service import resolve_profile

router = APIRouter(tags=["restaurants"])


class RestaurantSearch(BaseModel):
    q: str = ""                      # 식당 이름·지역·업종·메뉴명 (비우면 전체)
    only_edible: bool = False        # 먹을 수 있는(SAFE) 메뉴가 있는 식당만
    sort: Literal["rating", "edible"] = "rating"
    profile: ProfileInput | None = None   # 게스트용. 로그인 사용자는 DB 프로필을 쓴다


class RestaurantDetail(BaseModel):
    profile: ProfileInput | None = None


@router.post("/restaurants/search")
def search_restaurants(body: RestaurantSearch, auth: AuthContext | None = Depends(optional_auth)):
    """가기 전에 미리 알아보기: 저장된 식당을 내 프로필 기준으로 판정해 구글 평점순으로 보여준다."""
    profile, _ = resolve_profile(auth, body.profile)
    return {
        "profile_applied": not profile.is_empty(),
        "restaurants": restaurant_service.search(profile, body.q, body.only_edible, body.sort),
        "rating_attribution": "평점: Google",
    }


@router.post("/restaurants/{restaurant_id}")
def restaurant_detail(restaurant_id: str, body: RestaurantDetail | None = None,
                      auth: AuthContext | None = Depends(optional_auth)):
    """식당 하나의 메뉴별 판정. results 항목은 /analyze의 results와 같은 형식이다."""
    profile, _ = resolve_profile(auth, body.profile if body else None)
    data = restaurant_service.detail(restaurant_id, profile)
    if data is None:
        raise HTTPException(status_code=404, detail="저장된 식당이 아닙니다.")
    return {"profile_applied": not profile.is_empty(), **data, "rating_attribution": "평점: Google"}
