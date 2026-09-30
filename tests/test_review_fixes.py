"""독립 코드 리뷰(9건)에서 재현된 결함의 회귀 테스트.

각 테스트 이름 앞 번호는 리뷰 보고서의 번호다.
알레르기 앱에서 가장 나쁜 결과는 '위험한데 SAFE'이므로 그 경우를 중심으로 고정한다.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import MenuLine
from app.services import analysis_cache, analysis_service, groq_service, menuzen_knowledge
from app.services.dietary_rules import DietProfile


def P(**row):
    return DietProfile.from_row(row)


@pytest.fixture
def no_db(monkeypatch):
    monkeypatch.setattr(analysis_service, "build_known_ingredients", lambda name: None)


def _llm(monkeypatch, results):
    calls = []

    def fake(*a, **k):
        calls.append(1)
        return {"results": results}

    monkeypatch.setattr(groq_service, "chat_json", fake)
    return calls


# ── 1. 근거 없는 SAFE 금지 ─────────────────────────────────────

def test_01_skip_ai_unknown_menu_is_not_safe(no_db, monkeypatch):
    _llm(monkeypatch, [])
    out = analysis_service.analyze([MenuLine(name="대게찜")], None, P(allergies=["게"]), skip_ai=True)
    assert out[0]["risk"]["level"] != "SAFE"
    assert out[0]["provisional"] is True


def test_01_board_only_menu_with_unlisted_allergen_is_not_safe(no_db, monkeypatch):
    """메뉴판에 적힌 재료만으로는 양념·젓갈을 모른다 → SAFE 금지."""
    _llm(monkeypatch, [])
    out = analysis_service.analyze([MenuLine(name="모둠탕", note="대구, 명태")], None,
                                   P(allergies=["새우"]), skip_ai=True)
    assert out[0]["risk"]["level"] == "CAUTION"
    assert out[0]["risk"]["staff_questions"], "직원에게 물어볼 질문이 있어야 한다"


def test_01_menu_with_db_data_can_still_be_safe(monkeypatch):
    """DB 근거가 있으면 SAFE를 막지 않는다 (시연의 소갈비찜)."""
    _llm(monkeypatch, [])
    out = analysis_service.analyze([MenuLine(name="소갈비찜")], None, P(allergies=["shellfish"]), skip_ai=True)
    assert out[0]["matched_menu_db"] is True
    assert out[0]["risk"]["level"] == "SAFE"


# ── 2. 메뉴명의 게·생선 ───────────────────────────────────────

@pytest.mark.parametrize("menu", ["홍게라면", "대게찜", "킹크랩구이", "게살볶음밥", "간장게장"])
def test_02_crab_in_menu_name_is_warning(menu, monkeypatch):
    _llm(monkeypatch, [])
    out = analysis_service.analyze([MenuLine(name=menu)], None, P(allergies=["게"]), skip_ai=True)
    assert out[0]["risk"]["level"] == "WARNING", out[0]["ingredients"]


def test_02_moodum_spelling_variant():
    tags = {t for i in menuzen_knowledge.from_menu_name("해물모둠", set()) for t in i["tags"]}
    assert "shrimp" in tags


# ── 3. LLM이 메뉴명을 바꿔서 돌려줘도 결과 유지 ──────────────────

def test_03_llm_renamed_menu_is_still_matched(no_db, monkeypatch):
    calls = _llm(monkeypatch, [{"menu": "새우튀김우동", "menu_translated": "Shrimp tempura udon",
                                "ingredients": [{"name": "튀김옷", "tags": ["egg"], "certainty": "confirmed"}]}])
    line = [MenuLine(name="새우튀김우동(대)")]
    out = analysis_service.analyze(line, None, P(allergies=["계란"]))
    assert out[0]["risk"]["level"] == "WARNING"
    assert out[0]["menu_translated"] == "Shrimp tempura udon"
    analysis_service.analyze(line, None, P(allergies=["계란"]))
    assert len(calls) == 1, "두 번째는 캐시에서 나와야 한다"


# ── 4. 메뉴판 메모의 공백·해산물 ────────────────────────────────

def test_04_spaced_note_is_parsed(no_db, monkeypatch):
    _llm(monkeypatch, [])
    out = analysis_service.analyze([MenuLine(name="모둠탕", note="새 우 2, 꽃 게")], None,
                                   P(allergies=["새우"]), skip_ai=True)
    assert out[0]["risk"]["level"] == "WARNING"


@pytest.mark.parametrize("note,allergy", [("굴, 홍게, 대게", "게"), ("굴, 소라", "조개류"), ("대구, 명태", "생선")])
def test_04_board_seafood_keywords(note, allergy, no_db, monkeypatch):
    _llm(monkeypatch, [])
    out = analysis_service.analyze([MenuLine(name="모둠탕", note=note)], None, P(allergies=[allergy]), skip_ai=True)
    assert out[0]["risk"]["level"] == "WARNING"


# ── 5. 잘못된 형식의 LLM 출력 ─────────────────────────────────

def test_05_string_ingredients_do_not_crash_or_poison_cache(no_db, monkeypatch):
    _llm(monkeypatch, [{"menu": "해물볶음", "ingredients": ["새우", "오징어"]}])
    out = analysis_service.analyze([MenuLine(name="해물볶음")], None, P(allergies=["새우"]))
    # 확정 여부 없이 이름만 온 재료는 '가능성' → 직원 확인 (SAFE는 절대 아님)
    assert out[0]["risk"]["level"] in ("CAUTION", "WARNING")
    assert any(i["name"] == "새우" and "shrimp" in i["tags"] for i in out[0]["ingredients"])
    out2 = analysis_service.analyze([MenuLine(name="해물볶음")], None, P(allergies=["새우"]))  # 캐시 경로
    assert out2[0]["risk"]["level"] == out[0]["risk"]["level"], "캐시에서 꺼내도 같은 판정"


def test_05_string_tags_are_not_split_into_letters(no_db, monkeypatch):
    _llm(monkeypatch, [{"menu": "튀김", "ingredients": [{"name": "튀김재료", "tags": "shrimp", "certainty": "confirmed"}]}])
    out = analysis_service.analyze([MenuLine(name="튀김")], None, P(allergies=["새우"]))
    assert out[0]["risk"]["level"] == "WARNING"


# ── 6. 사용자 정의 알레르기가 다른 사용자에게 섞이지 않음 ─────────────

def test_06_custom_allergen_hits_are_not_shared_between_profiles(no_db, monkeypatch):
    def fake(model, messages, **kw):
        text = messages[-1]["content"]
        hits = [{"allergy": "키위", "ingredient": "키위", "certainty": "confirmed"}] if "키위" in text else []
        return {"results": [{"menu": "과일샐러드", "ingredients": [{"name": "키위", "tags": [], "certainty": "confirmed"}],
                             "custom_allergen_hits": hits}]}
    monkeypatch.setattr(groq_service, "chat_json", fake)
    kiwi = analysis_service.analyze([MenuLine(name="과일샐러드")], None, P(allergies=["키위"]))
    mango = analysis_service.analyze([MenuLine(name="과일샐러드")], None, P(allergies=["망고"]))
    assert kiwi[0]["risk"]["level"] == "WARNING"
    assert not mango[0]["custom_allergen_hits"], "키위 사용자의 결과가 망고 사용자에게 섞이면 안 된다"


# ── 7. 캐시 키 정규화 + AI 장애 시 전체 실패 대신 판정 ────────────

def test_07_cache_hits_even_if_ocr_spacing_differs(no_db, monkeypatch):
    calls = _llm(monkeypatch, [{"menu": "해물탕", "ingredients": [{"name": "새우", "tags": ["shrimp"], "certainty": "confirmed"}]}])
    analysis_service.analyze([MenuLine(name="해물탕", note="전복2,가리비2")], None, P(allergies=["새우"]))
    analysis_service.analyze([MenuLine(name="해물탕", note=" 전복2, 가리비2 ")], None, P(allergies=["새우"]))
    assert len(calls) == 1


def test_07_daily_limit_falls_back_instead_of_failing(no_db, monkeypatch):
    def exhausted(*a, **k):
        raise groq_service.AIUnavailable("tokens per day")
    monkeypatch.setattr(groq_service, "chat_json", exhausted)
    out = analysis_service.analyze(
        [MenuLine(name="해물조개전골", note="새우2,꽃게"), MenuLine(name="대게찜")], None, P(allergies=["게"]))
    assert [r["risk"]["level"] for r in out] == ["WARNING", "WARNING"]


def test_07_daily_limit_is_not_retried(monkeypatch):
    """하루 한도 소진은 기다려도 안 풀리므로 재시도하지 않는다 (시연 중 수 분 멈춤 방지)."""
    from groq import RateLimitError
    import httpx
    tried = []

    class Fake:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    tried.append(1)
                    req = httpx.Request("POST", "https://x")
                    raise RateLimitError("Rate limit reached ... tokens per day (TPD): Limit 200000",
                                         response=httpx.Response(429, request=req), body=None)
    monkeypatch.setattr(groq_service, "get_client", lambda: Fake)
    with pytest.raises(groq_service.AIUnavailable):
        groq_service.chat_json("m", [{"role": "user", "content": "x"}])
    assert len(tried) == 1


# ── 8. 음식이 음료로 잘못 빠지지 않음 ─────────────────────────

@pytest.mark.parametrize("name", ["와인삼겹살", "카스테라", "라면사리", "새로운 해물찜", "테라스 스테이크", "소주잔치국수"])
def test_08_food_is_not_skipped_as_drink(name):
    from app.routers.ocr import _is_drink
    assert not _is_drink(name)


@pytest.mark.parametrize("name", ["소주", "맥주(대)", "보해복분자", "부산생탁", "진로,참이슬", "음료수", "대선"])
def test_08_drinks_are_skipped(name):
    from app.routers.ocr import _is_drink
    assert _is_drink(name)


# ── 9. 표시 근거·qna 방어 ─────────────────────────────────────

def test_09_board_based_verdict_says_menu_board(no_db, monkeypatch):
    _llm(monkeypatch, [])
    out = analysis_service.analyze([MenuLine(name="해물조개전골", note="새우2")], None, P(allergies=["새우"]), skip_ai=True)
    assert out[0]["data_source"] == "menu_board"


def test_09_confirm_without_menu_key_does_not_500():
    r = TestClient(app).post("/qna/confirm", json={
        "menu_result": {"ingredients": [], "risk": {}},
        "question": {"kind": "contains", "ingredient": "새우", "tag": "shrimp"},
        "staff_answer": "아니요", "input_type": "text", "profile": {"allergies": ["새우"]}})
    assert r.status_code != 500, r.text
