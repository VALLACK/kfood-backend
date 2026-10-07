"""메뉴젠 데이터로 메뉴 재료를 조회한다 (1순위 데이터 소스).

핵심: 같은 계열 레시피를 모아 비교한다.
  '짬뽕' → 짬뽕, 해물짬뽕, 차돌박이짬뽕국, 백짬뽕국 ... (짬뽕덮밥·짬뽕순두부는 제외)
  - 계열 대부분(70%↑)에 있는 알레르기 재료 → 확정(confirmed)
  - 일부 레시피에만 있는 재료 → 가능성(possible) → 직원 질문
  - 성분 비율은 대표 레시피의 실제 중량(g)으로 계산
"""
import json
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

from app.services.menuzen import is_seasoning, is_water

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "menuzen_menus.json"
CONSENSUS = 0.7          # 계열 레시피 중 이 비율 이상에 있으면 확정
MAIN_SHARE = 5.0         # 대표 레시피에서 중량 5% 이상인 주재료는 확정
FAMILY_SUFFIXES = ("", "국", "탕")  # '짬뽕' 계열에 '짬뽕국', '짬뽕탕' 포함


def core(name: str) -> str:
    return re.sub(r"\(.*?\)|\s", "", name or "")


@lru_cache
def load_dishes(path: str = str(DATA_PATH)) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))["dishes"]


def find_family(query: str, dishes: list[dict]) -> tuple[list[dict], list[dict]]:
    """→ (정확히 같은 이름 레시피들, 같은 계열 레시피들)"""
    q = core(query)
    if len(q) < 2:
        return [], []

    def family_of(base: str):
        return [d for d in dishes if any(core(d["name"]).endswith(base + s) for s in FAMILY_SUFFIXES)]

    fam = family_of(q)
    if not fam:
        # '부산밀면'처럼 수식어가 붙은 경우 → DB 이름 중 query의 가장 긴 접미사로 재시도
        suffixes = sorted({core(d["name"]) for d in dishes if len(core(d["name"])) >= 2 and q.endswith(core(d["name"]))},
                          key=len, reverse=True)
        if suffixes:
            q = suffixes[0]
            fam = family_of(q)
    exact = [d for d in fam if core(d["name"]) == q]
    if not exact and len(fam) > 1:
        # '수육' → '탕수육'(튀김류)처럼 이름만 비슷한 다른 요리 제외: 최빈 식품군만 남김
        groups = Counter(d.get("upper_group") for d in fam)
        top = groups.most_common(1)[0][0]
        fam = [d for d in fam if d.get("upper_group") == top]
    return exact, fam


def _merge_same(ings: list[dict]) -> list[dict]:
    out: dict[str, dict] = {}
    for i in ings:
        key = i["short"]
        if key in out:
            out[key]["weight_g"] += i["weight_g"]
            out[key]["tags"] = list(dict.fromkeys(out[key]["tags"] + i["tags"]))
            out[key]["seasoning"] = out[key]["seasoning"] and is_seasoning(i)
        else:
            out[key] = {**i, "seasoning": is_seasoning(i)}
    return list(out.values())


def build_from_menuzen(menu_name: str, dishes: list[dict] | None = None) -> dict | None:
    from app.services.dietary_rules import KO_SHORT  # 순환 import 방지

    dishes = load_dishes() if dishes is None else dishes
    if not dishes:
        return None
    exact, fam = find_family(menu_name, dishes)
    if not fam:
        return None

    base = exact[0] if exact else min(fam, key=lambda d: len(d["name"]))
    n = len(fam)
    tag_count: dict[str, int] = {}
    tag_seen: dict[str, list[str]] = {}
    for d in fam:
        for t in {t for i in d["ingredients"] for t in i["tags"]}:
            tag_count[t] = tag_count.get(t, 0) + 1
            tag_seen.setdefault(t, []).append(d["name"])
    frac = {t: c / n for t, c in tag_count.items()}

    base_ings = _merge_same([i for i in base["ingredients"] if not is_water(i)])
    total = sum(i["weight_g"] for i in base_ings) or 1.0

    ingredients = []
    for i in base_ings:
        share = i["weight_g"] * 100 / total
        if n == 1:
            confirmed = not i["seasoning"]
        else:
            confirmed = (not i["seasoning"] and share >= MAIN_SHARE) or any(frac.get(t, 0) >= CONSENSUS for t in i["tags"])
        ingredients.append({
            "name": i["short"],
            "name_translated": i.get("name_en"),
            "tags": i["tags"],
            "certainty": "confirmed" if confirmed else "possible",
            "source": "menuzen",
            "weight_g": round(i["weight_g"], 1),
            "ratio_percent": round(share, 1),
            "ratio_source": "menuzen",
            "allergy_raw": i.get("allergy_raw"),
        })

    # 대표 레시피엔 없지만 같은 계열 다른 레시피에 있는 알레르기·식단 재료
    base_tags = {t for i in base_ings for t in i["tags"]}
    for t, c in sorted(tag_count.items(), key=lambda x: -x[1]):
        if t in base_tags:
            continue
        ingredients.append({
            "name": KO_SHORT.get(t, (t, []))[0],
            "name_translated": None,
            "tags": [t],
            "certainty": "confirmed" if frac[t] >= CONSENSUS else "possible",
            "source": "family",
            "seen_in": tag_seen[t][:3],
            "ratio_percent": None,
        })

    ingredients += _from_menu_name(menu_name, {t for i in ingredients if i["certainty"] == "confirmed" for t in i["tags"]}, KO_SHORT)

    return {
        "base_menu": base["name"],
        "resolved_variant": None,
        "variant_options": [],
        "family": [d["name"] for d in fam],
        "data_source": "menuzen",
        "ingredients": ingredients,
    }


# 메뉴명에 재료가 드러난 경우 (예: '돼지등갈비찜', '소고기우동', '해물아구찜')
# 3번째 값은 예외 — 그 단어가 메뉴명에 있으면 이 규칙을 적용하지 않는다.
# (예: '아구수육'은 생선 요리라서 '수육' 규칙에서 빼야 한다)
NAME_CONFIRM = [("돼지", "pork"), ("삼겹", "pork"), ("소고기", "beef"), ("쇠고기", "beef"), ("차돌", "beef"),
                ("한우", "beef"), ("닭", "chicken"), ("새우", "shrimp"), ("오징어", "squid"), ("낙지", "mollusk"),
                ("문어", "mollusk"), ("전복", "shellfish"), ("굴", "shellfish"), ("조개", "shellfish"),
                ("꽃게", "crab"), ("치즈", "milk"), ("계란", "egg"), ("달걀", "egg"), ("순대", "pork"),
                ("참치", "fish"), ("고등어", "mackerel"), ("장어", "fish"), ("김치", "fish"),
                # 고기 이름이 드러나지 않지만 재료가 정해진 메뉴
                ("수육", "pork", ("아구수육", "아귀수육", "문어수육", "오리수육", "닭수육", "소수육", "한우수육")),
                ("항정살", "pork"), ("목살", "pork"), ("갈매기살", "pork"),
                ("보쌈", "pork"), ("족발", "pork"), ("차슈", "pork"),
                ("돈까스", "pork"), ("돈가스", "pork"), ("돈카츠", "pork"),
                # 게 종류 — '홍게라면'이 공공데이터 '라면'으로 매칭되면서 게가 빠지던 문제
                ("대게", "crab"), ("홍게", "crab"), ("킹크랩", "crab"), ("돌게", "crab"), ("털게", "crab"),
                ("게장", "crab"), ("게살", "crab"),
                # 생선 이름 ('대구'는 지명 '대구막창'과 겹쳐서 메뉴명 규칙에서는 뺀다)
                ("명태", "fish"), ("동태", "fish"), ("생태", "fish"), ("황태", "fish"), ("코다리", "fish"),
                ("아귀", "fish"), ("아구", "fish"), ("우럭", "fish"), ("광어", "fish"), ("갈치", "fish"),
                # 부산식 줄임말: 낙곱새 = 낙지+곱창+새우, 낙새 = 낙지+새우, 낙삼새 = 낙지+삼겹살+새우
                # (10/05 평가: '수백당곱새세트'가 새우 알레르기에 SAFE로 나옴)
                ("곱새", "shrimp"), ("낙새", "shrimp"), ("삼새", "shrimp"), ("낙삼", "pork"),
                # 돼지 부위가 이름에 들어간 카츠 (10/05 평가: '등심카츠'를 AI가 소고기로 추정)
                ("등심카츠", "pork"), ("안심카츠", "pork"), ("로스카츠", "pork"), ("히레카츠", "pork")]

# (키워드, 태그, 예외 메뉴명, 재료 이름) — 재료 이름이 None이면 태그 기본 이름을 쓴다.
NAME_POSSIBLE = [("해물", ["shrimp", "squid", "shellfish"]), ("해산물", ["shrimp", "squid", "shellfish"]),
                 ("모듬", ["shrimp", "squid", "shellfish"]), ("모둠", ["shrimp", "squid", "shellfish"]),
                 # 한국 카츠는 대부분 돼지고기. 고기 종류가 이름에 없으면 확인 질문을 띄운다 ('명란카츠')
                 ("카츠", ["pork"], ("생선", "치킨", "닭", "새우", "규", "연어", "함박", "비프", "소고기"), "돼지고기"),
                 # 국밥·수육은 새우젓을 넣거나 곁들인다. 공공데이터 레시피에는 빠져 있어서
                 # '돼지국밥'은 CAUTION인데 '순대국밥'·'수육'은 SAFE로 갈리던 문제
                 ("국밥", ["shrimp"], (), "새우젓"),
                 ("수육", ["shrimp"], ("아구수육", "아귀수육", "문어수육"), "새우젓")]


def _from_menu_name(menu_name: str, confirmed_tags: set, KO_SHORT) -> list[dict]:
    """메뉴명에 재료가 명시돼 있으면 공공데이터 레시피보다 우선해 반영한다."""
    out, seen = [], set(confirmed_tags)
    for rule in NAME_CONFIRM:
        kw, tag = rule[0], rule[1]
        exceptions = rule[2] if len(rule) > 2 else ()
        if kw in menu_name and tag not in seen and not any(x in menu_name for x in exceptions):
            seen.add(tag)
            out.append({"name": KO_SHORT.get(tag, (tag, []))[0], "name_translated": None, "tags": [tag],
                        "certainty": "confirmed", "source": "menu_name", "matched_keyword": kw, "ratio_percent": None})
    for rule in NAME_POSSIBLE:
        kw, tags = rule[0], rule[1]
        exceptions = rule[2] if len(rule) > 2 else ()
        label = rule[3] if len(rule) > 3 else None
        if kw in menu_name and not any(x in menu_name for x in exceptions):
            for tag in tags:
                if tag not in seen:
                    seen.add(tag)
                    out.append({"name": label or KO_SHORT.get(tag, (tag, []))[0], "name_translated": None, "tags": [tag],
                                "certainty": "possible", "source": "menu_name", "matched_keyword": kw, "ratio_percent": None})
    return out


def from_menu_name(menu_name: str, confirmed_tags: set) -> list[dict]:
    """메뉴명 규칙을 데이터 출처와 상관없이 적용한다.

    build_from_menuzen() 안에서만 쓰이던 규칙이라, 공공데이터·자체 DB에 없는 메뉴
    (data_source='ai')에는 적용되지 않았다. 실사용 검증에서 '수육백반'이 할랄
    프로필에 SAFE로 나온 원인이다. 이제 모든 경로에서 호출한다.
    """
    from app.services.dietary_rules import KO_SHORT  # 순환 import 방지
    return _from_menu_name(menu_name, confirmed_tags, KO_SHORT)
