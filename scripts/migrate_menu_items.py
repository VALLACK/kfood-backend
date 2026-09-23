"""app/data/menu_base.json 을 Supabase menu_items 테이블로 이관.

menu_items 쓰기는 RLS 정책상 secret key(sb_secret_...)로만 가능하다.
SUPABASE_SECRET_KEY 값은 각자 .env에 직접 작성해야 한다.

사용법:
  python -m scripts.migrate_menu_items --dry-run   # 반영 없이 변환 결과만 출력
  python -m scripts.migrate_menu_items --yes       # 실제 반영 (확인 절차 통과 필요)

주의: menu_base.json 팀 검수가 완료된 뒤에만 --yes로 실행할 것.
같은 name으로 재실행하면 upsert(on_conflict="name")로 덮어쓴다.
"""
import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

DATA_PATH = Path(__file__).resolve().parent.parent / "app" / "data" / "menu_base.json"

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY")


def get_secret_client():
    if not SUPABASE_URL:
        raise SystemExit("SUPABASE_URL이 .env에 없습니다.")
    if not SECRET_KEY:
        raise SystemExit(
            "SUPABASE_SECRET_KEY가 .env에 없습니다.\n"
            "Supabase 대시보드 > Settings > API Keys에서 secret key(sb_secret_...)를 확인해 "
            ".env에 직접 추가하세요 (혹은 팀 채널로 전달받고 추가하세요. 이 값은 절대 커밋하지 마세요)."
        )
    if not SECRET_KEY.startswith("sb_secret_"):
        print(
            f"경고: SUPABASE_SECRET_KEY가 예상 형식(sb_secret_...)이 아닙니다. "
            f"publishable 키를 잘못 넣지 않았는지 확인하세요."
        )
    return create_client(SUPABASE_URL, SECRET_KEY)


def build_rows(menus: dict[str, dict]) -> list[dict]:
    rows = []
    for name, item in menus.items():
        rows.append({
            "name": name,
            "aliases": item.get("aliases", []),
            "category": item.get("category"),
            "required_ingredients": item.get("required", []),
            "hidden_ingredients": item.get("hidden", []),
            "variants": item.get("variants", []),
        })
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="DB에 반영하지 않고 변환 결과만 출력")
    parser.add_argument("--yes", action="store_true", help="실제 DB 반영을 확정 (없으면 안전을 위해 실행 거부)")
    args = parser.parse_args()

    with open(DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)

    menus = data.get("menus", {})
    rows = build_rows(menus)

    print(f"총 {len(rows)}개 메뉴를 이관합니다: {', '.join(r['name'] for r in rows)}")

    if args.dry_run:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return

    if not args.yes:
        raise SystemExit(
            "실수 방지를 위해 --yes 없이는 실행하지 않습니다.\n"
            "먼저 --dry-run으로 결과를 확인한 뒤, 검수 완료 후 --yes를 붙여 실행하세요."
        )

    client = get_secret_client()
    res = client.table("menu_items").upsert(rows, on_conflict="name").execute()
    print(f"완료: {len(res.data)}개 행 반영됨")


if __name__ == "__main__":
    main()