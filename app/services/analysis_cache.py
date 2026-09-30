"""메뉴 성분 분석 결과 캐시.

성분은 **프로필과 무관하다.** '돼지국밥에 돼지고기가 들어간다'는 사실은
할랄 사용자가 보든 비건 사용자가 보든 같다. 프로필에 따라 달라지는 것은
그 성분을 어떻게 판정하느냐(규칙 엔진)뿐이다.

그래서 성분 분석 결과만 캐시해두면:
  - 같은 식당을 다른 관광객이 볼 때      → LLM 호출 0번
  - 같은 메뉴판을 여러 프로필로 검증할 때 → 두 번째부터 LLM 호출 0번
  - 부산에서 흔한 메뉴(돼지국밥·밀면 등)  → 쓸수록 빨라짐

캐시는 실패해도 분석을 막지 않는다. 읽기·쓰기 모두 예외를 삼킨다.
"""
import copy
import json
import re
import threading
import unicodedata
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "data" / "analysis_cache.json"
MAX_ENTRIES = 5000

# 분석 로직(태그 규칙·프롬프트)이 바뀌면 이 값을 올린다. 옛 캐시는 자동으로 버려진다.
# 알레르기 판정이라 낡은 결과를 계속 쓰는 것이 더 위험하다.
VERSION = 1

_lock = threading.Lock()
_cache: dict[str, dict] | None = None
_dirty = False


def _norm(text: str | None) -> str:
    """OCR은 같은 메뉴판을 읽어도 공백·전각문자·괄호를 매번 조금씩 다르게 돌려준다.
    그 차이 때문에 시연 전날 채운 캐시가 당일에 빗나가지 않도록 정규화한다."""
    t = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"[\s()\[\]{}·,，、/]+", "", t)


def _key(menu: str, note: str | None, lang: str) -> str:
    return f"{lang}\u0000{_norm(menu)}\u0000{_norm(note)}"


def _load() -> dict:
    global _cache
    if _cache is None:
        try:
            raw = json.loads(PATH.read_text(encoding="utf-8")) if PATH.exists() else {}
            _cache = raw.get("entries", {}) if raw.get("version") == VERSION else {}
        except Exception:
            _cache = {}
    return _cache


def get(menu: str, note: str | None, lang: str) -> dict | None:
    with _lock:
        hit = _load().get(_key(menu, note, lang))
        return copy.deepcopy(hit) if hit is not None else None  # 꺼내 쓴 쪽이 수정해도 캐시는 그대로


def put(menu: str, note: str | None, lang: str, result: dict) -> None:
    """LLM이 돌려준 메뉴 하나치 결과를 저장한다 (위험도는 저장하지 않는다)."""
    if not result or not result.get("ingredients"):
        return  # 빈 결과를 캐시하면 오류가 굳어버린다
    global _dirty
    with _lock:
        c = _load()
        if len(c) >= MAX_ENTRIES:
            for k in list(c)[: MAX_ENTRIES // 10]:
                c.pop(k, None)
        c[_key(menu, note, lang)] = {
            "menu": result.get("menu"),
            "menu_translated": result.get("menu_translated"),
            "description_translated": result.get("description_translated"),
            "ingredients": result.get("ingredients"),
            "custom_allergen_hits": result.get("custom_allergen_hits") or [],
        }
        _dirty = True


def flush() -> None:
    global _dirty
    with _lock:
        if not _dirty or _cache is None:
            return
        try:
            PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = PATH.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"version": VERSION, "entries": _cache}, ensure_ascii=False), encoding="utf-8")
            tmp.replace(PATH)
            _dirty = False
        except Exception:
            pass  # 캐시 저장 실패가 분석을 막으면 안 된다


def stats() -> dict:
    with _lock:
        return {"entries": len(_load()), "path": str(PATH)}


def clear() -> None:
    global _cache, _dirty
    with _lock:
        _cache = {}
        _dirty = True
