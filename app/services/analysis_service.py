"""/analyze 파이프라인: 메뉴 DB 매칭 → LLM 성분 추론(태그·비율) → 규칙 판정."""
import json

from fastapi import HTTPException

from app.core.config import settings
from app.models.schemas import MenuLine
from app.services import groq_service
import re
import unicodedata

from app.services.dietary_rules import DietProfile, evaluate, LEVEL_ORDER, KO_SHORT, RELIGIOUS_RULES
from app.services import analysis_cache, menu_board
from app.services.ingredient_lexicon import enrich
from app.services.menuzen_knowledge import from_menu_name
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
- Hidden/customary ingredients (broth base, fish sauce, jeotgal, oyster sauce, cooking wine, sesame oil) = "possible".
- "confirmed" only if virtually every restaurant uses it for this dish.
- Tag conservatively: soy sauce → ["soy","wheat"], fish cake → ["fish","wheat"], anchovy broth → ["fish"].
- Skip non-food lines (prices, shop name, notices).
- At most 8 ingredients per menu, largest share first. Omit water, salt, sugar and plain vegetables.
"""


def _lines_from_request(menus, ocr_text: str | None) -> list[MenuLine]:
    """요청을 MenuLine 목록으로 통일한다. 메뉴판 표기(note)를 끝까지 들고 가야 한다."""
    if menus:
        return [m for m in menus if m.name.strip()]
    return [MenuLine(name=l.strip()) for l in (ocr_text or "").splitlines() if l.strip()]


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


CERTAINTY_ORDER = {"excluded": 0, "possible": 1, "confirmed": 2}


def _dedupe(ings: list[dict]) -> list[dict]:
    """같은 재료가 여러 경로로 들어오면 하나로 합친다.

    예: '해물탕'은 메뉴명 규칙('해물'→새우)과 메뉴판 표기에서 새우를 각각 넣는다.
    그대로 두면 직원 질문과 위험 사유가 똑같이 두 번 나온다.
    확정도가 높은 쪽(confirmed > possible)을 남긴다.
    """
    out: list[dict] = []
    index: dict[tuple, int] = {}
    for i in ings:
        key = (i.get("name"), tuple(sorted(i.get("tags") or [])))
        pos = index.get(key)
        if pos is None:
            index[key] = len(out)
            out.append(i)
        elif CERTAINTY_ORDER.get(i.get("certainty"), 0) > CERTAINTY_ORDER.get(out[pos].get("certainty"), 0):
            out[pos] = i
    return out


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


# 한 번에 보내는 메뉴 수. 호출마다 지시문(약 950토큰)이 통째로 반복되므로,
# 이 값이 작을수록 분당 토큰 한도를 낭비한다. 응답이 잘리면 자동으로 절반씩 나눠 재시도한다.
CHUNK = settings.ANALYZE_CHUNK


def analyze(menus, ocr_text: str | None, profile: DietProfile, skip_ai: bool = False) -> list[dict]:
    lines = _lines_from_request(menus, ocr_text)
    if not lines:
        return []
    if len(lines) > CHUNK:  # 메뉴판이 크면 나눠서 호출하고 결과를 합친다
        out = []
        for i in range(0, len(lines), CHUNK):
            out += _analyze_chunk(lines[i:i + CHUNK], profile, skip_ai)
        return out
    return _analyze_chunk(lines, profile, skip_ai)


def _analyze_chunk(lines: list[MenuLine], profile: DietProfile, skip_ai: bool = False) -> list[dict]:
    if skip_ai:
        return _analyze_batch(lines, profile, skip_ai=True)
    try:
        return _analyze_batch(lines, profile)
    except groq_service.AIUnavailable:
        # 하루 한도 소진 등: 나눠서 다시 불러봐야 소용없다 → AI 없이 판정해서라도 결과를 준다
        return _analyze_batch(lines, profile, skip_ai=True)
    except HTTPException:
        if len(lines) > 1:  # 요청이 커서 실패했을 수 있으니 절반으로 나눠 재시도
            half = len(lines) // 2
            return _analyze_chunk(lines[:half], profile) + _analyze_chunk(lines[half:], profile)
        # 한 개만 보내도 실패하면, 요청 전체를 502로 날리지 않고 AI 없이 판정한다
        return _analyze_batch(lines, profile, skip_ai=True)


def _prompt_line(line: MenuLine) -> str:
    """메뉴판에 재료가 인쇄돼 있으면 AI에게도 알려준다."""
    if line.note and line.note.strip():
        return f"- {line.name}  (메뉴판에 인쇄된 재료: {line.note.strip()})"
    return f"- {line.name}"


def _cache_scope(profile: DietProfile) -> str:
    """캐시 키의 범위. 성분은 프로필과 무관하지만, 사용자 정의 알레르기 판정
    (custom_allergen_hits)은 그 사용자가 적은 항목에 따라 달라지므로 키에 넣는다."""
    lang = profile.preferred_language if profile.preferred_language in LANG_NAMES else "en"
    custom = ",".join(sorted(profile.unmapped_allergies))
    return f"{lang}|{custom}" if custom else lang


def _analyze_batch(lines: list[MenuLine], profile: DietProfile, skip_ai: bool = False) -> list[dict]:
    lang_key = _cache_scope(profile)
    cached = {}
    todo = []
    for l in lines:
        hit = analysis_cache.get(l.name, l.note, lang_key)
        if hit is None:
            todo.append(l)
        else:
            cached.setdefault(l.name, hit)
    if not todo or skip_ai:  # 캐시에 있거나 즉시 판정 모드면 LLM을 부르지 않는다
        return _build_results(lines, cached, profile)
    return _build_results(lines, {**_ask_llm(todo, profile), **cached}, profile)


def _ask_llm(lines: list[MenuLine], profile: DietProfile) -> dict:
    names = [l.name for l in lines]
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
        menus="\n".join(_prompt_line(l) for l in lines),
        known=json.dumps(known_for_prompt, ensure_ascii=False) if known_for_prompt else "(none)",
        tags=", ".join(TAGS),
        custom=", ".join(profile.unmapped_allergies) or "(none)",
        lang=LANG_NAMES[lang],
    )
    data = groq_service.chat_json(
        settings.GROQ_TEXT_MODEL,
        [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
        max_tokens=min(900 * len(lines) + 600, 6000),
    )
    raw = data.get("results") if isinstance(data, dict) else None
    results = [_sanitize(r) for r in (raw or []) if isinstance(r, dict)]
    ai_by_menu = _match_results(lines, results)
    scope = _cache_scope(profile)
    for l in lines:
        if l.name in ai_by_menu:
            analysis_cache.put(l.name, l.note, scope, ai_by_menu[l.name])
    analysis_cache.flush()
    return ai_by_menu


def _sanitize(r: dict) -> dict:
    """LLM 응답 한 건을 검증한다.

    형식이 틀린 값이 그대로 캐시에 저장되면 그 메뉴는 서버를 재시작해도 계속 오류가 나고,
    tags가 문자열("shrimp")로 오면 글자 단위로 쪼개져 사라져서 새우 알레르기인데 SAFE가 된다.
    """
    valid = set(TAGS)
    ings = []
    for i in r.get("ingredients") or []:
        if isinstance(i, str):
            i = {"name": i}
        if not isinstance(i, dict) or not isinstance(i.get("name"), str) or not i["name"].strip():
            continue
        tags = i.get("tags")
        if isinstance(tags, str):
            tags = [tags]
        tags = [t.strip() for t in (tags if isinstance(tags, list) else []) if isinstance(t, str) and t.strip() in valid]
        ings.append({
            "name": i["name"].strip(),
            "name_translated": i.get("name_translated") if isinstance(i.get("name_translated"), str) else None,
            "tags": tags,
            "certainty": i.get("certainty") if i.get("certainty") in ("confirmed", "possible") else "possible",
            "ratio_percent": i.get("ratio_percent") if isinstance(i.get("ratio_percent"), (int, float)) else None,
        })
    text = lambda k: r.get(k) if isinstance(r.get(k), str) else None
    return {
        "menu": text("menu"),
        "menu_translated": text("menu_translated"),
        "description_translated": text("description_translated"),
        "ingredients": ings,
        "custom_allergen_hits": [h for h in (r.get("custom_allergen_hits") or []) if isinstance(h, dict)],
    }


def _core(name: str) -> str:
    """메뉴명 비교용: 공백·괄호·크기 표기를 뺀다. '새우튀김우동(대)' == '새우튀김우동'"""
    t = unicodedata.normalize("NFKC", name or "")
    t = re.sub(r"[(\[].*?[)\]]", "", t)
    t = re.sub(r"(大|中|小)$", "", t.strip())
    return re.sub(r"\s+", "", t)


def _match_results(lines: list[MenuLine], results: list[dict]) -> dict:
    """LLM이 메뉴명을 조금 바꿔서 돌려줘도 결과를 버리지 않는다.
    (버리면 재료가 비어 SAFE로 나가고, 캐시에도 안 남아 매번 다시 호출한다)"""
    matched: dict[str, dict] = {}
    remaining = list(results)
    for same in (lambda a, b: a == b, lambda a, b: _core(a) == _core(b)):
        for l in lines:
            if l.name in matched:
                continue
            for r in remaining:
                if same(r.get("menu") or "", l.name):
                    matched[l.name] = r
                    remaining.remove(r)
                    break
    # 하나만 남았으면 이름이 달라도 그 메뉴의 결과로 본다 (여럿이면 엉뚱하게 붙일 수 있어 하지 않음)
    left = [l for l in lines if l.name not in matched]
    if len(left) == 1 and len(remaining) == 1:
        matched[left[0].name] = remaining[0]
    return matched


def _build_results(lines: list[MenuLine], ai_by_menu: dict, profile: DietProfile) -> list[dict]:
    known_map = {l.name: build_known_ingredients(l.name) for l in lines}
    results = []
    for line in lines:
        n = line.name
        ai = ai_by_menu.get(n, {})
        known = known_map.get(n)
        ingredients = enrich(_merge(known, ai))
        # 근거의 우선순위: 메뉴판 표기 > 메뉴명 > 공공데이터·자체 DB > AI 추론
        ingredients = menu_board.apply(ingredients, line.note)
        confirmed_tags = {t for i in ingredients if i.get("certainty") == "confirmed" for t in (i.get("tags") or [])}
        ingredients = _dedupe(ingredients + from_menu_name(n, confirmed_tags))

        # 공공데이터·자체 DB도, AI 분석도 없으면 재료 전체를 모르는 상태다.
        # 메뉴판·메뉴명에서 몇 개 알아냈더라도 양념·젓갈 같은 숨은 재료는 모른다 → SAFE로 내보내지 않는다.
        provisional = not known and not ai.get("ingredients")
        if provisional and not profile.is_empty():
            ingredients = _dedupe(ingredients + _unknown_ingredients(profile, ingredients))
        _normalize_ratios(ingredients)
        risk = evaluate(n, ingredients, profile, ai.get("menu_translated"))
        if provisional and not profile.is_empty():
            if risk["level"] == "SAFE":
                risk["level"] = "CAUTION"
            risk["notes"].append({
                "type": "no_ingredient_data",
                "message": "이 메뉴의 전체 재료 정보를 찾지 못했습니다. 주문 전 직원에게 확인하세요.",
            })

        hits = ai.get("custom_allergen_hits") or []
        for h in hits:
            lvl = "WARNING" if h.get("certainty") == "confirmed" else "CAUTION"
            if LEVEL_ORDER[lvl] > LEVEL_ORDER[risk["level"]]:
                risk["level"] = lvl

        results.append({
            "menu": n,
            "menu_note": line.note,
            "menu_translated": ai.get("menu_translated"),
            "description_translated": ai.get("description_translated"),
            "base_menu": known["base_menu"] if known else None,
            "resolved_variant": known["resolved_variant"] if known else None,
            "variant_options": known["variant_options"] if known else [],
            "matched_menu_db": bool(known),
            "data_source": _data_source(known, ingredients),
            "provisional": provisional,
            "family": known.get("family", []) if known else [],
            "ingredients": ingredients,
            "custom_allergen_hits": hits,
            "risk": risk,
        })
    return results


def _data_source(known: dict | None, ingredients: list[dict]) -> str:
    if known:
        return known.get("data_source") or "menu_base"
    if any(i.get("source") == menu_board.SOURCE and i.get("certainty") == "confirmed" for i in ingredients):
        return "menu_board"
    return "ai"


def _unknown_ingredients(profile: DietProfile, ingredients: list[dict]) -> list[dict]:
    """재료를 모를 때, 사용자가 피해야 하는 것들을 '가능성'으로 넣어 직원 질문이 생기게 한다.
    (채식 전체 목록까지 넣으면 질문이 너무 많아져서 알레르기·종교 항목만)"""
    have = {t for i in ingredients if i.get("certainty") == "confirmed" for t in (i.get("tags") or [])}
    tags = [t for t in profile.allergy_tags if t not in have]
    rel = RELIGIOUS_RULES.get(profile.religious_diet or "")
    if rel:
        tags += [t for t in sorted(rel["forbidden"]) if t not in have and t not in tags]
    if not tags:
        return []
    return [{
        "name": "·".join(KO_SHORT.get(t, (t, []))[0] for t in tags),
        "name_translated": None,
        "tags": tags,
        "certainty": "possible",
        "source": "unknown",
        "ratio_percent": None,
    }]


def re_evaluate(menu_result: dict, profile: DietProfile) -> dict:
    risk = evaluate(menu_result.get("menu") or "", menu_result.get("ingredients", []), profile, menu_result.get("menu_translated"))
    return {**menu_result, "risk": risk}
