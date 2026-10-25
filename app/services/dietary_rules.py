"""규칙 기반 위험도 판정 + 종업원 확인 질문 생성.

핵심 원칙 (교수님 피드백 2 반영)
- 메뉴 DB상 '필수 재료'(certainty=confirmed)에서 걸리면 → WARNING (먼저 알려줌)
- 가게마다 다른 '변형 재료'·'숨은 재료'(certainty=possible)에서 걸리면 → CAUTION + 직원에게 물어볼 질문 생성
- 직원 답변으로 possible → confirmed / excluded 로 바뀌면 재계산
"""
from dataclasses import dataclass, field

from app.services.taxonomy import label, normalize_allergies

MEATS = {"pork", "beef", "chicken", "other_meat", "animal_gelatin"}
SEAFOOD = {"fish", "mackerel", "shrimp", "crab", "squid", "mollusk", "shellfish"}

RELIGIOUS_RULES: dict[str, dict[str, set[str]]] = {
    "halal": {"forbidden": {"pork", "alcohol", "animal_gelatin"}, "verify": {"beef", "chicken", "other_meat"}},
    "kosher": {"forbidden": {"pork", "shrimp", "crab", "squid", "mollusk", "shellfish"},
               "verify": {"beef", "chicken", "other_meat", "animal_gelatin"}},
    "hindu": {"forbidden": {"beef"}, "verify": set()},
}

DIET_RULES: dict[str, set[str]] = {
    "vegan": MEATS | SEAFOOD | {"egg", "milk"},
    "vegetarian": MEATS | SEAFOOD,       # lacto-ovo
    "lacto_ovo": MEATS | SEAFOOD,
    "lacto": MEATS | SEAFOOD | {"egg"},
    "ovo": MEATS | SEAFOOD | {"milk"},
    "pescatarian": MEATS,
}

LEVEL_ORDER = {"SAFE": 0, "CAUTION": 1, "WARNING": 2}


@dataclass
class DietProfile:
    allergy_tags: dict[str, str] = field(default_factory=dict)   # tag -> severity
    unmapped_allergies: list[str] = field(default_factory=list)
    religious_diet: str | None = None
    vegetarian_type: str | None = None
    preferred_language: str = "en"

    @classmethod
    def from_row(cls, row: dict | None) -> "DietProfile":
        row = row or {}
        tags, unmapped = normalize_allergies(row.get("allergies"))
        norm = lambda v: (str(v).strip().lower() or None) if v and str(v).lower() != "none" else None
        return cls(
            allergy_tags=tags,
            unmapped_allergies=unmapped,
            religious_diet=norm(row.get("religious_diet")),
            vegetarian_type=norm(row.get("vegetarian_type")),
            preferred_language=(row.get("preferred_language") or "en"),
        )

    def is_empty(self) -> bool:
        return not (self.allergy_tags or self.unmapped_allergies or self.religious_diet or self.vegetarian_type)


def _constraints(p: DietProfile) -> tuple[dict[str, str], set[str]]:
    """→ ({금지 태그: 사유 종류}, {확인 필요 태그})"""
    forbidden: dict[str, str] = {}
    verify: set[str] = set()
    for t in DIET_RULES.get(p.vegetarian_type or "", set()):
        forbidden[t] = "diet"
    rel = RELIGIOUS_RULES.get(p.religious_diet or "")
    if rel:
        for t in rel["forbidden"]:
            forbidden[t] = "religious"
        verify |= rel["verify"]
    for t in p.allergy_tags:
        forbidden[t] = "allergy"  # 알레르기가 가장 우선
    return forbidden, verify - set(forbidden)


def _has_batchim(word: str) -> bool | None:
    import re
    word = re.sub(r"\(.*?\)", "", word or "").strip()  # 괄호 설명 제외: '젓갈(새우젓)' → '젓갈'
    ch = word[-1] if word else ""
    if "가" <= ch <= "힣":
        return (ord(ch) - 0xAC00) % 28 != 0
    return None


def _josa(word: str, with_b: str, without_b: str) -> str:
    b = _has_batchim(word)
    return f"{with_b}({without_b})" if b is None else (with_b if b else without_b)


QUESTION_TEMPLATES = {
    "contains": {
        "ko": "{menu}에 {ingredient}{iga} 들어가나요?",
        "ko_inner": "{menu}의 {ingredient}에 {what}{iga} 들어가나요?",
        "en": "Does the {menu_t} contain {labels}?",
        "zh": "这道{menu_t}里有{labels}吗？",
        "ja": "この{menu_t}に{labels}は入っていますか？",
    },
    "variant": {
        "ko": "{menu}{eunneun} 어떤 종류인가요? ({options})",
        "en": "Which kind of {menu_t} is it? ({options})",
        "zh": "这是哪种{menu_t}？（{options}）",
        "ja": "この{menu_t}はどの種類ですか？（{options}）",
    },
    "halal_meat": {
        "ko": "{menu}에 들어가는 {ingredient}{iga} 할랄 인증 제품인가요?",
        "en": "Is the {labels} in the {menu_t} halal-certified?",
        "zh": "{menu_t}里的{labels}是清真认证的吗？",
        "ja": "{menu_t}の{labels}はハラール認証品ですか？",
    },
    "kosher_meat": {
        "ko": "{menu}에 들어가는 {ingredient}{iga} 코셔 인증 제품인가요?",
        "en": "Is the {labels} in the {menu_t} kosher-certified?",
        "zh": "{menu_t}里的{labels}是犹太洁食认证的吗？",
        "ja": "{menu_t}の{labels}はコーシャ認証品ですか？",
    },
}

LIST_SEP = {"ko": ", ", "en": ", ", "zh": "、", "ja": "・"}

# 질문용 짧은 한국어 이름과, 재료명에 이미 드러나 있는지 판단할 키워드
KO_SHORT = {
    "pork": ("돼지고기", ["돼지", "햄", "순대", "삼겹"]), "beef": ("소고기", ["소고기", "쇠고기", "차돌", "한우", "사골", "소곱창", "소갈비"]),
    "chicken": ("닭고기", ["닭"]), "other_meat": ("고기", ["고기"]),
    "fish": ("생선이나 멸치", ["생선", "멸치", "액젓", "어묵", "참치", "회", "복어", "아귀", "장어"]),
    "mackerel": ("고등어", ["고등어"]), "shrimp": ("새우", ["새우"]), "crab": ("게", ["게"]),
    "squid": ("오징어", ["오징어"]), "mollusk": ("낙지나 문어", ["낙지", "문어", "주꾸미"]),
    "shellfish": ("조개류", ["조개", "굴", "홍합", "바지락", "전복", "미더덕"]),
    "egg": ("달걀", ["달걀", "계란", "마요네즈"]), "milk": ("우유나 치즈", ["우유", "치즈", "버터", "크림"]),
    "wheat": ("밀가루", ["밀", "면"]), "buckwheat": ("메밀", ["메밀"]), "soy": ("콩", ["콩", "두부", "간장", "된장"]),
    "peanut": ("땅콩", ["땅콩"]), "walnut": ("호두", ["호두"]), "pine_nut": ("잣", ["잣"]),
    "sesame": ("참깨", ["깨", "참기름"]), "peach": ("복숭아", ["복숭아"]), "tomato": ("토마토", ["토마토", "케첩"]),
    "sulfite": ("아황산류", []), "alcohol": ("술이나 맛술", ["술", "미림", "청주", "주"]),
    "animal_gelatin": ("젤라틴", ["젤라틴"]),
}
OTHER_OPTION = "그 외"
OTHER_LABEL = {"ko": "그 외", "en": "other", "zh": "其他", "ja": "その他"}


def evaluate(menu_name: str, ingredients: list[dict], profile: DietProfile, menu_translated: str | None = None) -> dict:
    """ingredients: [{name, tags:[...], certainty: confirmed|possible|excluded, source, variant?, certified?}]

    질문 생성 규칙
    - 이미 필수 재료로 확정된 금지 태그(예: 돼지국밥의 pork)는 다시 묻지 않는다
    - 변형 메뉴에서 온 재료는 재료별로 묻지 않고 '어떤 종류인가요?' 한 번만 묻는다
    - 한 재료에 태그가 여러 개면 질문 하나로 합친다
    """
    lang = profile.preferred_language if profile.preferred_language in ("ko", "en", "zh", "ja") else "en"
    menu_t = menu_translated or menu_name
    forbidden, verify = _constraints(profile)
    level = "SAFE"
    reasons: list[dict] = []

    def bump(new_level: str):
        nonlocal level
        if LEVEL_ORDER[new_level] > LEVEL_ORDER[level]:
            level = new_level

    active = [i for i in ingredients if i.get("certainty", "possible") != "excluded"]

    # 1) 확정 금지 태그 먼저 계산
    confirmed_forbidden = {
        t for i in active if i.get("certainty") == "confirmed" for t in i.get("tags", []) if t in forbidden
    }

    contains_q: dict[str, list[str]] = {}   # ingredient -> tags
    verify_q: dict[str, list[str]] = {}
    variant_hit = False

    for ing in active:
        certainty = ing.get("certainty", "possible")
        name = ing.get("name", "")
        from_variant = ing.get("source") == "variant"
        ing_forbidden_possible = []
        ing_verify = []

        for tag in ing.get("tags", []):
            if tag in forbidden:
                sev = profile.allergy_tags.get(tag) if forbidden[tag] == "allergy" else None
                reasons.append({"kind": forbidden[tag], "tag": tag, "label": label(tag, lang),
                                "ingredient": name, "certainty": certainty, "severity": sev})
                if certainty == "confirmed":
                    bump("WARNING")
                else:
                    bump("CAUTION")
                    if tag not in confirmed_forbidden:
                        ing_forbidden_possible.append(tag)
            elif tag in verify:
                if ing.get("certified") is True:
                    continue
                if ing.get("certified") is False:
                    reasons.append({"kind": "religious", "tag": tag, "label": label(tag, lang),
                                    "ingredient": name, "certainty": "confirmed", "severity": None})
                    bump("WARNING")
                    continue
                reasons.append({"kind": "religious_verify", "tag": tag, "label": label(tag, lang),
                                "ingredient": name, "certainty": certainty, "severity": None})
                bump("CAUTION")
                ing_verify.append(tag)

        if from_variant and certainty == "possible" and (ing_forbidden_possible or ing_verify):
            variant_hit = True
        elif ing_forbidden_possible:
            contains_q.setdefault(name, []).extend(ing_forbidden_possible)  # 금지 여부 질문이 인증 질문보다 우선
        elif ing_verify and certainty == "possible":
            # 들어가는지부터 불확실 → '소고기가 들어가나요?' 먼저 (예 → 확정 후 인증 질문)
            contains_q.setdefault(name, []).extend(ing_verify)
        elif ing_verify:
            verify_q.setdefault(name, []).extend(ing_verify)

    questions: list[dict] = []
    sep = LIST_SEP[lang]

    if variant_hit:
        options = list(dict.fromkeys(i["variant"] for i in ingredients if i.get("source") == "variant" and i.get("variant")))
        options.append(OTHER_OPTION)
        tpl = QUESTION_TEMPLATES["variant"]
        ko = tpl["ko"].format(menu=menu_name, eunneun=_josa(menu_name, "은", "는"), options=" / ".join(options))
        questions.append({
            "kind": "variant", "ingredient": None, "tag": None, "tags": [], "options": options,
            "ko": ko,
            "user_lang": lang,
            # 사용자 언어가 한국어면 한국어 질문을 그대로 쓴다 (ko 템플릿은 {menu}를 써서 menu_t로 채울 수 없음)
            "translated": ko if lang == "ko" else
                tpl[lang].format(menu_t=menu_t, options=" / ".join(OTHER_LABEL[lang] if o == OTHER_OPTION else o for o in options)),
        })

    vkind = "kosher_meat" if profile.religious_diet == "kosher" else "halal_meat"
    for kind, bucket in (("contains", contains_q), (vkind, verify_q)):
        tpl = QUESTION_TEMPLATES[kind]
        for name, tags in bucket.items():
            tags = list(dict.fromkeys(tags))
            obvious = all(any(k in name for k in KO_SHORT.get(t, ("", []))[1]) for t in tags)
            if kind == "contains" and not obvious:
                what = "·".join(KO_SHORT.get(t, (t, []))[0] for t in tags)
                ko = tpl["ko_inner"].format(menu=menu_name, ingredient=name, what=what, iga=_josa(what, "이", "가"))
            else:
                ko = tpl["ko"].format(menu=menu_name, ingredient=name, iga=_josa(name, "이", "가"))
            questions.append({
                "kind": kind, "ingredient": name, "tag": tags[0], "tags": tags, "options": [],
                "ko": ko,
                "user_lang": lang,
                "translated": ko if lang == "ko" else
                    tpl[lang].format(menu_t=menu_t, labels=sep.join(label(t, lang) for t in tags)),
            })

    if level == "WARNING":
        # 이미 먹으면 안 되는 메뉴 → 직원에게 더 물어볼 필요 없음
        questions = []

    notes = []
    if profile.unmapped_allergies:
        notes.append({
            "type": "unmapped_allergy",
            "items": profile.unmapped_allergies,
            "message": "규칙 DB에 없는 알레르기 항목은 AI 추론 결과만으로 판단되므로 반드시 직원에게 확인하세요.",
        })
        if level == "SAFE":
            level = "CAUTION"

    return {
        "level": level,
        "confirmed_reasons": [r for r in reasons if r["certainty"] == "confirmed"],
        "possible_reasons": [r for r in reasons if r["certainty"] != "confirmed"],
        "needs_confirmation": bool(questions),
        "staff_questions": questions,
        "notes": notes,
    }
