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
                            "menus": list(menus.values())})
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
    data = {
        "_comment": "미리 알아보기용 식당 데이터. 판정·평점은 저장하지 않고 요청 때 계산/조회한다. "
                    "name_confirmed=false인 식당은 상호를 확인해서 고칠 것.",
        "restaurants": build(raw, old),
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    rs = data["restaurants"]
    print(f"식당 {len(rs)}곳, 메뉴 {sum(len(r['menus']) for r in rs)}개 → {OUT}")
    for r in rs:
        flag = "" if r["name_confirmed"] else "  ← 상호 확인 필요"
        print(f"  {r['id']:22s} {r['name']}  메뉴 {len(r['menus'])}개{flag}")


if __name__ == "__main__":
    main()
