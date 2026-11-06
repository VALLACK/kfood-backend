"""메뉴판 사진으로 '미리 알아보기' 식당을 추가한다 (학교 주변 식당 등).

서버를 켠 상태에서 실행한다. 사진 읽기(OCR)와 재료 분석에 AI를 쓰므로 Groq 사용량이 든다
(메뉴판 1장당 사진 읽기 1번 + 분석 1번). 한 번 등록하면 검색할 때는 AI를 다시 부르지 않는다.

    python -m scripts.add_restaurant --id pknu-gukbap --name "○○국밥" --area "남구 대연동" ^
        --category 국밥 --photo photos\\school\\gukbap1.jpg photos\\school\\gukbap2.jpg

- 같은 --id로 다시 실행하면 그 식당을 새 결과로 바꾼다(google_place_id는 유지).
- 메뉴판이 여러 장이면 --photo에 모두 넣는다.
- 등록 후 구글 ID 채우기: python -m scripts.find_place_ids --write
"""
import argparse
import json
import mimetypes
import sys
from pathlib import Path

import httpx

from app.routers.ocr import _is_drink
from app.services.restaurant_service import DATA_PATH

KEEP_SOURCES = (None, "ai", "menu_board")   # 프로필과 무관한 재료(AI 답변·메뉴판 표기)만 저장


def read_menus(client: httpx.Client, api: str, photos: list[Path]) -> list[dict]:
    menus: dict[str, dict] = {}
    for p in photos:
        mime = mimetypes.guess_type(p.name)[0] or "image/jpeg"
        r = client.post(f"{api}/ocr", files={"file": (p.name, p.read_bytes(), mime)})
        r.raise_for_status()
        body = r.json()
        if body.get("truncated"):
            print(f"  ⚠ {p.name}: 메뉴가 많아 일부만 읽었습니다. 메뉴판을 나눠 찍어 다시 넣으세요.")
        for m in body.get("menus", []):
            if _is_drink(m["name"]):
                continue
            item = menus.setdefault(m["name"], {"name": m["name"], "prices": [], "note": m.get("note"), "ai": None})
            if m.get("price") and m["price"] not in item["prices"]:
                item["prices"].append(m["price"])
            item["note"] = item["note"] or m.get("note")
        print(f"  {p.name}: 메뉴 {len(body.get('menus', []))}개 읽음")
    return list(menus.values())


def attach_ai(client: httpx.Client, api: str, menus: list[dict], lang: str) -> None:
    body = {"menus": [{"name": m["name"], "note": m["note"]} for m in menus],
            "profile": {"preferred_language": lang}}
    r = client.post(f"{api}/analyze", json=body)
    r.raise_for_status()
    by_name = {x["menu"]: x for x in r.json()["results"]}
    for m in menus:
        x = by_name.get(m["name"])
        if not x or x.get("provisional"):
            continue   # AI가 답하지 못한 메뉴 → 저장하지 않으면 검색 때 '직원 확인'으로 나온다
        ings = [{k: i.get(k) for k in ("name", "name_translated", "tags", "certainty", "ratio_percent")}
                for i in x.get("ingredients", []) if i.get("source") in KEEP_SOURCES]
        if ings or x.get("menu_translated"):   # 공공데이터 메뉴도 번역명은 남긴다
            m["ai"] = {"menu": m["name"], "menu_translated": x.get("menu_translated"), "ingredients": ings}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True, help="영문 소문자·하이픈 (예: pknu-gukbap)")
    ap.add_argument("--name", required=True)
    ap.add_argument("--area", default="")
    ap.add_argument("--category", default="")
    ap.add_argument("--photo", nargs="+", required=True)
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--lang", default="en", choices=["en", "ko", "zh", "ja"])
    args = ap.parse_args(argv)

    photos = [Path(p) for p in args.photo]
    for p in photos:
        if not p.exists():
            sys.exit(f"사진이 없습니다: {p}")

    with httpx.Client(timeout=300) as client:
        print(f"[{args.name}] 메뉴판 읽는 중...")
        menus = read_menus(client, args.api, photos)
        if not menus:
            sys.exit("읽은 메뉴가 없습니다. 사진을 확인하세요.")
        print(f"[{args.name}] 재료 분석 중 (메뉴 {len(menus)}개)...")
        attach_ai(client, args.api, menus, args.lang)

    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    old = next((r for r in data["restaurants"] if r["id"] == args.id), {})
    entry = {"id": args.id, "name": args.name, "area": args.area, "category": args.category,
             "name_confirmed": True, "google_place_id": old.get("google_place_id"),
             "source": "메뉴판 사진 " + ", ".join(p.name for p in photos), "menus": menus}
    data["restaurants"] = [r for r in data["restaurants"] if r["id"] != args.id] + [entry]
    DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    no_ai = sum(1 for m in menus if not m["ai"])
    print(f"저장 완료: {args.name} 메뉴 {len(menus)}개 (재료 정보 없음 {no_ai}개 → 검색 때 '직원 확인'으로 표시)")


if __name__ == "__main__":
    main()
