"""11/25 부산 현장 테스트 후속 + PR #18 후속.

1. '대맥 기장칼국수'(기장 해산물 칼국수)가 새우 알레르기에 SAFE로 나옴
   → 메뉴명의 '기장'(부산 기장군)을 해산물 가능성으로 본다. 곡물 기장 메뉴는 예외.
2. 메뉴명으로 꿀을 확정할 때 재료 이름이 'honey'로 나옴 → '꿀'
3. 이름 포함 규칙의 오탐: '꿀꿀이죽'(꿀), '에비앙'(새우)
"""
import pytest

from app.models.schemas import MenuLine
from app.services import analysis_service, groq_service
from app.services.dietary_rules import DietProfile
from app.services.menuzen_knowledge import from_menu_name


def P(**row):
    return DietProfile.from_row(row)


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    monkeypatch.setattr(groq_service, "chat_json", lambda *a, **k: {"results": []})


def _level(name, **profile):
    return analysis_service.analyze([MenuLine(name=name)], None, P(**profile), skip_ai=True)[0]["risk"]["level"]


# ── 1. 기장 = 해산물 산지 ─────────────────────────────────────

@pytest.mark.parametrize("menu", ["대맥 기장칼국수", "기장칼국수", "기장 해물칼국수"])
@pytest.mark.parametrize("allergy", ["새우", "조개"])
def test_gijang_noodle_is_not_safe_for_seafood_allergy(menu, allergy):
    assert _level(menu, allergies=[allergy]) != "SAFE"


def test_gijang_marks_seafood_as_possible_not_confirmed():
    tags = {t: i["certainty"] for i in from_menu_name("대맥 기장칼국수", set()) for t in i["tags"]}
    assert tags == {"shrimp": "possible", "shellfish": "possible", "squid": "possible"}


@pytest.mark.parametrize("menu", ["기장밥", "찰기장밥", "기장떡"])
def test_grain_gijang_is_not_seafood(menu):
    assert not any(t in ("shrimp", "shellfish", "squid")
                   for i in from_menu_name(menu, set()) for t in i["tags"])


# ── 2. 꿀 재료 이름 ──────────────────────────────────────────

def test_honey_from_menu_name_is_named_in_korean():
    names = [i["name"] for i in from_menu_name("꿀 호떡", set()) if "honey" in i["tags"]]
    assert names == ["꿀"]


def test_honey_hotteok_still_not_vegan():
    assert _level("꿀 호떡", vegetarian_type="vegan") != "SAFE"


# ── 3. 이름 포함 규칙 오탐 ────────────────────────────────────

@pytest.mark.parametrize("menu, tag", [("꿀꿀이죽", "honey"), ("에비앙", "shrimp")])
def test_name_rule_false_positives(menu, tag):
    assert tag not in {t for i in from_menu_name(menu, set()) for t in i["tags"]}


def test_ebi_still_shrimp():
    assert "shrimp" in {t for i in from_menu_name("에비돈코츠라멘", set()) for t in i["tags"]}
