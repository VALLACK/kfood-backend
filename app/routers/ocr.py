import base64
import io
import re

from fastapi import APIRouter, HTTPException, UploadFile
from PIL import Image, ImageOps

from app.core.config import settings
from app.services import groq_service, menu_board

router = APIRouter(tags=["ocr"])

ALLOWED = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}

# 음료·주류·공기밥 등 성분 분석이 필요 없는 항목 (분석 호출 절약)
# 음료·주류·공기밥 등 성분 분석이 필요 없는 항목 (분석 호출 절약)
# 이름이 정확히 이것이면 제외 — 부분 일치로 하면 '와인삼겹살', '카스테라', '새로운 해물찜'까지 빠진다.
SKIP_EXACT = {
    "소주", "맥주", "막걸리", "청하", "동동주", "백세주", "설중매", "매실마을", "정종", "사케", "와인",
    "위스키", "탁주", "청주", "좋은데이", "해오름", "가을국화", "대선", "강알리", "진로", "참이슬", "테라",
    "카스", "아사히", "삿포로", "새로", "처음처럼", "산사춘", "칵테일", "토닉", "하이볼", "소맥",
    "빅웨이브", "별빛청하", "화요", "에이드",
    "음료", "음료수", "콜라", "사이다", "주스", "커피", "아메리카노", "라떼", "생수", "공기밥", "공깃밥",
}
# 음식 이름에 섞일 일이 없는 단어는 부분 일치로 제외 ('보해복분자', '부산생탁', '진로,참이슬')
SKIP_CONTAINS = ("소주", "맥주", "막걸리", "생맥", "생탁", "음료", "복분자", "참이슬", "처음처럼", "에이드",
                 "하이볼", "아메리카노", "공기밥", "공깃밥", "에일", "라거", "토닉", "청하")


# 이 글자가 들어 있으면 음식으로 본다 ('소주잔치국수', '막걸리찜닭', '맥주 수육')
FOOD_HINTS = ("국수", "탕", "찌개", "볶음", "구이", "찜", "전골", "면", "스테이크", "국", "튀김",
              "무침", "회", "닭", "갈비", "수육", "삼겹", "살")


def _is_drink(name: str) -> bool:
    base = re.sub(r"\s+", "", re.sub(r"[(（\[].*$", "", name))   # 괄호 앞부분만, 공백 제거
    parts = [x for x in re.split(r"[/,·]", base) if x]
    if len(parts) > 1 and all(_is_drink(x) for x in parts):    # '청하/별빛청하', '소주,맥주'
        return True
    if base in SKIP_EXACT:
        return True
    if len(base) > 2 and base[-1] in "대중소大中小" and base[:-1] in SKIP_EXACT:  # '맥주대'
        return True
    if any(h in name for h in FOOD_HINTS):
        return False
    return any(k in name for k in SKIP_CONTAINS)


OCR_PROMPT = """이 이미지는 한국 음식점 메뉴판(또는 원산지 표시판)이다.
메뉴를 추출해서 아래 JSON 하나로만 답해라. 설명·생각 과정은 쓰지 말 것.
{"menus": [{"name": "<메뉴명>", "price": "<가격 문자열>", "note": "<재료 설명>"}],
 "origin_info": ["<원산지 표시 문구>"]}
- 가격이 없으면 price 키를, 재료 설명이 없으면 note 키를 **생략**할 것 (null 쓰지 말 것). 원산지가 없으면 빈 배열.
- 메뉴명 오타·인식 오류는 자연스러운 한국 음식명으로 교정
- note: 메뉴명 옆이나 아래에 괄호로 재료가 적혀 있으면 그 문구를 **고치지 말고 그대로** 옮길 것.
  예) "돌게탕 (전복2,가리비2,오징어中,꽃게,새우2,낙지,대구,알,곤,조개다수)"
      → {"name": "돌게탕", "price": "40,000", "note": "전복2,가리비2,오징어中,꽃게,새우2,낙지,대구,알,곤,조개다수"}
  인분·중량·원산지만 적힌 괄호(예: "3~4인분", "국내산 400g이상")도 note에 그대로 넣을 것.
- 같은 메뉴에 가격이 둘(소/대)이면 두 줄로 나누고, 큰 쪽 이름 끝에 "(대)"를 붙일 것.
  이때 **재료 설명(note)은 소·대 양쪽에 똑같이** 넣을 것. (큰 쪽 칸에는 보통 "大"와 가격만 적혀 있다)
- 가게 이름, 영업시간, 안내 문구는 menus에 넣지 말 것
- 메뉴판 전체 글자를 옮겨 적지 말 것. menus와 origin_info만 답할 것"""

# Groq 무료 등급의 비전 모델은 '분당 출력 토큰'이 1000개로 제한된다(OTPM).
# 10/05 평가에서 메뉴판 원문(raw_text)까지 받느라 한도를 넘어 OCR이 실패했다.
# 원문은 프론트가 쓰지 않으므로 받지 않고, 출력 상한도 한도 안으로 둔다.
OCR_MAX_TOKENS = 1000


def _share_notes(menus: list[dict]) -> list[dict]:
    """같은 메뉴의 소/대가 따로 잡히면 재료 설명을 공유한다.

    메뉴판의 큰 사이즈 칸에는 "大 70,000"처럼 크기·가격만 적혀 있어서
    note가 비거나 "大"만 들어온다. 그대로 두면 같은 메뉴인데 소는 WARNING,
    대는 CAUTION으로 갈리는 문제가 생긴다.
    """
    def richness(note):
        return len(menu_board.parse(note))

    best: dict[str, str] = {}
    for m in menus:
        base = m["name"].replace("(대)", "").replace("(소)", "").strip()
        if richness(m.get("note")) > richness(best.get(base)):
            best[base] = m.get("note") or ""
    for m in menus:
        base = m["name"].replace("(대)", "").replace("(소)", "").strip()
        if richness(best.get(base)) > richness(m.get("note")):
            m["note"] = best[base]
    return menus


def _compress(data: bytes) -> tuple[bytes, str]:
    """Groq base64 이미지 한도(4MB) 대응: 긴 변 1600px, JPEG 재인코딩."""
    if len(data) <= settings.MAX_IMAGE_BYTES:
        try:
            Image.open(io.BytesIO(data)).verify()
        except Exception:
            raise HTTPException(status_code=400, detail="이미지를 읽을 수 없습니다.")
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    img.thumbnail((1600, 1600))
    quality = 85
    while True:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        if buf.tell() <= settings.MAX_IMAGE_BYTES or quality <= 40:
            return buf.getvalue(), "image/jpeg"
        quality -= 15


@router.post("/ocr")
def extract_text(file: UploadFile):
    if file.content_type not in ALLOWED:
        raise HTTPException(status_code=415, detail=f"지원하지 않는 형식입니다: {file.content_type}")
    data = file.file.read()
    if len(data) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="이미지가 너무 큽니다(최대 15MB).")

    data, mime = _compress(data)
    b64 = base64.b64encode(data).decode()

    result = groq_service.chat_json(
        settings.GROQ_VISION_MODEL,
        [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            {"type": "text", "text": OCR_PROMPT},
        ]}],
        max_tokens=OCR_MAX_TOKENS,
        reasoning_effort="none",    # qwen 계열 '생각 과정' 끄기 — 출력 토큰·시간 절약 (미지원이면 빼고 재시도)
        reasoning_format="hidden",  # 그래도 나오는 추론 텍스트는 숨김 (미지원이면 빼고 재시도)
    )
    menus = [{"name": m["name"], "price": m.get("price"), "note": m.get("note") or None}
             for m in result.get("menus", []) if isinstance(m, dict) and m.get("name")]
    drinks = [m for m in menus if _is_drink(m["name"])]
    skipped_names = {m["name"] for m in drinks}
    menus = [m for m in menus if m["name"] not in skipped_names]  # 음료·주류는 분석 대상에서 제외
    menus = _share_notes(menus)
    return {
        "text": "\n".join(m["name"] for m in menus),  # 기존 프론트 호환 (메뉴명 줄 목록)
        "menus": menus,
        "skipped": [m["name"] for m in drinks],  # 음료·주류 등 분석 제외 항목
        "origin_info": result.get("origin_info", []),
    }
