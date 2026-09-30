"""메뉴판에 인쇄된 재료 문구를 재료 목록으로 바꾼다.

부산 식당 메뉴판에는 메뉴명 옆·아래 괄호로 재료가 적힌 경우가 많다.

    돌 게 탕  (전복2, 가리비2, 오징어中, 꽃게, 새우2, 낙지, 대구, 알, 곤, 조개다수)

가게가 자기 레시피를 직접 적어둔 것이므로, 공공데이터 유사 레시피나 AI 추론보다
우선한다(certainty=confirmed). 실사용 검증에서 나온 SAFE 오판 3건이 모두
"메뉴판에 새우가 적혀 있는데 읽지 않아서" 발생했다.

재료명을 자유롭게 파싱하지 않고 태그를 붙일 수 있는 키워드만 뽑는다.
원산지·수량·인분 표기(국내산, 3~4인분, 1000g)를 파싱하려다 오탐을 만드는 것보다,
알레르기 판정에 쓰이는 재료만 확실히 잡는 편이 안전하다.
"""
import re
import unicodedata

from app.services.ingredient_lexicon import DIRECT_RULES

SOURCE = "menu_board"

# 메뉴판 괄호에 자주 나오지만 DIRECT_RULES(AI 재료명 보정용)에는 없는 해산물.
# DIRECT_RULES에 넣으면 AI 재료명에도 적용돼 오탐이 생길 수 있어 메뉴판 전용으로 둔다.
BOARD_RULES: list[tuple[str, list[str]]] = [
    ("대게", ["crab"]), ("홍게", ["crab"]), ("킹크랩", ["crab"]), ("돌게", ["crab"]), ("털게", ["crab"]),
    ("대구", ["fish"]), ("명태", ["fish"]), ("동태", ["fish"]), ("생태", ["fish"]), ("황태", ["fish"]),
    ("우럭", ["fish"]), ("광어", ["fish"]), ("도미", ["fish"]), ("아귀", ["fish"]), ("아구", ["fish"]),
    ("코다리", ["fish"]), ("갈치", ["fish"]),
    ("굴", ["shellfish"]), ("꼬막", ["shellfish"]), ("소라", ["shellfish"]), ("담치", ["shellfish"]),
    ("재첩", ["shellfish"]), ("키조개", ["shellfish"]), ("관자", ["shellfish"]),
]

# 재료 설명이 아니라 원산지·수량·안내 문구만 있는 칸은 무시한다.
_NOISE_ONLY = ("인분", "이상", "미만", "원산지", "주문", "포장", "예약")


def parse(note: str | None) -> list[dict]:
    """괄호 안 재료 문구 → confirmed 재료 목록.

    >>> [i["name"] for i in parse("전복2,가리비2,꽃게,새우2,낙지,조개다수")]
    ['꽃게', '새우', '전복', '조개', '가리비']
    >>> parse("(3~4인분) 국내산 2마리 400g이상")
    []
    """
    if not note or not note.strip():
        return []
    # OCR이 글자 사이에 공백을 넣는 경우가 있다: "새 우 2, 꽃 게" → "새우2,꽃게"
    text = re.sub(r"\s+", "", unicodedata.normalize("NFKC", note))
    found: dict[str, set[str]] = {}
    for keyword, tags in DIRECT_RULES + BOARD_RULES:
        if keyword in text:
            found.setdefault(keyword, set()).update(tags)
    return [
        {
            "name": name,
            "name_translated": None,
            "tags": sorted(tags),
            "certainty": "confirmed",
            "source": SOURCE,
            "ratio_percent": None,
            "seen_in": ["메뉴판 표기"],
        }
        for name, tags in found.items()
    ]


def apply(ingredients: list[dict], note: str | None) -> list[dict]:
    """메뉴판 표기 재료를 기존 재료 목록에 얹는다.

    같은 태그를 이미 possible로 들고 있으면 confirmed로 올리고,
    아예 없으면 새 재료로 추가한다. 메뉴판에 적힌 것을 지우지는 않는다.
    """
    board = parse(note)
    if not board:
        return ingredients

    out = [dict(i) for i in ingredients]
    by_name = {i.get("name"): i for i in out}
    confirmed_tags = {t for i in out if i.get("certainty") == "confirmed" for t in (i.get("tags") or [])}

    for b in board:
        existing = by_name.get(b["name"])
        if existing is not None:
            # 이름이 같은 재료가 이미 있으면 확정으로 승격 (근거만 메뉴판으로 교체)
            existing["certainty"] = "confirmed"
            existing["source"] = SOURCE
            existing["tags"] = sorted(set(existing.get("tags") or []) | set(b["tags"]))
            existing["seen_in"] = ["메뉴판 표기"]
            continue
        if set(b["tags"]) <= confirmed_tags:
            continue  # 다른 이름으로 이미 확정된 태그면 중복 추가하지 않음
        out.append(b)
        by_name[b["name"]] = b
        confirmed_tags |= set(b["tags"])
    return out
