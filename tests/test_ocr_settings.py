import io

from PIL import Image

from app.core.config import settings
from app.routers import ocr
from scripts.compare_ocr import answer_key


def _png(w, h) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, format="PNG")
    return buf.getvalue()


def test_ocr_max_side_is_configurable(monkeypatch):
    monkeypatch.setattr(settings, "OCR_MAX_SIDE", 2048)
    data, _ = ocr._compress(_png(3000, 1500))
    assert max(Image.open(io.BytesIO(data)).size) == 2048
    monkeypatch.setattr(settings, "OCR_MAX_SIDE", 1600)
    data, _ = ocr._compress(_png(3000, 1500))
    assert max(Image.open(io.BytesIO(data)).size) == 1600


def test_compare_ocr_answer_key_uses_corrected_names():
    key = answer_key()
    names = key["스크린샷 2026-09-23 193421.png"]
    assert "계란말이" in names and "게란말이" not in names     # 채점 X → 비고의 실제 이름이 정답
    assert "뼈없는닭발" in names


def test_small_photo_is_upscaled_only_when_enabled(monkeypatch):
    """10/05 평가 사진은 긴 변 576px까지 작다 → OCR_UPSCALE_TO를 켜면 키워서 보낸다."""
    monkeypatch.setattr(settings, "OCR_MAX_SIDE", 1600)
    monkeypatch.setattr(settings, "OCR_UPSCALE_TO", 0)
    data, _ = ocr._compress(_png(576, 351))
    assert Image.open(io.BytesIO(data)).size == (576, 351)          # 기본: 그대로
    monkeypatch.setattr(settings, "OCR_UPSCALE_TO", 1600)
    data, _ = ocr._compress(_png(576, 351))
    assert max(Image.open(io.BytesIO(data)).size) == 1600
