"""/analyze 파이프라인: 메뉴 DB 매칭 → LLM 성분 추론(태그·비율) → 규칙 판정."""
import json

from fastapi import HTTPException

from app.core.config import settings
from app.models.schemas import MenuLine
from app.services import groq_service
from app.services.dietary_rules import DietProfile, evaluate, LEVEL_ORDER
from app.services.ingredient_lexicon import enrich
from app.services.unmatched_log import record as record_unmatched
from app.services.menu_knowledge import build_known_ingredients
from app.services.taxonomy import TAGS

LANG_NAMES = {"ko": "Korean", "en": "English", "zh": "Simplified Chinese", "ja": "Japanese"}

SYSTEM_PROMPT = """You are a Korean food ingredient analyst for foreign tourists in Busan.
You DO NOT decide safety levels. You only list ingredients with tags; a rule engine decides risk.
Respond with a single JSON object only."""

USER_TEMPLATE = """Menu items (from a restaurant menu photo):
{menus}

Reference data from our menu DB (authoritative; reuse these ingredient names EXACTLY when listing them):
{known}

Allowed tags (use only these): {tags}

Custom allergies the user listed that have no tag (report if an ingredient may contain them): {custom}

For EACH menu item return:
{{
  "results": [
    {{
      "menu": "<menu name exactly as given>",
      "menu_translated": "<name in {lang}>",
      "description_translated": "<one-sentence description in {lang}>",
      "ingredients": [
        {{
          "name": "<Korean ingredient name>",
          "name_translated": "<in {lang}>",
          "tags": ["<allowed tag>", ...],
          "ratio_percent": <estimated share of the dish by weight, integer; all ratios of a menu should sum to about 100>,
          "certainty": "confirmed" | "possible"
        }}
      ],
      "custom_allergen_hits": [{{"allergy": "<custom allergy>", "ingredient": "<name>", "certainty": "confirmed"|"possible"}}]
    }}
  ]
}}

Rules:
- Include hidden/customary ingredients (broth base, fish sauce, jeotgal, oyster sauce, cooking wine, sesame oil) as "possible" unless always used.
- "confirmed" only if virtually every restaurant uses it for this dish.
- Tag conservatively: soy sauce → ["soy","wheat"], fish cake → ["fish","wheat"], anchovy broth → ["fish"].
- Non-food lines (prices, shop name, notices) must be skipped.
- List at most 12 ingredients per menu (largest share first) to keep the response short.
"""


def _menus_from_request(menus, ocr_text: str | None) -> list[str]:
    if menus:
        return [m.name for m in menus if m.name.strip()]
    lines = [l.strip() for l in (ocr_text or "").splitlines()]
    return [l for l in lines if l]


def _merge(known: dict | None, ai: dict) -> list[dict]:
    valid = set(TAGS)
    ai_ings = ai.get("ingredients") or []
    for i in ai_ings:
        i["tags"] = [t for t in (i.get("tags") or []) if t in valid]

    if not known:
        return [{**i, "source": "ai", "certainty": i.get("certainty") if i.get("certainty") in ("confirmed", "possible") else "possible"}
                for i in ai_ings if i.get("name")]

    by_name = {i.get("name"): i for i in ai_ings}
    merged = []
    for k in known["ingredients"]:
        a = by_name.pop(k["name"], {})
        merged.append({
            **k,
            "name_translated": k.get("name_translated") or a.get("name_translated"),
            # 메뉴젠은 실제 중량 기반 비율 → AI 추정치로 덮어쓰지 않음
            "ratio_percent": k["ratio_percent"] if k.get("ratio_source") == "menuzen" else a.get("ratio_percent"),
        })
    # DB에 없는 AI 추론 재료는 확정하지 않고 possible로만 반영
    for a in by_name.values():
        if a.get("name"):
            merged.append({**a, "certainty": "possible", "source": "ai"})
    return merged


def _normalize_ratios(ings: list[dict]) -> None:
    if any(i.get("ratio_source") == "menuzen" for i in ings):
        for i in ings:
            if i.get("ratio_source") != "menuzen":
                i["ratio_percent"] = None  # 실측 비율과 AI 추정치를 섞지 않음
        return
    vals = [i for i in ings if isinstance(i.get("ratio_percent"), (int, float)) and i["ratio_percent"] > 0]
    total = sum(i["ratio_percent"] for i in vals)
    if total <= 0:
        for i in ings:
            i["ratio_percent"] = None
        return
    for i in ings:
        if i in vals:
            i["ratio_percent"] = round(i["ratio_percent"] * 100 / total, 1)
        else:
            i["ratio_percent"] = None


CHUNK = 2  # 한 번에 보내는 메뉴 수 (Groq 무료 등급 분당 토큰 한도 8,000 대응)


def analyze(menus, ocr_text: str | None, profile: DietProfile) -> list[dict]:
    names = _menus_from_request(menus, ocr_text)
    if not names:
        return []
    if len(names) > CHUNK:  # 메뉴판이 크면 나눠서 호출하고 결과를 합친다
        out = []
        for i in range(0, len(names), CHUNK):
            out += analyze([MenuLine(name=n) for n in names[i:i + CHUNK]], None, profile)
        return out
    if len(names) > 1:
        try:
            return _analyze_batch(names, profile)
        except HTTPException:  # 요청이 여전히 크면 절반으로 나눠 재시도
            half = len(names) // 2
            return (analyze([MenuLine(name=n) for n in names[:half]], None, profile)
                    + analyze([MenuLine(name=n) for n in names[half:]], None, profile))
    return _analyze_batch(names, profile)


def _analyze_batch(names: list[str], profile: DietProfile) -> list[dict]:
    known_map = {n: build_known_ingredients(n) for n in names}
    for n, k in known_map.items():
        if not k:
            record_unmatched(n)  # 데이터가 없는 메뉴 → 검수 대상으로 기록
    lang = profile.preferred_language if profile.preferred_language in LANG_NAMES else "en"

    known_for_prompt = {
        n: {"base_menu": k["base_menu"], "resolved_variant": k["resolved_variant"],
            "ingredients": [{"name": i["name"], "tags": i["tags"], "certainty": i["certainty"]} for i in k["ingredients"]]}
        for n, k in known_map.items() if k
    }
    prompt = USER_TEMPLATE.format(
        menus="\n".join(f"- {n}" for n in names),
        known=json.dumps(known_for_prompt, ensure_ascii=False) if known_for_prompt else "(none)",
        tags=", ".join(TAGS),
        custom=", ".join(profile.unmapped_allergies) or "(none)",
        lang=LANG_NAMES[lang],
    )
    data = groq_service.chat_json(
        settings.GROQ_TEXT_MODEL,
        [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
        max_tokens=3000,
    )
    ai_by_menu = {r.get("menu"): r for r in data.get("results", []) if isinstance(r, dict)}

    results = []
    for n in names:
        ai = ai_by_menu.get(n, {})
        known = known_map.get(n)
        ingredients = enrich(_merge(known, ai))
        _normalize_ratios(ingredients)
        risk = evaluate(n, ingredients, profile, ai.get("menu_translated"))

        hits = ai.get("custom_allergen_hits") or []
        for h in hits:
            lvl = "WARNING" if h.get("certainty") == "confirmed" else "CAUTION"
            if LEVEL_ORDER[lvl] > LEVEL_ORDER[risk["level"]]:
                risk["level"] = lvl

        results.append({
            "menu": n,
            "menu_translated": ai.get("menu_translated"),
            "description_translated": ai.get("description_translated"),
            "base_menu": known["base_menu"] if known else None,
            "resolved_variant": known["resolved_variant"] if known else None,
            "variant_options": known["variant_options"] if known else [],
            "matched_menu_db": bool(known),
            "data_source": known.get("data_source") if known else "ai",
            "family": known.get("family", []) if known else [],
            "ingredients": ingredients,
            "custom_allergen_hits": hits,
            "risk": risk,
        })
    return results


def re_evaluate(menu_result: dict, profile: DietProfile) -> dict:
    risk = evaluate(menu_result["menu"], menu_result.get("ingredients", []), profile, menu_result.get("menu_translated"))
    return {**menu_result, "risk": risk}
