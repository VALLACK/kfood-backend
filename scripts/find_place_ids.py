"""저장된 식당의 구글 식당 ID(place_id)를 찾아 app/data/restaurants.json에 채운다.

구글 정책상 평점은 저장하면 안 되지만 place_id는 저장해도 된다.
평점은 앱이 보여줄 때마다 이 ID로 새로 불러온다(app/services/google_places.py).

    python -m scripts.find_place_ids            # 후보만 보기 (파일은 안 바꿈)
    python -m scripts.find_place_ids --write    # 1순위 후보를 파일에 저장
    python -m scripts.find_place_ids --set katsuan=ChIJxxxx   # 직접 지정

- .env의 GOOGLE_MAPS_API_KEY 필요
- 상호를 확인하지 않은 식당(name_confirmed=false)은 건너뛴다 → restaurants.json에서 이름부터 고칠 것
- 이 검색은 ID·이름·주소만 받아서 평점 조회보다 무료 사용량이 넉넉하다
"""
import argparse
import json
import sys

import httpx

from app.core.config import settings
from app.services.restaurant_service import DATA_PATH

URL = "https://places.googleapis.com/v1/places:searchText"
FIELDS = "places.id,places.displayName,places.formattedAddress"


def search(query: str) -> list[dict]:
    r = httpx.post(URL, json={"textQuery": query, "languageCode": "ko", "regionCode": "KR"},
                   headers={"X-Goog-Api-Key": settings.GOOGLE_MAPS_API_KEY, "X-Goog-FieldMask": FIELDS},
                   timeout=10)
    r.raise_for_status()
    return [{"id": p["id"], "name": (p.get("displayName") or {}).get("text", ""), "address": p.get("formattedAddress", "")}
            for p in r.json().get("places", [])][:3]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="1순위 후보를 restaurants.json에 저장")
    ap.add_argument("--set", nargs="*", default=[], metavar="식당ID=place_id", help="직접 지정")
    args = ap.parse_args(argv)

    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in data["restaurants"]}
    changed = False

    for pair in args.set:
        rid, _, pid = pair.partition("=")
        if rid not in by_id or not pid:
            sys.exit(f"형식 오류 또는 없는 식당: {pair}  (예: katsuan=ChIJxxxx)")
        by_id[rid]["google_place_id"] = pid
        changed = True
        print(f"지정: {rid} → {pid}")

    if not args.set:
        if not settings.GOOGLE_MAPS_API_KEY:
            sys.exit("GOOGLE_MAPS_API_KEY가 .env에 없습니다.")
        for r in data["restaurants"]:
            if r.get("google_place_id"):
                print(f"[완료] {r['name']}: {r['google_place_id']}")
                continue
            if not r.get("name_confirmed"):
                print(f"[건너뜀] {r['name']}: 상호를 먼저 확인해서 restaurants.json의 name을 고치고 name_confirmed를 true로")
                continue
            query = f"{r['name']} {r.get('area', '')} 부산".strip()
            cands = search(query)
            print(f"\n[{r['id']}] '{query}' 검색 결과:")
            for k, c in enumerate(cands, 1):
                print(f"   {k}. {c['name']} | {c['address']} | {c['id']}")
            if not cands:
                print("   (결과 없음 — area를 채우거나 --set으로 직접 지정)")
            elif args.write:
                r["google_place_id"] = cands[0]["id"]
                changed = True
                print(f"   → 1번을 저장. 틀렸으면 --set {r['id']}=올바른ID 로 고치기")

    if changed:
        DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"\n저장됨: {DATA_PATH}")


if __name__ == "__main__":
    main()
