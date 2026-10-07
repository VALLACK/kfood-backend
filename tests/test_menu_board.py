"""메뉴판 표기 재료 반영 테스트.

실사용 검증(메뉴판 사진 2장, 56건)에서 나온 SAFE 오판 4건을 그대로 회귀 테스트로 만든다.
  - 돌게탕 / 돌게탕(대) / 해물조개전골 : 메뉴판에 '새우2'가 적혀 있는데 새우 알레르기 SAFE
  - 수육백반 (일반, 항정살)          : 수육=돼지고기인데 할랄 SAFE
"""
from app.services import menu_board
from app.services.dietary_rules import DietProfile, evaluate
from app.services.menuzen_knowledge import from_menu_name

DOLGE_NOTE = "전복2,가리비2,오징어中,꽃게,새우2,낙지,대구,알,곤,조개다수"


def _shrimp_profile():
    return DietProfile.from_row({"allergies": {"새우": "심각"}, "preferred_language": "en"})


def _halal_profile():
    return DietProfile.from_row({"religious_diet": "halal", "preferred_language": "en"})


# ── 메뉴판 표기 파싱 ────────────────────────────────────────────

def test_parse_picks_up_shrimp_from_menu_board():
    names = {i["name"] for i in menu_board.parse(DOLGE_NOTE)}
    assert "새우" in names
    assert "꽃게" in names
    assert "전복" in names


def test_parse_marks_board_ingredients_as_confirmed():
    assert all(i["certainty"] == "confirmed" for i in menu_board.parse(DOLGE_NOTE))
    assert all(i["source"] == "menu_board" for i in menu_board.parse(DOLGE_NOTE))


def test_parse_ignores_portion_and_origin_only_notes():
    assert menu_board.parse("(3~4인분) 국내산 2마리 400g이상") == []
    assert menu_board.parse("") == []
    assert menu_board.parse(None) == []


def test_apply_promotes_existing_possible_ingredient_to_confirmed():
    before = [{"name": "새우", "tags": ["shrimp"], "certainty": "possible", "source": "ai"}]
    after = menu_board.apply(before, DOLGE_NOTE)
    shrimp = [i for i in after if i["name"] == "새우"]
    assert len(shrimp) == 1, "같은 재료가 중복 추가되면 안 된다"
    assert shrimp[0]["certainty"] == "confirmed"


def test_apply_keeps_original_list_untouched():
    before = [{"name": "새우", "tags": ["shrimp"], "certainty": "possible", "source": "ai"}]
    menu_board.apply(before, DOLGE_NOTE)
    assert before[0]["certainty"] == "possible"


# ── 오판 회귀 테스트 ───────────────────────────────────────────

def test_dolgetang_is_not_safe_for_shrimp_allergy():
    """메뉴판에 '새우2'가 적힌 돌게탕이 SAFE로 나오면 안 된다."""
    ingredients = menu_board.apply([], DOLGE_NOTE)
    risk = evaluate("돌게탕", ingredients, _shrimp_profile())
    assert risk["level"] == "WARNING"
    assert any("새우" in r["ingredient"] for r in risk["confirmed_reasons"])


def test_haemul_jogae_jeongol_is_not_safe_for_shrimp_allergy():
    note = "3~4인분,전복4,가리비4,오징어大,꽃게,새우2,낙지,어묵,조개류다수"
    risk = evaluate("해물조개전골", menu_board.apply([], note), _shrimp_profile())
    assert risk["level"] == "WARNING"


def test_suyuk_baekban_is_not_safe_for_halal():
    """수육백반은 메뉴 DB에 없어도(ai 추론) 돼지고기로 잡혀야 한다."""
    ingredients = from_menu_name("수육백반 (일반, 항정살)", set())
    assert any("pork" in i["tags"] for i in ingredients)
    risk = evaluate("수육백반 (일반, 항정살)", ingredients, _halal_profile())
    assert risk["level"] == "WARNING"


def test_agu_suyuk_is_not_tagged_as_pork():
    """'아구수육'은 생선 요리라 돼지고기 규칙에서 빠져야 한다."""
    assert not any("pork" in i["tags"] for i in from_menu_name("아구수육", set()))


def test_menu_name_rule_does_not_duplicate_already_confirmed_tag():
    assert from_menu_name("돼지갈비", {"pork"}) == []
    # 국밥은 새우젓 확인 질문이 추가로 붙지만, 돼지고기는 중복으로 넣지 않는다
    assert [i["name"] for i in from_menu_name("돼지국밥", {"pork"})] == ["새우젓"]


# ── 파이프라인 전체 (AI가 재료를 빠뜨린 상황) ──────────────────

def test_pipeline_uses_menu_board_when_ai_misses_shrimp(monkeypatch):
    """AI가 새우를 빠뜨려도 메뉴판 표기로 잡아낸다 — 실사용 검증 오판의 실제 재현."""
    from app.models.schemas import MenuLine
    from app.services import analysis_service, groq_service

    # AI가 '돌게탕 = 게, 채소'로만 답한 상황 (실제 실행에서 SAFE가 나온 원인)
    monkeypatch.setattr(groq_service, "chat_json", lambda *a, **k: {
        "results": [{"menu": "돌게탕", "menu_translated": "Crab stew",
                     "ingredients": [{"name": "돌게", "tags": ["crab"], "certainty": "confirmed", "ratio_percent": 60}]}]
    })
    monkeypatch.setattr(analysis_service, "build_known_ingredients", lambda name: None)

    without_note = analysis_service.analyze([MenuLine(name="돌게탕")], None, _shrimp_profile())
    with_note = analysis_service.analyze([MenuLine(name="돌게탕", note=DOLGE_NOTE)], None, _shrimp_profile())

    assert without_note[0]["risk"]["level"] == "SAFE", "메뉴판 표기가 없으면 AI 결과 그대로 (오판 재현)"
    assert with_note[0]["risk"]["level"] == "WARNING", "메뉴판 표기가 있으면 새우를 잡아야 한다"
    assert with_note[0]["menu_note"] == DOLGE_NOTE


def test_pipeline_applies_menu_name_rule_without_db_match(monkeypatch):
    from app.models.schemas import MenuLine
    from app.services import analysis_service, groq_service

    monkeypatch.setattr(groq_service, "chat_json", lambda *a, **k: {
        "results": [{"menu": "수육백반", "ingredients": [{"name": "밥", "tags": [], "certainty": "confirmed"}]}]
    })
    monkeypatch.setattr(analysis_service, "build_known_ingredients", lambda name: None)

    out = analysis_service.analyze([MenuLine(name="수육백반")], None, _halal_profile())
    assert out[0]["risk"]["level"] == "WARNING"


def test_same_ingredient_from_two_sources_is_not_duplicated():
    """메뉴명 규칙과 메뉴판 표기가 같은 재료를 넣어도 한 번만 남아야 한다."""
    from app.services.analysis_service import _dedupe
    ings = [
        {"name": "새우", "tags": ["shrimp"], "certainty": "possible", "source": "menu_name"},
        {"name": "새우", "tags": ["shrimp"], "certainty": "confirmed", "source": "menu_board"},
    ]
    out = _dedupe(ings)
    assert len(out) == 1
    assert out[0]["certainty"] == "confirmed", "확정도가 높은 쪽이 남아야 한다"


def test_large_size_shares_ingredient_note_with_small():
    """'大 70,000'처럼 크기만 적힌 칸도 같은 메뉴의 재료 설명을 받아야 한다."""
    from app.routers.ocr import _share_notes
    menus = [
        {"name": "해물탕", "price": "55,000", "note": "전복2,가리비2,꽃게,새우2,낙지,조개다수"},
        {"name": "해물탕(대)", "price": "70,000", "note": "大"},
    ]
    out = _share_notes(menus)
    assert "새우" in out[1]["note"], "대 사이즈도 새우를 알아야 소/대 판정이 갈리지 않는다"


# ── 캐시 (속도) ────────────────────────────────────────────────

def test_second_profile_reuses_cache_without_calling_llm(monkeypatch, tmp_path):
    """같은 메뉴를 다른 프로필로 다시 보면 LLM을 부르지 않아야 한다."""
    from app.models.schemas import MenuLine
    from app.services import analysis_cache, analysis_service, groq_service

    monkeypatch.setattr(analysis_cache, "PATH", tmp_path / "cache.json")
    analysis_cache.clear()

    calls = []

    def fake(*a, **k):
        calls.append(1)
        return {"results": [{"menu": "제육볶음", "menu_translated": "Spicy stir-fried pork",
                             "ingredients": [{"name": "돼지고기", "tags": ["pork"],
                                              "certainty": "confirmed", "ratio_percent": 40}]}]}

    monkeypatch.setattr(groq_service, "chat_json", fake)
    monkeypatch.setattr(analysis_service, "build_known_ingredients", lambda name: None)

    line = [MenuLine(name="제육볶음")]
    first = analysis_service.analyze(line, None, _halal_profile())
    second = analysis_service.analyze(line, None, _shrimp_profile())

    assert len(calls) == 1, "두 번째 프로필에서는 LLM을 부르면 안 된다"
    assert first[0]["risk"]["level"] == "WARNING"   # 할랄 → 돼지고기
    assert second[0]["risk"]["level"] == "SAFE"     # 새우 알레르기 → 관계없음
    analysis_cache.clear()


def test_cache_does_not_store_empty_result(tmp_path, monkeypatch):
    from app.services import analysis_cache
    monkeypatch.setattr(analysis_cache, "PATH", tmp_path / "c.json")
    analysis_cache.clear()
    analysis_cache.put("짬뽕", None, "en", {"menu": "짬뽕", "ingredients": []})
    assert analysis_cache.get("짬뽕", None, "en") is None, "빈 결과를 캐시하면 오류가 굳어버린다"
    analysis_cache.clear()


def test_skip_ai_gives_verdict_without_calling_llm(monkeypatch, tmp_path):
    """즉시 판정 모드: 공공데이터·메뉴판 표기만으로 LLM 없이 위험도가 나와야 한다."""
    from app.models.schemas import MenuLine
    from app.services import analysis_cache, analysis_service, groq_service

    monkeypatch.setattr(analysis_cache, "PATH", tmp_path / "c.json")
    analysis_cache.clear()

    def boom(*a, **k):
        raise AssertionError("즉시 판정 모드에서는 LLM을 부르면 안 된다")

    monkeypatch.setattr(groq_service, "chat_json", boom)
    monkeypatch.setattr(analysis_service, "build_known_ingredients", lambda name: None)

    out = analysis_service.analyze(
        [MenuLine(name="해물조개전골", note="전복4,가리비4,꽃게,새우2,낙지,조개다수"),
         MenuLine(name="수육백반")],
        None, _shrimp_profile(), skip_ai=True,
    )
    assert out[0]["risk"]["level"] == "WARNING"          # 메뉴판 표기의 새우
    assert out[0]["data_source"] == "menu_board"         # 판정 근거가 메뉴판임을 표시
    # 수육백반: 돼지고기인 건 알지만 나머지 재료(새우젓 등)는 모른다 → SAFE 금지, 직원 질문
    assert out[1]["risk"]["level"] == "CAUTION"
    assert out[1]["provisional"] is True
    assert any("새우" in q["ko"] for q in out[1]["risk"]["staff_questions"])
    analysis_cache.clear()
