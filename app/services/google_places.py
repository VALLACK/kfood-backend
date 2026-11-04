"""구글 지도 평점 조회 (Places API New — Place Details).

구글 정책상 평점·리뷰 수는 저장(캐시)하면 안 되고, 식당 ID(place_id)만 저장할 수 있다.
그래서 평점은 식당 목록을 보여줄 때마다 여기서 새로 불러온다.

- 키: .env의 GOOGLE_MAPS_API_KEY (결제 계정이 연결된 구글 클라우드 프로젝트의 키)
- 키가 없거나 호출이 실패하면 평점 없이(None) 돌려준다. 검색 자체는 막지 않는다.
- 평점(rating)은 Place Details의 Enterprise 등급 필드라 무료 사용량이 적다(월 약 1,000건).
  식당 10곳 목록을 한 번 보여줄 때 10건이 쓰인다.
"""
from concurrent.futures import ThreadPoolExecutor

import httpx

from app.core.config import settings

URL = "https://places.googleapis.com/v1/places/{place_id}"
FIELDS = "rating,userRatingCount,googleMapsUri"


def get_rating(place_id: str | None) -> dict | None:
    if not place_id or not settings.GOOGLE_MAPS_API_KEY:
        return None
    try:
        r = httpx.get(
            URL.format(place_id=place_id),
            headers={"X-Goog-Api-Key": settings.GOOGLE_MAPS_API_KEY, "X-Goog-FieldMask": FIELDS},
            timeout=5,
        )
        if r.status_code != 200:
            return None
        d = r.json()
    except (httpx.HTTPError, ValueError):
        return None
    if d.get("rating") is None:
        return None
    return {
        "rating": d.get("rating"),
        "count": d.get("userRatingCount"),
        "maps_url": d.get("googleMapsUri"),
        "source": "Google",
    }


def get_ratings(place_ids: list[str | None]) -> list[dict | None]:
    """여러 식당을 동시에 조회한다 (10곳을 차례로 부르면 몇 초씩 걸린다)."""
    if not settings.GOOGLE_MAPS_API_KEY:
        return [None] * len(place_ids)
    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(get_rating, place_ids))
