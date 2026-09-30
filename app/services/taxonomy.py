"""성분 태그 체계.

LLM이 위험도를 직접 판정하지 않게 하고, 재료마다 '태그'만 붙이게 한 뒤
위험도는 규칙(dietary_rules.py)으로 계산한다 → 같은 입력이면 항상 같은 결과,
테스트 케이스로 필터 정확도를 검증할 수 있음.
"""

# LLM이 사용할 수 있는 태그 목록 (프롬프트에 그대로 들어감)
TAGS: dict[str, str] = {
    "pork": "돼지고기·돼지뼈 육수·라드·햄·베이컨·순대",
    "beef": "소고기·사골 육수·차돌",
    "chicken": "닭고기·닭 육수",
    "other_meat": "오리·양 등 기타 육류",
    "fish": "생선·어묵·멸치·멸치육수·액젓·가쓰오부시",
    "mackerel": "고등어",
    "shrimp": "새우·새우젓",
    "crab": "게·꽃게·게맛살",
    "squid": "오징어",
    "mollusk": "낙지·문어·주꾸미·곰장어 제외 연체류",
    "shellfish": "조개·바지락·홍합·굴·전복·가리비",
    "egg": "달걀·메추리알·마요네즈",
    "milk": "우유·치즈·버터·크림",
    "wheat": "밀가루·면·빵가루·간장(대부분 밀 함유)·부침가루",
    "buckwheat": "메밀",
    "soy": "대두·간장·된장·두부·콩나물",
    "peanut": "땅콩",
    "walnut": "호두",
    "pine_nut": "잣",
    "sesame": "참깨·참기름·들기름 제외",
    "peach": "복숭아",
    "tomato": "토마토·케첩",
    "sulfite": "아황산류(말린 과일·와인 등)",
    "alcohol": "술·맛술·미림·청주·요리주",
    "animal_gelatin": "젤라틴",
}

# 프로필 알레르기 이름(한/영) → 태그. 식약처 알레르기 유발물질 22종 기준 + 흔한 묶음 표현
ALLERGY_ALIASES: dict[str, list[str]] = {
    "알류": ["egg"], "달걀": ["egg"], "계란": ["egg"], "egg": ["egg"], "eggs": ["egg"],
    "우유": ["milk"], "유제품": ["milk"], "milk": ["milk"], "dairy": ["milk"],
    "메밀": ["buckwheat"], "buckwheat": ["buckwheat"],
    "땅콩": ["peanut"], "peanut": ["peanut"], "peanuts": ["peanut"],
    "대두": ["soy"], "콩": ["soy"], "soy": ["soy"], "soybean": ["soy"],
    "밀": ["wheat"], "글루텐": ["wheat"], "wheat": ["wheat"], "gluten": ["wheat"],
    "고등어": ["mackerel"], "mackerel": ["mackerel"],
    "게": ["crab"], "crab": ["crab"],
    "새우": ["shrimp"], "shrimp": ["shrimp"],
    "갑각류": ["shrimp", "crab"], "crustacean": ["shrimp", "crab"], "crustaceans": ["shrimp", "crab"],
    "돼지고기": ["pork"], "pork": ["pork"],
    "복숭아": ["peach"], "peach": ["peach"],
    "토마토": ["tomato"], "tomato": ["tomato"],
    "아황산류": ["sulfite"], "sulfite": ["sulfite"], "sulfites": ["sulfite"],
    "호두": ["walnut"], "walnut": ["walnut"],
    "견과류": ["walnut", "peanut", "pine_nut"], "nuts": ["walnut", "peanut", "pine_nut"], "tree_nuts": ["walnut", "pine_nut"],
    "닭고기": ["chicken"], "chicken": ["chicken"],
    "쇠고기": ["beef"], "소고기": ["beef"], "beef": ["beef"],
    "오징어": ["squid"], "squid": ["squid"],
    "조개류": ["shellfish"], "조개": ["shellfish"],
    # 영어 "shellfish"는 새우·게(갑각류)까지 포함하는 말이다. 영어권 관광객이 새우 알레르기로
    # "Shellfish"를 고르면 조개류만 잡혀서 새우 요리가 SAFE로 나오던 문제를 막는다.
    # (한국어 '조개류'를 고른 경우는 조개만 — 사용자가 구분해서 고른 것이므로 존중한다)
    "shellfish": ["shellfish", "shrimp", "crab"], "shell fish": ["shellfish", "shrimp", "crab"],
    "잣": ["pine_nut"], "pine_nut": ["pine_nut"],
    "생선": ["fish", "mackerel"], "어류": ["fish", "mackerel"], "fish": ["fish", "mackerel"],
    "해산물": ["fish", "mackerel", "shrimp", "crab", "squid", "mollusk", "shellfish"],
    "seafood": ["fish", "mackerel", "shrimp", "crab", "squid", "mollusk", "shellfish"],
    "참깨": ["sesame"], "깨": ["sesame"], "sesame": ["sesame"],
}

# 다국어 표시용 태그 이름 (위험 사유/직원 질문 생성에 사용)
TAG_LABELS: dict[str, dict[str, str]] = {
    "pork": {"ko": "돼지고기", "en": "pork", "zh": "猪肉", "ja": "豚肉"},
    "beef": {"ko": "소고기", "en": "beef", "zh": "牛肉", "ja": "牛肉"},
    "chicken": {"ko": "닭고기", "en": "chicken", "zh": "鸡肉", "ja": "鶏肉"},
    "other_meat": {"ko": "육류", "en": "meat", "zh": "肉类", "ja": "肉類"},
    "fish": {"ko": "생선(멸치·액젓 포함)", "en": "fish (incl. anchovy/fish sauce)", "zh": "鱼类（含鳀鱼、鱼露）", "ja": "魚（煮干し・魚醤を含む）"},
    "mackerel": {"ko": "고등어", "en": "mackerel", "zh": "鲭鱼", "ja": "サバ"},
    "shrimp": {"ko": "새우", "en": "shrimp", "zh": "虾", "ja": "エビ"},
    "crab": {"ko": "게", "en": "crab", "zh": "蟹", "ja": "カニ"},
    "squid": {"ko": "오징어", "en": "squid", "zh": "鱿鱼", "ja": "イカ"},
    "mollusk": {"ko": "연체류(낙지·문어 등)", "en": "mollusks (octopus etc.)", "zh": "软体类（章鱼等）", "ja": "軟体類（タコ等）"},
    "shellfish": {"ko": "조개류", "en": "shellfish", "zh": "贝类", "ja": "貝類"},
    "egg": {"ko": "달걀", "en": "egg", "zh": "鸡蛋", "ja": "卵"},
    "milk": {"ko": "우유·유제품", "en": "milk/dairy", "zh": "乳制品", "ja": "乳製品"},
    "wheat": {"ko": "밀", "en": "wheat", "zh": "小麦", "ja": "小麦"},
    "buckwheat": {"ko": "메밀", "en": "buckwheat", "zh": "荞麦", "ja": "そば"},
    "soy": {"ko": "대두", "en": "soy", "zh": "大豆", "ja": "大豆"},
    "peanut": {"ko": "땅콩", "en": "peanut", "zh": "花生", "ja": "落花生"},
    "walnut": {"ko": "호두", "en": "walnut", "zh": "核桃", "ja": "くるみ"},
    "pine_nut": {"ko": "잣", "en": "pine nut", "zh": "松子", "ja": "松の実"},
    "sesame": {"ko": "참깨", "en": "sesame", "zh": "芝麻", "ja": "ごま"},
    "peach": {"ko": "복숭아", "en": "peach", "zh": "桃子", "ja": "桃"},
    "tomato": {"ko": "토마토", "en": "tomato", "zh": "番茄", "ja": "トマト"},
    "sulfite": {"ko": "아황산류", "en": "sulfites", "zh": "亚硫酸盐", "ja": "亜硫酸塩"},
    "alcohol": {"ko": "술(맛술·미림 포함)", "en": "alcohol (incl. cooking wine)", "zh": "酒（含料酒）", "ja": "酒（みりん含む）"},
    "animal_gelatin": {"ko": "동물성 젤라틴", "en": "animal gelatin", "zh": "动物明胶", "ja": "動物性ゼラチン"},
}

SUPPORTED_LANGS = ("ko", "en", "zh", "ja")


def label(tag: str, lang: str = "ko") -> str:
    lang = lang if lang in SUPPORTED_LANGS else "en"
    return TAG_LABELS.get(tag, {}).get(lang, tag)


def normalize_allergies(raw) -> tuple[dict[str, str], list[str]]:
    """profiles.allergies(jsonb) → ({tag: severity}, 매핑 실패한 이름 목록).

    DB 예시: {"땅콩": "심각", "갑각류": "경미"} 또는 ["땅콩", "새우"] 둘 다 허용.
    """
    if not raw:
        return {}, []
    items = raw.items() if isinstance(raw, dict) else ((name, "unknown") for name in raw)
    tags: dict[str, str] = {}
    unmapped: list[str] = []
    for name, severity in items:
        key = str(name).strip()
        mapped = ALLERGY_ALIASES.get(key) or ALLERGY_ALIASES.get(key.lower())
        if not mapped:
            unmapped.append(key)
            continue
        for t in mapped:
            tags[t] = str(severity)
    return tags, unmapped
