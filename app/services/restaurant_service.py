"""'미리 알아보기' — 저장해 둔 식당의 메뉴를 내 프로필 기준으로 판정한다.

메뉴와 AI 재료 답변은 app/data/restaurants.json에 미리 저장돼 있어서 AI를 부르지 않는다.
판정은 /analyze와 같은 규칙 엔진(_build_results)을 그대로 쓰므로, 메뉴판을 직접 찍었을 때와
같은 결과가 나온다.
"""
import copy
import json
import unicodedata
from functools import lru_cache
from pathlib import Path

from app.models.schemas import MenuLine
from urllib.parse import quote

from app.services import analysis_service, google_places
from app.services.dietary_rules import DietProfile
from app.services.menu_knowledge import build_known_ingredients

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "restaurants.json"


@lru_cache
def load_restaurants() -> list[dict]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))["restaurants"]


def _norm(s: str) -> str:
    return "".join(unicodedata.normalize("NFKC", s or "").lower().split())


def _matches(r: dict, q: str) -> bool:
    if not q:
        return True
    q = _norm(q)
    fields = [r["name"], r.get("area", ""), r.get("category", "")] + [m["name"] for m in r["menus"]]
    return any(q in _norm(f) for f in fields)


@lru_cache(maxsize=256)
def _known_for(names: tuple[str, ...]) -> dict:
    """메뉴명 → 공공데이터·자체 DB 조회 결과. 프로필과 상관없어서 한 번만 찾고 재사용한다.
    (식당 11곳·메뉴 170개를 매번 찾으면 검색 한 번에 1~5초 걸렸다)"""
    return {n: build_known_ingredients(n) for n in names}


def warm_cache() -> None:
    """서버 시작 직후 메뉴 조회 캐시를 미리 채운다 (첫 검색도 빠르게)."""
    for r in load_restaurants():
        _known_for(tuple(m["name"] for m in r["menus"]))


def judge_menus(r: dict, profile: DietProfile) -> list[dict]:
    """저장된 재료 답변으로 판정한다.

    메뉴의 재료 답변은 두 종류다.
    - ai: 메뉴판 사진을 분석할 때 AI가 답한 재료 (scripts/add_restaurant.py, build_restaurants.py)
    - manual: 팀이 메뉴판을 보고 일반 레시피 기준으로 직접 입력한 재료
    판정 결과의 data_source·재료 source도 ai / manual로 구분해서 내보낸다.
    """
    lines = [MenuLine(name=m["name"], note=m.get("note")) for m in r["menus"]]
    stored = {m["name"]: analysis_service._sanitize(m.get("ai") or m.get("manual"))
              for m in r["menus"] if m.get("ai") or m.get("manual")}
    known = copy.deepcopy(_known_for(tuple(l.name for l in lines)))
    results = analysis_service._build_results(lines, stored, profile, known_map=known)
    for res, m in zip(results, r["menus"]):
        res["prices"] = m.get("prices", [])
        if m.get("manual"):
            if res.get("data_source") == "ai":
                res["data_source"] = "manual"
            for ing in res.get("ingredients", []):
                if ing.get("source") == "ai":
                    ing["source"] = "manual"
    return results


def _summary(results: list[dict]) -> dict:
    count = {"SAFE": 0, "CAUTION": 0, "WARNING": 0}
    for x in results:
        count[x["risk"]["level"]] += 1
    return {"safe": count["SAFE"], "caution": count["CAUTION"], "warning": count["WARNING"],
            "safe_menus": [x["menu"] for x in results if x["risk"]["level"] == "SAFE"][:5]}


def maps_url(r: dict) -> str:
    """구글 지도 링크. 키 없이도 만들 수 있다(공식 Maps URL). place_id가 있으면 정확한 가게로 열린다."""
    q = quote(" ".join(x for x in (r.get("name"), r.get("area"), "부산") if x))
    url = f"https://www.google.com/maps/search/?api=1&query={q}"
    return url + f"&query_place_id={r['google_place_id']}" if r.get("google_place_id") else url


def _public(r: dict) -> dict:
    return {**{k: r.get(k) for k in ("id", "name", "area", "category", "name_confirmed")}, "maps_url": maps_url(r)}


def search(profile: DietProfile, q: str = "", only_edible: bool = False, sort: str = "rating") -> list[dict]:
    """식당 목록 + 내 프로필 기준 판정 요약 + 구글 평점.

    sort: rating(구글 평점 높은 순, 평점 없는 식당은 뒤) | edible(먹을 수 있는 메뉴 많은 순)
    only_edible: 먹을 수 있는(SAFE) 메뉴가 하나라도 있는 식당만
    """
    rows = [r for r in load_restaurants() if _matches(r, q)]
    items = []
    for r in rows:
        s = _summary(judge_menus(r, profile))
        if only_edible and s["safe"] == 0:
            continue
        items.append({**_public(r), "summary": s, "_place_id": r.get("google_place_id")})
    ratings = google_places.get_ratings([i.pop("_place_id") for i in items])
    for i, g in zip(items, ratings):
        i["google"] = g
    if sort == "edible":
        items.sort(key=lambda i: (-i["summary"]["safe"], i["summary"]["warning"]))
    else:
        items.sort(key=lambda i: (i["google"] is None, -((i["google"] or {}).get("rating") or 0),
                                  -i["summary"]["safe"]))
    return items


def detail(restaurant_id: str, profile: DietProfile) -> dict | None:
    r = next((x for x in load_restaurants() if x["id"] == restaurant_id), None)
    if not r:
        return None
    results = judge_menus(r, profile)
    order = {"SAFE": 0, "CAUTION": 1, "WARNING": 2}
    return {
        **_public(r),
        "summary": _summary(results),
        "google": google_places.get_rating(r.get("google_place_id")),
        "results": sorted(results, key=lambda x: order[x["risk"]["level"]]),
    }
