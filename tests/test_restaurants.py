"""미리 알아보기(저장된 식당 검색) 테스트. 구글 호출은 가짜로 바꾼다."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services import google_places, restaurant_service

client = TestClient(app)
SHELLFISH = {"allergies": ["shellfish"], "preferred_language": "en"}


@pytest.fixture
def fake_google(monkeypatch):
    """place_id → 평점. 실제 구글을 부르지 않는다."""
    ratings = {}
    calls = []
    monkeypatch.setattr(settings, "GOOGLE_MAPS_API_KEY", "test-key")

    def fake_get(url, headers=None, timeout=None):
        calls.append((url, headers))
        pid = url.rsplit("/", 1)[-1]
        req = httpx.Request("GET", url)
        if pid not in ratings:
            return httpx.Response(404, request=req, json={})
        return httpx.Response(200, request=req, json={"rating": ratings[pid], "userRatingCount": 100,
                                                      "googleMapsUri": f"https://maps.google.com/?cid={pid}"})

    monkeypatch.setattr(google_places.httpx, "get", fake_get)
    monkeypatch.setattr(google_places, "_used", {"day": None, "count": 0})   # 하루 상한 카운트 초기화
    return ratings, calls


@pytest.fixture
def place_ids(monkeypatch):
    """저장 데이터에 place_id를 임시로 넣는다."""
    data = [dict(r) for r in restaurant_service.load_restaurants()]
    ids = {"katsuan": "P_KATSU", "osaka": "P_OSAKA", "chakhan-gukbap": "P_CHAKHAN"}
    for r in data:
        r["google_place_id"] = ids.get(r["id"])
    monkeypatch.setattr(restaurant_service, "load_restaurants", lambda: data)
    return ids


def _search(**body):
    r = client.post("/restaurants/search", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_saved_restaurants_have_menus_and_no_stored_ratings():
    """구글 정책: 평점은 저장하지 않는다. 저장 파일에 rating 같은 값이 없어야 한다."""
    rs = restaurant_service.load_restaurants()
    assert len(rs) >= 7
    assert all(r["menus"] for r in rs)
    assert all(r["name_confirmed"] for r in rs)   # 상호 애매한 식당은 넣지 않는다
    raw = json.dumps(rs, ensure_ascii=False)
    assert '"rating"' not in raw and "userRatingCount" not in raw


def test_search_works_without_google_key(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_MAPS_API_KEY", "")
    d = _search(profile=SHELLFISH)
    assert d["profile_applied"] is True
    assert d["restaurants"] and all(r["google"] is None for r in d["restaurants"])


def test_sorted_by_google_rating_and_unrated_last(fake_google, place_ids):
    ratings, _ = fake_google
    ratings.update({"P_KATSU": 4.1, "P_OSAKA": 4.7, "P_CHAKHAN": 4.4})
    names = [r["id"] for r in _search(profile=SHELLFISH)["restaurants"]]
    assert names[:3] == ["osaka", "chakhan-gukbap", "katsuan"]
    top = _search(profile=SHELLFISH)["restaurants"][0]
    assert top["google"]["source"] == "Google Maps" and top["google"]["rating"] == 4.7


def test_profile_changes_what_is_edible():
    """같은 식당도 프로필에 따라 먹을 수 있는 메뉴 수가 달라진다 (국밥집: 할랄이면 0개)."""
    halal = {r["id"]: r["summary"] for r in _search(profile={"religious_diet": "halal"})["restaurants"]}
    shrimp = {r["id"]: r["summary"] for r in _search(profile=SHELLFISH)["restaurants"]}
    assert halal["chakhan-gukbap"]["safe"] == 0
    assert halal["katsuan"]["warning"] >= 1          # 돈까스집 → 할랄 위험
    assert shrimp["haemulnara"]["warning"] >= 1       # 조개구이집 → 갑각류 위험


def test_only_edible_filters_out_restaurants_with_nothing_to_eat():
    d = _search(q="국밥", only_edible=True, profile={"religious_diet": "halal"})
    assert d["restaurants"] == []
    d = _search(q="국밥", profile={"religious_diet": "halal"})
    assert len(d["restaurants"]) >= 2   # 필터를 끄면 국밥집이 보인다


def test_query_matches_name_area_category_and_menu():
    assert [r["id"] for r in _search(q="카츠안")["restaurants"]] == ["katsuan"]
    assert "gaemijip-gwangalli" in [r["id"] for r in _search(q="광안리")["restaurants"]]
    assert "osaka" in [r["id"] for r in _search(q="오코노미야키")["restaurants"]]   # 메뉴명으로도 찾음


def test_sort_by_edible(place_ids, fake_google):
    rs = _search(sort="edible", profile=SHELLFISH)["restaurants"]
    safes = [r["summary"]["safe"] for r in rs]
    assert safes == sorted(safes, reverse=True)


def test_detail_matches_analyze_for_same_menu():
    """미리 알아보기 판정은 메뉴판을 직접 찍었을 때(/analyze)와 같은 엔진이다."""
    d = client.post("/restaurants/chakhan-gukbap", json={"profile": SHELLFISH}).json()
    gukbap = next(m for m in d["results"] if m["menu"] == "돼지국밥")
    assert gukbap["risk"]["level"] == "CAUTION"
    assert any("새우젓" in q["ko"] for q in gukbap["risk"]["staff_questions"])
    assert gukbap["prices"] == ["8,000"]
    levels = [m["risk"]["level"] for m in d["results"]]
    order = {"SAFE": 0, "CAUTION": 1, "WARNING": 2}
    assert levels == sorted(levels, key=order.get)       # 먹을 수 있는 메뉴부터


def test_detail_unknown_restaurant_is_404():
    assert client.post("/restaurants/nope", json={}).status_code == 404


def test_search_does_not_call_ai(monkeypatch):
    from app.services import groq_service
    monkeypatch.setattr(groq_service, "chat_json", lambda *a, **k: pytest.fail("AI를 부르면 안 된다"))
    _search(profile=SHELLFISH)


def test_google_failure_does_not_break_search(monkeypatch, place_ids):
    monkeypatch.setattr(settings, "GOOGLE_MAPS_API_KEY", "test-key")

    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(google_places.httpx, "get", boom)
    assert all(r["google"] is None for r in _search(profile=SHELLFISH)["restaurants"])


def test_find_place_ids_set_and_write(monkeypatch, tmp_path):
    from scripts import find_place_ids

    path = tmp_path / "restaurants.json"
    path.write_text(json.dumps({"restaurants": [
        {"id": "katsuan", "name": "카츠안", "area": "", "name_confirmed": True, "google_place_id": None, "menus": []},
        {"id": "x", "name": "모름", "area": "", "name_confirmed": False, "google_place_id": None, "menus": []},
    ]}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(find_place_ids, "DATA_PATH", path)
    monkeypatch.setattr(settings, "GOOGLE_MAPS_API_KEY", "test-key")
    sent = []

    def fake_post(url, json=None, headers=None, timeout=None):
        sent.append((json, headers))
        return httpx.Response(200, request=httpx.Request("POST", url),
                              json={"places": [{"id": "ChIJ_KATSU", "displayName": {"text": "카츠안"}, "formattedAddress": "부산"}]})

    monkeypatch.setattr(find_place_ids.httpx, "post", fake_post)
    find_place_ids.main(["--write"])
    saved = {r["id"]: r for r in __import__("json").loads(path.read_text(encoding="utf-8"))["restaurants"]}
    assert saved["katsuan"]["google_place_id"] == "ChIJ_KATSU"
    assert saved["x"]["google_place_id"] is None            # 상호 미확인 → 건너뜀
    assert "rating" not in sent[0][1]["X-Goog-FieldMask"]   # 검색에서는 평점(비싼 필드)을 받지 않는다

    find_place_ids.main(["--set", "x=ChIJ_MANUAL"])
    saved = {r["id"]: r for r in __import__("json").loads(path.read_text(encoding="utf-8"))["restaurants"]}
    assert saved["x"]["google_place_id"] == "ChIJ_MANUAL"


def test_add_restaurant_from_photo(monkeypatch, tmp_path):
    """메뉴판 사진 → /ocr → /analyze 결과로 식당을 등록한다 (AI는 가짜)."""
    from scripts import add_restaurant
    from app.services import groq_service

    path = tmp_path / "restaurants.json"
    path.write_text(json.dumps({"restaurants": [
        {"id": "pknu-gukbap", "name": "옛이름", "google_place_id": "ChIJ_KEEP", "menus": []}]}), encoding="utf-8")
    monkeypatch.setattr(add_restaurant, "DATA_PATH", path)

    def fake_ai(model, messages, **kw):
        if "vision" in model or "qwen" in model:
            return {"menus": [{"name": "돼지국밥", "price": "9,000"}, {"name": "사장님특제덮밥", "price": "6,000"},
                              {"name": "소주", "price": "5,000"}], "origin_info": []}
        return {"results": [{"menu": "사장님특제덮밥", "menu_translated": "Chef's Special Rice Bowl",
                             "ingredients": [{"name": "새우", "tags": ["shrimp"], "certainty": "confirmed"}]}]}

    monkeypatch.setattr(groq_service, "chat_json", fake_ai)

    class Local:   # httpx.Client 대신 테스트 서버로 보낸다
        def __init__(self, *a, **k): self.c = client
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, **kw): return self.c.post(url.replace("http://localhost:8000", ""), **kw)

    monkeypatch.setattr(add_restaurant.httpx, "Client", Local)
    import io
    from PIL import Image
    photo = tmp_path / "menu.png"
    Image.new("RGB", (40, 40), "white").save(photo)

    add_restaurant.main(["--id", "pknu-gukbap", "--name", "학교앞국밥", "--area", "남구 대연동",
                         "--category", "국밥", "--photo", str(photo)])
    r = json.loads(path.read_text(encoding="utf-8"))["restaurants"][0]
    assert r["name"] == "학교앞국밥" and r["google_place_id"] == "ChIJ_KEEP"   # 구글 ID는 유지
    names = [m["name"] for m in r["menus"]]
    assert names == ["돼지국밥", "사장님특제덮밥"]                                 # 소주는 제외
    shrimp = next(m for m in r["menus"] if m["name"] == "사장님특제덮밥")
    assert any(i["name"] == "새우" for i in shrimp["ai"]["ingredients"])

    # 등록한 식당이 바로 검색되고, 새우 알레르기면 특제덮밥이 위험으로 나온다
    monkeypatch.setattr(restaurant_service, "DATA_PATH", path)
    restaurant_service.load_restaurants.cache_clear()
    try:
        d = client.post("/restaurants/pknu-gukbap", json={"profile": SHELLFISH}).json()
        level = {m["menu"]: m["risk"]["level"] for m in d["results"]}
        assert level["사장님특제덮밥"] == "WARNING"
    finally:
        restaurant_service.load_restaurants.cache_clear()


def test_hiwaffle_peanut_menus_are_warning():
    """하이와플: 땅콩버터 들어간 와플만 땅콩 알레르기에 🔴, 나머지는 먹을 수 있다."""
    from app.services.dietary_rules import DietProfile
    d = restaurant_service.detail("hiwaffle-kyungsung-pknu", DietProfile.from_row({"allergies": ["peanut"]}))
    warn = {r["menu"] for r in d["results"] if r["risk"]["level"] == "WARNING"}
    assert warn and all("땅콩" in m for m in warn)
    assert d["summary"]["warning"] == 4 and d["summary"]["safe"] == 27


def test_every_restaurant_has_maps_link_without_google_key(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_MAPS_API_KEY", "")
    for r in _search()["restaurants"]:
        assert r["maps_url"].startswith("https://www.google.com/maps/search/?api=1&query=")
    r = {"name": "카츠안", "area": "", "google_place_id": "ChIJabc"}
    assert restaurant_service.maps_url(r).endswith("&query_place_id=ChIJabc")


def test_misread_menu_names_from_eval_are_fixed():
    """태욱님 리뷰: 평가 채점에서 메뉴명 X였던 이름이 데이터에 남아 있으면 안 된다."""
    import csv
    from pathlib import Path
    rows = csv.DictReader(Path("docs/eval_1005_scored.csv").open(encoding="utf-8-sig"))
    wrong = {r["메뉴"] for r in rows if r["채점_메뉴명정확"] == "X"}
    names = {m["name"] for r in restaurant_service.load_restaurants() for m in r["menus"]}
    assert not (wrong & names), wrong & names
    assert not [p for r in restaurant_service.load_restaurants() for m in r["menus"] for p in m["prices"]
                if p.startswith(("W", "₩"))]


def test_chicken_rice_bowl_is_not_safe_for_halal():
    """원래 '닭덮밥'이 '달걀밥'으로 읽혀 할랄에 SAFE가 났던 문제."""
    d = client.post("/restaurants/osaka", json={"profile": {"religious_diet": "halal"}}).json()
    bowl = next(m for m in d["results"] if m["menu"] == "닭덮밥")
    assert bowl["risk"]["level"] != "SAFE"
    assert "달걀밥" not in [m["menu"] for m in d["results"]]


def test_manual_menus_are_labeled_manual_not_ai():
    d = client.post("/restaurants/hiwaffle-kyungsung-pknu", json={"profile": SHELLFISH}).json()
    plain = next(m for m in d["results"] if m["menu"] == "사과잼 플레인와플")
    assert plain["data_source"] == "manual"
    assert {i["source"] for i in plain["ingredients"]} <= {"manual", "menu_name", "menu_board", "menuzen", "menu_base", None}
    assert "ai" not in {i["source"] for i in plain["ingredients"]}
    # 사진 분석 식당은 그대로 ai
    d = client.post("/restaurants/katsuan", json={"profile": SHELLFISH}).json()
    assert "manual" not in {m["data_source"] for m in d["results"]}


def test_no_profile_shows_notice_and_disclaimer():
    d = _search()
    assert d["profile_applied"] is False and "SAFE" in d["notice"]
    assert d["disclaimer"] and d["rating_attribution"] == "Google Maps"
    d = _search(profile=SHELLFISH)
    assert d["profile_applied"] is True and d["notice"] is None
    d = client.post("/restaurants/osaka", json={}).json()
    assert d["notice"] and d["disclaimer"]


def test_google_daily_limit_stops_rating_calls(fake_google, place_ids, monkeypatch):
    ratings, calls = fake_google
    ratings.update({"P_KATSU": 4.2, "P_OSAKA": 4.3, "P_CHAKHAN": 5.0})
    monkeypatch.setattr(settings, "GOOGLE_RATING_DAILY_LIMIT", 4)
    _search(profile=SHELLFISH)                      # 3건 사용
    d = _search(profile=SHELLFISH)                  # 1건만 남음
    assert len(calls) == 4
    assert sum(r["google"] is not None for r in d["restaurants"]) == 1
    assert len(d["restaurants"]) == 11              # 평점이 없어도 목록은 그대로


def test_repeated_search_is_fast():
    """메뉴 DB 조회를 캐시해서 두 번째 검색부터는 빨라야 한다."""
    import time
    _search(profile=SHELLFISH)
    t = time.time()
    _search(profile={"religious_diet": "halal"})
    assert time.time() - t < 1.0


def test_rating_calls_only_for_returned_restaurants(fake_google, monkeypatch):
    """태욱님 리뷰: 식당이 수백 곳이 돼도 평점은 돌려주는 식당(최대 20곳)만 조회한다."""
    ratings, calls = fake_google
    base = restaurant_service.load_restaurants()[0]
    many = [{**base, "id": f"r{i}", "name": f"식당{i}", "google_place_id": f"P{i}"} for i in range(60)]
    monkeypatch.setattr(restaurant_service, "load_restaurants", lambda: many)
    d = _search(profile=SHELLFISH)
    assert d["total"] == 60
    assert len(d["restaurants"]) == 20
    assert len(calls) == 20                       # 60건이 아니라 20건만 호출
    calls.clear()
    d = _search(profile=SHELLFISH, limit=5)
    assert len(d["restaurants"]) == 5 and len(calls) == 5
    assert client.post("/restaurants/search", json={"limit": 100}).status_code == 422
