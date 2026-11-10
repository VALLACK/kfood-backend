"""화면에 그대로 보여주는 안내 문구 (프로필 언어별).

백엔드가 사용자 언어로 번역된 문구를 내려주고, 프론트는 받은 문자열을 그대로 표시한다.
언어는 프로필의 preferred_language(ko/en/zh/ja), 그 밖의 값은 en.
"""
from app.services.dietary_rules import DietProfile

LANGS = ("ko", "en", "zh", "ja")

MESSAGES = {
    # /analyze 결과 하단
    "analyze_disclaimer": {
        "ko": "성분 비율(ratio_percent)은 AI 추정치이며, 최종 판단은 반드시 직원 확인 후 하세요.",
        "en": "Ingredient ratios are AI estimates. Always confirm with the staff before eating.",
        "zh": "成分比例为AI估算值，食用前请务必向店员确认。",
        "ja": "成分の割合はAIによる推定です。食べる前に必ず店員に確認してください。",
    },
    # 미리 알아보기(식당 찾기) 하단
    "restaurant_disclaimer": {
        "ko": "재료는 메뉴판과 일반 레시피 기준 추정이며, 최종 판단은 반드시 직원 확인 후 하세요.",
        "en": "Ingredients are estimated from the menu board and typical recipes. Always confirm with the staff before eating.",
        "zh": "食材是根据菜单和常见食谱推测的，食用前请务必向店员确认。",
        "ja": "材料はメニュー表と一般的なレシピからの推定です。食べる前に必ず店員に確認してください。",
    },
    # 프로필이 없을 때 경고 배너 (모든 메뉴가 SAFE로 보이는 상태)
    "no_profile_notice": {
        "ko": "프로필(알레르기·식단)이 없어서 모든 메뉴가 SAFE로 보입니다. 프로필을 설정해야 판정이 적용됩니다.",
        "en": "No profile (allergies/diet) is set, so every menu shows as SAFE. Set up your profile to get real results.",
        "zh": "尚未设置个人资料（过敏·饮食），所有菜品都会显示为SAFE。请先设置个人资料再查看结果。",
        "ja": "プロフィール（アレルギー・食事制限）が未設定のため、すべてのメニューがSAFEと表示されます。プロフィールを設定してください。",
    },
}


def lang_of(profile: DietProfile) -> str:
    lang = (profile.preferred_language or "en").lower()
    return lang if lang in LANGS else "en"


def t(key: str, profile: DietProfile) -> str:
    return MESSAGES[key][lang_of(profile)]
