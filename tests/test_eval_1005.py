"""10/05 메뉴판 12장 재평가에서 나온 문제의 회귀 테스트."""
import json

import pytest

from app.routers.ocr import _is_drink
from app.services import groq_service, menu_board
from app.services.menuzen_knowledge import from_menu_name


def _tags(menu, confirmed=frozenset()):
    return {(t, i["certainty"]) for i in from_menu_name(menu, set(confirmed)) for t in i["tags"]}


# ── 메뉴명 줄임말 ─────────────────────────────────────────────

@pytest.mark.parametrize("menu", ["수백당곱새세트", "수백당곱새", "낙곱새볶음", "낙새볶음", "낙삼새볶음"])
def test_busan_abbreviation_sae_means_shrimp(menu):
    """'곱새'·'낙새'의 '새'는 새우. 수백당곱새세트가 새우 알레르기에 SAFE로 나왔던 문제."""
    assert ("shrimp", "confirmed") in _tags(menu)


def test_naksamsae_has_pork():
    assert ("pork", "confirmed") in _tags("낙삼새볶음")


def test_sae_rule_does_not_hit_unrelated_menus():
    for menu in ("낙지볶음", "낙곱볶음", "새송이버섯구이", "수백당곱"):
        assert ("shrimp", "confirmed") not in _tags(menu), menu


# ── 카츠 ─────────────────────────────────────────────────────

@pytest.mark.parametrize("menu", ["등심카츠", "안심카츠", "로스카츠", "히레카츠"])
def test_pork_cut_katsu_is_confirmed_pork(menu):
    assert ("pork", "confirmed") in _tags(menu)


@pytest.mark.parametrize("menu", ["명란카츠", "치즈카츠", "초밥카츠"])
def test_unknown_katsu_asks_about_pork(menu):
    """고기 종류가 이름에 없는 카츠 → 돼지고기 확인 질문 (명란카츠가 할랄에 SAFE로 나왔던 문제)."""
    assert ("pork", "possible") in _tags(menu)


@pytest.mark.parametrize("menu", ["생선카츠", "치킨카츠", "규카츠", "새우카츠"])
def test_non_pork_katsu_is_not_flagged(menu):
    assert not any(t == "pork" for t, _ in _tags(menu))


# ── 국밥·수육 새우젓 ──────────────────────────────────────────

@pytest.mark.parametrize("menu", ["순대국밥", "수육 - 소", "수육백반", "마늘수육", "어린이국밥"])
def test_gukbap_and_suyuk_ask_about_saeujeot(menu):
    names = {i["name"] for i in from_menu_name(menu, set()) if "shrimp" in i["tags"]}
    assert "새우젓" in names


def test_agu_suyuk_does_not_ask_saeujeot():
    assert not any("shrimp" in i["tags"] for i in from_menu_name("아구수육", set()))


def test_saeujeot_not_added_when_shrimp_already_confirmed():
    assert not any(i["name"] == "새우젓" for i in from_menu_name("새우국밥", set()))


# ── 메뉴판 원산지 표기의 돼지 지방 ──────────────────────────────

@pytest.mark.parametrize("note", ["3 pcs (돈지방:국내산)", "3 pcs (돈지망:국내산)"])
def test_pork_fat_in_board_note(note):
    """딤섬집 '춘권(돈지방:국내산)'이 할랄에 SAFE로 나왔던 문제. '돈지망'은 실제 OCR 오인식."""
    assert any("pork" in i["tags"] for i in menu_board.parse(note))


def test_salad_is_not_lard():
    assert not any("pork" in i["tags"] for i in menu_board.parse("샐러드"))


# ── 음료 제외 ─────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["청하/별빛청하", "빅웨이브", "강서 마일드 에일", "담서 오렌지 에일",
                                  "탄타카토닉", "소주, 맥주", "화요"])
def test_drinks_are_skipped(name):
    assert _is_drink(name)


@pytest.mark.parametrize("name", ["청경채 / 초이삼 데침", "털게찜, 과메기", "맑은국 우동,곤약사리", "새우튀김",
                                  "수육 - 소", "맥주 수육"])
def test_food_is_not_skipped(name):
    assert not _is_drink(name)


# ── OCR 출력 한도 (Groq 비전 모델 분당 출력 1000토큰) ─────────────

def test_ocr_does_not_request_raw_text_and_stays_under_otpm(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.routers import ocr

    seen = {}

    def fake(model, messages, max_tokens=0, **extra):
        seen["max_tokens"], seen["extra"] = max_tokens, extra
        seen["prompt"] = messages[0]["content"][1]["text"]
        return {"menus": [{"name": "돼지국밥", "price": "10,000"}, {"name": "소주"}], "origin_info": []}

    monkeypatch.setattr(groq_service, "chat_json", fake)
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buf, format="PNG")
    r = TestClient(app).post("/ocr", files={"file": ("m.png", buf.getvalue(), "image/png")})

    assert r.status_code == 200
    body = r.json()
    assert seen["max_tokens"] <= 1000
    assert "raw_text" not in seen["prompt"]
    assert seen["extra"].get("reasoning_effort") == "none"
    assert body["text"] == "돼지국밥"                       # 프론트 호환용 text는 메뉴명 목록
    assert body["menus"] == [{"name": "돼지국밥", "price": "10,000", "note": None}]
    assert body["skipped"] == ["소주"]
    assert ocr.OCR_MAX_TOKENS <= 1000


def test_truncated_json_keeps_complete_menus():
    text = '{"menus": [{"name": "아구찜", "price": "40,000"}, {"name": "아구탕", "note": "大"}, {"name": "된장'
    assert groq_service.parse_json(text) == {"menus": [{"name": "아구찜", "price": "40,000"},
                                                       {"name": "아구탕", "note": "大"}]}


def test_request_too_large_fails_fast_without_retry(monkeypatch):
    """요청 하나가 분당 한도보다 크면 기다려도 소용없다 → 재시도하지 않고 바로 실패(10/05: 77초 대기)."""
    import httpx
    from fastapi import HTTPException
    from groq import RateLimitError

    calls = []
    req = httpx.Request("POST", "https://api.groq.com/x")
    resp = httpx.Response(429, request=req, json={})

    class Client:
        class chat:
            class completions:
                @staticmethod
                def create(**k):
                    calls.append(1)
                    raise RateLimitError("Request too large for model on output tokens per minute (OTPM)",
                                         response=resp, body=None)

    monkeypatch.setattr(groq_service, "get_client", lambda: Client)
    monkeypatch.setattr(groq_service.time, "sleep", lambda s: pytest.fail("기다리면 안 된다"))
    with pytest.raises(HTTPException):
        groq_service.chat_json("m", [], max_tokens=10)
    assert len(calls) == 1


def test_unsupported_option_is_dropped_one_by_one(monkeypatch):
    """모델이 reasoning_effort를 모르면 그것만 빼고, reasoning_format은 유지한다."""
    import httpx
    from groq import BadRequestError

    sent = []
    req = httpx.Request("POST", "https://api.groq.com/x")

    class Msg:
        content = json.dumps({"ok": 1})

    class Resp:
        choices = [type("C", (), {"message": Msg})]

    class Client:
        class chat:
            class completions:
                @staticmethod
                def create(**k):
                    sent.append(dict(k))
                    if "reasoning_effort" in k:
                        raise BadRequestError("`reasoning_effort` is not supported with this model",
                                              response=httpx.Response(400, request=req, json={}), body=None)
                    return Resp

    monkeypatch.setattr(groq_service, "get_client", lambda: Client)
    assert groq_service.chat_json("m", [], reasoning_effort="none", reasoning_format="hidden") == {"ok": 1}
    assert "reasoning_format" in sent[-1] and "reasoning_effort" not in sent[-1]
