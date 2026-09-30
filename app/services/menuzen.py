"""농촌진흥청 메뉴젠(음식·재료·알레르기) 데이터 파싱·정규화.

- scripts/fetch_menuzen.py 가 API 전체를 받아 이 모듈로 정규화해 app/data/menuzen_menus.json 생성
"""
import re
import xml.etree.ElementTree as ET

from app.services.ingredient_lexicon import DIRECT_RULES

# allrgy_Info 문자열 → 태그 (긴 키워드 먼저 처리해서 '메밀'이 '밀'로 잡히지 않게)
ALLERGY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("어패류", ["shellfish"]), ("조개류", ["shellfish"]),
    ("메밀", ["buckwheat"]), ("고등어", ["fish", "mackerel"]), ("돼지고기", ["pork"]),
    ("쇠고기", ["beef"]), ("소고기", ["beef"]), ("닭고기", ["chicken"]), ("복숭아", ["peach"]),
    ("토마토", ["tomato"]), ("아황산", ["sulfite"]), ("호두", ["walnut"]), ("땅콩", ["peanut"]),
    ("오징어", ["squid"]), ("새우", ["shrimp"]), ("난류", ["egg"]), ("알류", ["egg"]),
    ("우유", ["milk"]), ("대두", ["soy"]), ("잣", ["pine_nut"]), ("게", ["crab"]), ("밀", ["wheat"]),
]

# 알레르기 칸이 비어 있어도 식품군으로 보완 (할랄·비건 판정용)
SEAFOOD_NAME_RULES = [
    ("새우", "shrimp"), ("꽃게", "crab"), ("대게", "crab"), ("게,", "crab"), ("오징어", "squid"),
    ("문어", "mollusk"), ("낙지", "mollusk"), ("주꾸미", "mollusk"), ("굴,", "shellfish"),
    ("전복", "shellfish"), ("홍합", "shellfish"), ("담치", "shellfish"), ("조개", "shellfish"),
    ("바지락", "shellfish"), ("가리비", "shellfish"), ("고등어", "mackerel"),
]
MEAT_NAME_RULES = [("돼지", "pork"), ("소고기", "beef"), ("쇠고기", "beef"), ("닭", "chicken")]

SEASONING_GROUPS = {"조미료류", "유지류", "주류", "당류"}


def allergy_to_tags(text: str | None) -> list[str]:
    if not text or text == "null":
        return []
    s, tags = text, []
    for kw, add in ALLERGY_KEYWORDS:
        if kw in s:
            tags += [t for t in add if t not in tags]
            s = s.replace(kw, "")
    return tags


def ingredient_tags(name: str, group: str | None, allergy: str | None) -> list[str]:
    tags = allergy_to_tags(allergy)

    def add(*ts):
        for t in ts:
            if t not in tags:
                tags.append(t)

    group = group or ""
    if group.startswith("어패류"):
        hit = [t for kw, t in SEAFOOD_NAME_RULES if kw in name]
        add(*(hit or ["fish"]))
        if "mackerel" in hit:
            add("fish")
    elif group == "육류":
        hit = [t for kw, t in MEAT_NAME_RULES if kw in name]
        add(*(hit or ["other_meat"]))
    elif group == "주류":
        add("alcohol")
    elif group == "난류":
        add("egg")
    elif group.startswith("우유"):
        add("milk")
    for kw, extra in DIRECT_RULES:  # 간장→밀, 청주→술 등 공공데이터 누락 보정
        if kw in name:
            add(*extra)
    return tags


def short_name(food_nm: str) -> str:
    """'새우, 꽃새우, 생것' → '새우', '담치, 참담치(홍합), 생것' → '홍합'"""
    m = re.search(r"\(([^)]+)\)", food_nm)
    first = food_nm.split(",")[0].strip()
    if m and first in ("담치", "대나무순"):
        return m.group(1)
    return first


def _text(el, tag):
    v = el.findtext(tag)
    return None if v is None or v.strip() in ("", "null") else v.strip()


def parse_xml(xml_text: str) -> tuple[int, list[dict]]:
    """API 응답 XML → (total_count, [dish, ...])"""
    root = ET.fromstring(xml_text)
    code = root.findtext("header/result_Code")
    if code == "301":  # 요청 데이터 없음
        return 0, []
    if code != "200":
        raise ValueError(f"메뉴젠 API 오류 {code}: {root.findtext('header/result_Msg')}")
    total = int(root.findtext("body/total_Count") or 0)
    dishes = []
    for item in root.iter("item"):
        foods = []
        for f in item.iter("food"):
            name = _text(f, "food_Nm") or ""
            group = _text(f, "nation_Std_Food_Grupp_Code_Nm")
            allergy = _text(f, "allrgy_Info")
            foods.append({
                "food_code": _text(f, "food_Code"),
                "name": name,
                "short": short_name(name),
                "name_en": _text(f, "food_Eng_Nm"),
                "group": group,
                "weight_g": float(_text(f, "food_Wgh") or 0),
                "allergy_raw": allergy,
                "tags": ingredient_tags(name, group, allergy),
            })
        dishes.append({
            "code": _text(item, "fd_Code"),
            "name": _text(item, "fd_Nm"),
            "upper_group": _text(item, "upper_Fd_Grupp_Nm"),
            "group": _text(item, "fd_Grupp_Nm"),
            "weight_g": float(_text(item, "fd_Wgh") or 0),
            "ingredients": foods,
        })
    return total, dishes


def is_seasoning(ing: dict) -> bool:
    return (ing.get("group") or "") in SEASONING_GROUPS


def is_water(ing: dict) -> bool:
    n = ing.get("name", "")
    return n.startswith("생수") or n.startswith("물,") or n == "물"
