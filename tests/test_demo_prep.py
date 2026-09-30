"""시연 준비 기능 테스트 — 갑각류(영어 shellfish) 매핑, 캐시 채우기 명령."""
import io

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.services import groq_service, menuzen_knowledge
from app.services.dietary_rules import DietProfile, evaluate
from app.services.taxonomy import normalize_allergies


# ── 갑각류 ──────────────────────────────────────────────────────

def test_english_shellfish_includes_shrimp_and_crab():
    """영어권 관광객이 'Shellfish'를 고르면 새우·게도 잡혀야 한다 (프론트 선택지에 새우가 없다)."""
    tags, _ = normalize_allergies(["shellfish"])
    assert {"shellfish", "shrimp", "crab"} <= set(tags)


def test_korean_jogaeryu_stays_clams_only():
    """한국어 '조개류'는 사용자가 구분해서 고른 것이므로 조개만."""
    tags, _ = normalize_allergies(["조개류"])
    assert set(tags) == {"shellfish"}


def test_crustacean_option_catches_crab_and_shrimp():
    tags, _ = normalize_allergies(["갑각류"])
    assert set(tags) == {"shrimp", "crab"}


def test_shellfish_user_gets_warning_on_shrimp_dish():
    """프론트의 기존 'shellfish' 선택지 그대로 해물 요리의 새우가 WARNING이어야 한다."""
    profile = DietProfile.from_row({"allergies": ["shellfish"]})
    ings = [{"name": "새우", "tags": ["shrimp"], "certainty": "confirmed"}]
    assert evaluate("해물조개전골", ings, profile)["level"] == "WARNING"


def test_shrimp_only_user_is_not_warned_about_crab():
    """'새우'만 고른 사람에게 게까지 경고하지는 않는다 (선택을 존중)."""
    profile = DietProfile.from_row({"allergies": ["새우"]})
    ings = [{"name": "돌게", "tags": ["crab"], "certainty": "confirmed"}]
    assert evaluate("돌게탕", ings, profile)["level"] == "SAFE"


# ── 캐시 채우기 명령 ────────────────────────────────────────────

def _png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buf, format="PNG")
    return buf.getvalue()


def test_warm_cache_fills_cache_so_second_call_skips_llm(monkeypatch, tmp_path):
    """warm_cache를 돌리면 두 번째 분석은 LLM 없이 캐시에서 나와야 한다."""
    from scripts.warm_cache import warm

    monkeypatch.setattr(menuzen_knowledge, "load_dishes", lambda *a, **k: [])
    calls = {"ocr": 0, "analyze": 0}

    def fake(model, messages, **kw):
        content = messages[-1]["content"]
        if isinstance(content, list):  # OCR (이미지 포함)
            calls["ocr"] += 1
            return {"raw_text": "해물조개전골", "menus": [
                {"name": "해물조개전골", "price": "70,000", "note": "전복4,꽃게,새우2,낙지"}], "origin_info": []}
        calls["analyze"] += 1
        return {"results": [{"menu": "해물조개전골", "menu_translated": "Seafood hot pot",
                             "ingredients": [{"name": "전복", "tags": ["shellfish"], "certainty": "confirmed"}]}]}

    monkeypatch.setattr(groq_service, "chat_json", fake)

    photo = tmp_path / "demo.png"
    photo.write_bytes(_png_bytes())

    report = warm(TestClient(app), [photo], lang="en")

    assert report[0]["error"] is None, report[0]
    assert report[0]["menus"] == 1
    assert calls["analyze"] == 1, "두 번째 분석은 캐시에서 나와야 한다 (LLM 1번만)"
