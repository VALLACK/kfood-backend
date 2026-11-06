"""평가 때 읽은 메뉴판으로 '미리 알아보기'용 식당 데이터(app/data/restaurants.json)를 만든다.

    python -m scripts.build_restaurants            # docs/eval_1005_raw.json.gz 기준

- 메뉴는 10/05 평가 때 OCR이 읽은 결과를 쓴다(괄호 속 재료 note 포함).
- 메뉴마다 그때 AI가 답한 재료(ai)를 같이 저장한다 → 검색할 때 AI를 다시 부르지 않는다.
- 판정(🔴🟡🟢)은 저장하지 않는다. 검색할 때 사용자 프로필로 매번 새로 계산한다.
- 구글 평점은 저장하지 않는다(구글 정책). 식당 ID(google_place_id)만 저장하고,
  scripts/find_place_ids.py로 채운다.
- 이미 restaurants.json이 있으면 사람이 고친 name·area·google_place_id는 유지한다.
"""
import argparse
import gzip
import json
from pathlib import Path

from app.routers.ocr import _is_drink
from scripts.replay_eval import _stored_ai_answers

OUT = Path(__file__).resolve().parent.parent / "app" / "data" / "restaurants.json"

# 사진 → 식당 정보. name_confirmed=False인 식당은 사진에 상호가 없거나 흐려서 팀 확인이 필요하다.
PHOTOS = {
    "193106": {"id": "hadan-dolgetang", "name": "하단 돌게탕", "area": "사하구 하단동", "category": "해물탕", "name_confirmed": True},
    "193307": {"id": "haemulnara", "name": "해물나라 총각집", "area": "", "category": "조개구이", "name_confirmed": True},
    "193320": {"id": "chakhan-gukbap", "name": "착한국밥", "area": "", "category": "국밥", "name_confirmed": True},
    "193336": {"id": "osaka", "name": "오사카", "area": "", "category": "일식", "name_confirmed": True},
    "193353": {"id": "katsuan", "name": "카츠안", "area": "", "category": "돈까스", "name_confirmed": True},
    "200045": {"id": "gaemijip-gwangalli", "name": "개미집 광안리 본점", "area": "수영구 광안리", "category": "낙곱새", "name_confirmed": True},
    "200119": {"id": "subaekdang", "name": "수백당", "area": "", "category": "국밥", "name_confirmed": True},
}
KEEP = ("name", "area", "category", "google_place_id", "name_confirmed")


def _i(name, en, tags, certainty="confirmed"):
    return {"name": name, "name_translated": en, "tags": tags, "certainty": certainty, "ratio_percent": None}


# 평가 채점(docs/eval_1005_scored.csv)에서 메뉴명이 틀린 것(X)으로 나온 항목.
# 없는 메뉴·중복·음료 칸 오인식은 빼고, 실제 메뉴를 알 수 있는 건 이름과 재료(manual)를 바로잡는다.
MENU_DROP = {
    "hadan-dolgetang": {"대구알2,라2", "란전", "맑은국 우동,곤약사리", "산소라구이", "산우럭구이", "통나무죽"},
    "osaka": {"단타카토나, 키티"},
}
MENU_FIX = {
    ("hadan-dolgetang", "산눈지방탕탕이"): ("산낙지탕탕이", "Raw live octopus (sannakji)", [
        _i("산낙지", "live octopus", ["mollusk"]), _i("참기름", "sesame oil", []),
        _i("마늘", "garlic", [], "possible"), _i("소금", "salt", [])]),
    ("osaka", "달걀밥"): ("닭덮밥", "Chicken rice bowl (oyakodon style)", [   # 원래 '닭덮밥' — 달걀밥으로 읽혀 할랄에 SAFE가 났다
        _i("닭고기", "chicken", ["chicken"]), _i("달걀", "egg", ["egg"]), _i("간장", "soy sauce", ["soy", "wheat"]),
        _i("맛술", "cooking wine", ["alcohol"], "possible"), _i("쌀밥", "rice", []), _i("양파", "onion", [])]),
    ("subaekdang", "삼겹데지국밥"): ("삼겹돼지국밥", "Pork belly gukbap (pork soup with rice)", [
        _i("돼지 삼겹살", "pork belly", ["pork"]), _i("돼지뼈 육수", "pork bone broth", ["pork"]),
        _i("새우젓", "salted shrimp", ["shrimp"], "possible"), _i("쌀밥", "rice", []), _i("부추", "chives", [], "possible")]),
}


def _fix_menus(rid: str, menus: list[dict]) -> list[dict]:
    out = []
    for m in menus:
        if m["name"] in MENU_DROP.get(rid, set()):
            continue
        m["prices"] = [p.lstrip("W₩").strip() for p in m["prices"]]
        fix = MENU_FIX.get((rid, m["name"]))
        if fix:
            name, en, ings = fix
            m.update(name=name, ai=None, manual={"menu": name, "menu_translated": en, "ingredients": ings})
            m.pop("ai")
        out.append(m)
    return out


def build(raw: list[dict], old: dict[str, dict]) -> list[dict]:
    ai = _stored_ai_answers(raw)
    seen_photo = set()
    restaurants = []
    for blk in raw:
        key = blk["photo"][-10:-4]
        if key in seen_photo or key not in PHOTOS or not blk.get("ocr", {}).get("menus"):
            continue
        seen_photo.add(key)
        meta = {**PHOTOS[key], "google_place_id": None}
        prev = old.get(meta["id"], {})
        meta.update({k: prev[k] for k in KEEP if prev.get(k) not in (None, "")})

        menus: dict[str, dict] = {}
        for m in blk["ocr"]["menus"]:
            name = m["name"]
            if _is_drink(name):
                continue
            item = menus.setdefault(name, {"name": name, "prices": [], "note": m.get("note"), "ai": None})
            if m.get("price") and m["price"] not in item["prices"]:
                item["prices"].append(m["price"])
            if not item["note"] and m.get("note"):
                item["note"] = m["note"]
            if name in ai and ai[name]["ingredients"]:
                a = ai[name]
                item["ai"] = {"menu": name, "menu_translated": a.get("menu_translated"),
                              "ingredients": [{k: i.get(k) for k in ("name", "name_translated", "tags", "certainty", "ratio_percent")}
                                              for i in a["ingredients"]]}
        restaurants.append({**meta, "source": f"10/05 평가 메뉴판 사진 {blk['photo']}",
                            "menus": _fix_menus(meta["id"], list(menus.values()))})
    return restaurants


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="docs/eval_1005_raw.json.gz")
    args = ap.parse_args()
    with gzip.open(args.raw, "rt", encoding="utf-8") as f:
        raw = json.load(f)
    old = {}
    if OUT.exists():
        old = {r["id"]: r for r in json.loads(OUT.read_text(encoding="utf-8")).get("restaurants", [])}
    built = build(raw, old)
    ids = {r["id"] for r in built}
    # 사진 평가와 상관없이 추가한 식당(add_restaurant.py·수기 입력)은 그대로 둔다
    built += [r for r in old.values() if r["id"] not in ids]
    data = {
        "_comment": "미리 알아보기용 식당 데이터. 판정·평점은 저장하지 않고 요청 때 계산/조회한다. "
                    "메뉴 재료: ai=AI 답변, manual=팀이 일반 레시피 기준으로 직접 입력.",
        "restaurants": built,
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    rs = data["restaurants"]
    print(f"식당 {len(rs)}곳, 메뉴 {sum(len(r['menus']) for r in rs)}개 → {OUT}")
    for r in rs:
        flag = "" if r["name_confirmed"] else "  ← 상호 확인 필요"
        print(f"  {r['id']:22s} {r['name']}  메뉴 {len(r['menus'])}개{flag}")


if __name__ == "__main__":
    main()
