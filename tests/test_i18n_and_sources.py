"""11/9: 안내 문구 다국어 + 구글 지도 사진 참고 식당 출처 표시."""
from fastapi.testclient import TestClient

from app.main import app
from app.services import restaurant_service

client = TestClient(app)


def _search(**body):
    r = client.post("/restaurants/search", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_notice_and_disclaimer_follow_profile_language():
    """식당 찾기·분석 안내 문구가 프로필 언어로 나온다 (프론트는 그대로 표시)."""
    for lang, word in [("en", "staff"), ("zh", "店员"), ("ja", "店員"), ("ko", "직원")]:
        d = _search(profile={"preferred_language": lang})
        assert d["profile_applied"] is False
        assert word in d["disclaimer"] and "SAFE" in d["notice"]
    d = _search()                                               # 언어 지정 없으면 영어
    assert "staff" in d["disclaimer"]
    d = client.post("/analyze", json={"menus": [{"name": "김밥"}], "skip_ai": True,
                                      "profile": {"preferred_language": "ja", "allergies": ["egg"]}}).json()
    assert "店員" in d["disclaimer"]


def test_no_restaurant_uses_google_maps_photos():
    """태욱님 확인 요청(구글 지도 약관 3.2.3(c)): 구글 지도 사진을 참고한 식당이 남아 있으면 안 된다.
    학교 앞 4곳은 네이버 플레이스의 업주 등록 메뉴판 이미지로 다시 입력했다."""
    rs = restaurant_service.load_restaurants()
    assert not [r["id"] for r in rs if r.get("source_check") == "replace_photo" or "구글" in r.get("source", "")]
    naver = {r["id"] for r in rs if "네이버 플레이스" in r.get("source", "")}
    assert naver == {"hiwaffle-kyungsung-pknu", "yuilhan-siktak", "hey-egg-noodle", "myeonsikdang-pknu"}
