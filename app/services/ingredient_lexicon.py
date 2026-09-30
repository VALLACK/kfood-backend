"""재료명 키워드 → 태그 보정.

AI가 태그를 빠뜨려도(예: '김치'에 새우젓/액젓 태그 누락) 규칙으로 보완한다.
알레르기 안전과 직결되므로 AI 결과를 믿기만 하지 않는다.
"""

# (키워드, 추가할 태그)
DIRECT_RULES: list[tuple[str, list[str]]] = [
    ("간장", ["soy", "wheat"]), ("고추장", ["soy", "wheat"]), ("춘장", ["soy", "wheat"]),
    ("된장", ["soy"]), ("쌈장", ["soy", "wheat"]), ("두부", ["soy"]), ("콩나물", ["soy"]),
    ("어묵", ["fish", "wheat"]), ("오뎅", ["fish", "wheat"]),
    ("게맛살", ["fish", "crab"]), ("게장", ["crab"]), ("꽃게", ["crab"]),
    ("새우", ["shrimp"]),
    ("멸치", ["fish"]), ("액젓", ["fish"]), ("까나리", ["fish"]), ("참치", ["fish"]),
    ("연어", ["fish"]), ("생선", ["fish"]), ("고등어", ["fish", "mackerel"]), ("가쓰오", ["fish"]),
    ("오징어", ["squid"]), ("낙지", ["mollusk"]), ("문어", ["mollusk"]), ("주꾸미", ["mollusk"]),
    ("굴소스", ["shellfish"]), ("조개", ["shellfish"]), ("바지락", ["shellfish"]),
    ("홍합", ["shellfish"]), ("전복", ["shellfish"]), ("가리비", ["shellfish"]),
    ("햄", ["pork"]), ("베이컨", ["pork"]), ("소시지", ["pork"]), ("스팸", ["pork"]),
    ("돼지", ["pork"]), ("삼겹", ["pork"]), ("순대", ["pork"]),
    ("항정살", ["pork"]), ("목살", ["pork"]), ("갈매기살", ["pork"]),
    ("보쌈", ["pork"]), ("족발", ["pork"]), ("차슈", ["pork"]),
    ("돈까스", ["pork"]), ("돈가스", ["pork"]), ("돈카츠", ["pork"]),
    ("소고기", ["beef"]), ("쇠고기", ["beef"]), ("차돌", ["beef"]), ("한우", ["beef"]), ("사골", ["beef"]),
    ("닭", ["chicken"]),
    ("계란", ["egg"]), ("달걀", ["egg"]), ("마요네즈", ["egg"]), ("메추리알", ["egg"]),
    ("치즈", ["milk"]), ("버터", ["milk"]), ("크림", ["milk"]), ("우유", ["milk"]),
    ("밀가루", ["wheat"]), ("부침가루", ["wheat"]), ("튀김가루", ["wheat"]), ("빵가루", ["wheat"]),
    ("메밀", ["buckwheat"]), ("땅콩", ["peanut"]), ("호두", ["walnut"]), ("잣", ["pine_nut"]),
    ("참기름", ["sesame"]), ("참깨", ["sesame"]),
    ("맛술", ["alcohol"]), ("미림", ["alcohol"]), ("청주", ["alcohol"]), ("요리주", ["alcohol"]),
    ("소주", ["alcohol"]), ("와인", ["alcohol"]), ("맥주", ["alcohol"]),
    ("젤라틴", ["animal_gelatin"]), ("토마토", ["tomato"]), ("케첩", ["tomato"]), ("복숭아", ["peach"]),
]

# 재료 안에 '숨은 재료'가 들어있는 경우 → 별도 possible 재료로 추가
DERIVED_RULES: list[tuple[str, dict]] = [
    ("김치", {"name": "김치 속 젓갈(새우젓·액젓)", "name_translated": "fermented seafood in kimchi (shrimp paste, fish sauce)", "tags": ["shrimp", "fish"]}),
]


def enrich(ingredients: list[dict]) -> list[dict]:
    """AI 재료(source=ai)에 키워드 태그를 보강하고, 숨은 재료를 추가한다."""
    out = []
    names = {i.get("name") for i in ingredients}
    for ing in ingredients:
        name = ing.get("name") or ""
        if ing.get("source") == "ai":
            tags = list(ing.get("tags") or [])
            for kw, add in DIRECT_RULES:
                if kw in name:
                    tags += [t for t in add if t not in tags]
            ing = {**ing, "tags": tags}
        out.append(ing)
        for kw, derived in DERIVED_RULES:
            if kw in name and derived["name"] not in names and "젓갈" not in name and "액젓" not in name:
                out.append({**derived, "certainty": "possible", "source": "lexicon", "ratio_percent": None})
                names.add(derived["name"])
    return out
