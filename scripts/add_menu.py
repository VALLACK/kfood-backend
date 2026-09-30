"""검수한 메뉴를 자체 메뉴 DB(app/data/menu_base.json)에 추가한다.

사용 예:
    python -m scripts.add_menu --list                          # 검수 대기 메뉴 보기(빈도순)
    python -m scripts.add_menu "돈까스" ^
        --required "돼지고기:pork" "빵가루:wheat" "달걀:egg" ^
        --hidden "돈까스소스:wheat,soy" ^
        --alias "돈가스" "포크커틀릿"
    python -m scripts.add_menu "짜장면" --required "면:wheat" --variant "해물짜장:해물:오징어:squid"

태그 목록은 app/services/taxonomy.py 의 TAGS 참고 (pork, beef, chicken, fish, shrimp, crab,
squid, shellfish, egg, milk, wheat, buckwheat, soy, peanut, walnut, sesame, alcohol ...)
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.services.taxonomy import TAGS  # noqa: E402
from app.services import unmatched_log  # noqa: E402

DB = Path(__file__).resolve().parent.parent / "app" / "data" / "menu_base.json"


def parse_ing(spec: str) -> dict:
    """'돼지고기:pork' 또는 '간장:soy,wheat' → {"name": ..., "tags": [...]}"""
    name, _, tags = spec.partition(":")
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    for t in tag_list:
        if t not in TAGS:
            sys.exit(f"알 수 없는 태그: {t}\n사용 가능: {', '.join(TAGS)}")
    return {"name": name.strip(), "tags": tag_list}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("menu", nargs="?", help="추가할 메뉴명")
    ap.add_argument("--required", nargs="*", default=[], help="필수 재료 '이름:태그[,태그]'")
    ap.add_argument("--hidden", nargs="*", default=[], help="가게마다 다를 수 있는 재료")
    ap.add_argument("--variant", nargs="*", default=[],
                    help="변형 '변형명:키워드:재료명:태그' (예: 해물짜장:해물:오징어:squid)")
    ap.add_argument("--alias", nargs="*", default=[], help="별칭")
    ap.add_argument("--category", default="")
    ap.add_argument("--list", action="store_true", help="검수 대기 메뉴 목록만 보기")
    args = ap.parse_args()

    if args.list:
        rows = unmatched_log.top(30, status="대기")
        if not rows:
            print("검수 대기 메뉴가 없습니다. (/analyze를 돌리면 쌓입니다)")
            return
        print(f'{"메뉴":<20}{"발생":>5}  최근')
        for r in rows:
            print(f'{r["menu"]:<20}{r["count"]:>5}  {r.get("last_seen", "")[:10]}')
        return

    if not args.menu or not args.required:
        sys.exit("메뉴명과 --required 는 필수입니다. 예: python -m scripts.add_menu \"돈까스\" --required \"돼지고기:pork\"")

    data = json.loads(DB.read_text(encoding="utf-8"))
    menus = data["menus"]
    variants = []
    for v in args.variant:
        parts = v.split(":")
        if len(parts) < 4:
            sys.exit(f"변형 형식 오류: {v} (변형명:키워드:재료명:태그)")
        variants.append({"name": parts[0], "keywords": [parts[1]],
                         "ingredients": [parse_ing(f"{parts[2]}:{parts[3]}")]})

    entry = {
        "aliases": args.alias,
        "category": args.category,
        "required": [parse_ing(x) for x in args.required],
        "hidden": [parse_ing(x) for x in args.hidden],
        "variants": variants,
    }
    exists = args.menu in menus
    menus[args.menu] = entry
    DB.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    unmatched_log.mark_added(args.menu)
    print(f'{"수정" if exists else "추가"} 완료: {args.menu}')
    print(f'  필수 {len(entry["required"])}개 · 숨은 {len(entry["hidden"])}개 · 변형 {len(variants)}개')
    print("서버를 재시작하면 반영됩니다.")


if __name__ == "__main__":
    main()
