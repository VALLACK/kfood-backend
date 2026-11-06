"""PR #10 후속: 프로필 언어별로 직원 질문이 깨지지 않는지 확인한다.

10/25 리허설에서 프로필 언어를 한국어로 두면 /analyze가 500 오류를 냈다.
한국어 질문 템플릿은 {menu}를 쓰는데 다른 언어 템플릿처럼 menu_t로만 채워서 KeyError: 'menu'가 났다.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _analyze(lang, **profile):
    body = {
        "menus": [{"name": "돼지국밥"}, {"name": "짬뽕"}],
        "skip_ai": True,  # AI 호출 없이 공공데이터·자체 DB·규칙만으로 판정
        "profile": {"preferred_language": lang, **profile},
    }
    r = client.post("/analyze", json=body)
    assert r.status_code == 200, r.text
    return r.json()["results"]


@pytest.mark.parametrize("lang", ["ko", "en", "zh", "ja"])
def test_contains_questions_work_in_every_language(lang):
    results = _analyze(lang, allergies=["shellfish"])
    questions = [q for r in results for q in r["risk"]["staff_questions"]]
    assert questions, "새우 알레르기면 돼지국밥(새우젓)·짬뽕(새우)에 직원 질문이 있어야 한다"
    for q in questions:
        assert q["translated"] and "{" not in q["translated"]
        if lang == "ko":
            assert q["translated"] == q["ko"], "한국어 사용자에게는 한국어 질문을 그대로 보여준다"


@pytest.mark.parametrize("lang", ["ko", "en", "zh", "ja"])
def test_variant_question_works_in_every_language(lang):
    """'어떤 종류인가요?' 질문(variant)도 한국어 템플릿을 쓰는 경로가 따로 있다."""
    from app.services.dietary_rules import DietProfile, evaluate

    profile = DietProfile.from_row({"allergies": ["shellfish"], "preferred_language": lang})
    ingredients = [
        {"name": "면", "tags": ["wheat"], "certainty": "confirmed", "source": "menu_base"},
        {"name": "새우", "tags": ["shrimp"], "certainty": "possible", "source": "variant", "variant": "해물짬뽕"},
        {"name": "돼지고기", "tags": ["pork"], "certainty": "possible", "source": "variant", "variant": "고기짬뽕"},
    ]
    risk = evaluate("짬뽕", ingredients, profile, "Jjamppong")
    variant = [q for q in risk["staff_questions"] if q["kind"] == "variant"]
    assert variant, "종류에 따라 새우가 들어갈 수 있으면 종류 질문이 있어야 한다"
    for q in variant:
        assert q["translated"] and "{" not in q["translated"]
        if lang == "ko":
            assert q["translated"] == q["ko"]


def test_korean_profile_keeps_same_verdict_as_english():
    """언어만 바꿨을 때 판정(위험도)이 달라지면 안 된다."""
    ko = {r["menu"]: r["risk"]["level"] for r in _analyze("ko", allergies=["shellfish"])}
    en = {r["menu"]: r["risk"]["level"] for r in _analyze("en", allergies=["shellfish"])}
    assert ko == en
