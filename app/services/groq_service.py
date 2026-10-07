"""Groq 호출 공통 모듈 — 재시도, JSON 파싱, 추론 텍스트 제거."""
import json
import re
import time
from functools import lru_cache

from fastapi import HTTPException
from groq import Groq, APIStatusError, APIConnectionError, RateLimitError

from app.core.config import settings


@lru_cache
def get_client() -> Groq:
    if not settings.GROQ_API_KEY:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY가 설정되지 않았습니다.")
    return Groq(api_key=settings.GROQ_API_KEY)


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _repair_truncated(text: str) -> str | None:
    """출력 상한에 걸려 중간에 끊긴 JSON을 마지막으로 완성된 항목까지 살린다.

    '{"menus": [{"name": "A"}, {"name": "B"}, {"na'  →  '{"menus": [{"name": "A"}, {"name": "B"}]}'
    메뉴가 아주 많은 메뉴판에서 전체 실패 대신 앞부분 메뉴라도 돌려주기 위함.
    """
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
    if start < 0:
        return None
    stack: list[str] = []
    in_str = esc = False
    cut, cut_stack = -1, []
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c in "{[":
            stack.append("}" if c == "{" else "]")
        elif c in "}]":
            if not stack:
                break
            stack.pop()
            if stack and stack[-1] == "]":       # 배열 안의 항목 하나가 완성된 지점
                cut, cut_stack = i + 1, list(stack)
    if cut < 0:
        return None
    return text[start:cut] + "".join(reversed(cut_stack))


def parse_json(text: str):
    text = _THINK_RE.sub("", text or "").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 앞뒤 잡음이 섞였을 때 첫 { 또는 [ 부터 마지막 } 또는 ] 까지 잘라서 재시도
        m = re.search(r"[\{\[].*[\}\]]", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        fixed = _repair_truncated(text)   # 출력이 중간에 끊긴 경우
        if fixed:
            return json.loads(fixed)
        raise


class AIUnavailable(HTTPException):
    """하루 한도 소진 등 기다려도 복구되지 않는 AI 장애. 호출한 쪽은 AI 없이 판정으로 넘어간다."""

    def __init__(self, detail: str):
        super().__init__(status_code=503, detail=detail)


_DAILY_LIMIT_HINTS = ("tokens per day", "requests per day", "(TPD)", "(RPD)")


def _create_dropping_unsupported(client, kwargs: dict, optional: list[str]):
    """모델이 지원하지 않는 옵션(reasoning_effort 등)이 있으면 그 옵션만 빼고 다시 부른다.

    오류 문구에 옵션 이름이 나오면 그것만 빼고, 알 수 없으면 선택 옵션을 모두 뺀다.
    """
    while True:
        try:
            return client.chat.completions.create(**kwargs)
        except APIStatusError as e:
            present = [k for k in optional if k in kwargs]
            if e.status_code != 400 or not present:
                raise
            named = [k for k in present if k in str(e)]
            for k in (named or present):
                kwargs.pop(k, None)


def chat_json(model: str, messages: list[dict], max_tokens: int = 3000, retries: int = 4, **extra) -> dict:
    """JSON object 모드로 호출하고 dict를 반환. 429(분당 한도)/5xx/파싱 실패 시 대기 후 재시도."""
    client = get_client()
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            kwargs = dict(model=model, messages=messages, max_tokens=max_tokens, temperature=0.1,
                          response_format={"type": "json_object"}, **extra)
            resp = _create_dropping_unsupported(client, kwargs, list(extra))
            return parse_json(resp.choices[0].message.content or "")
        except RateLimitError as e:  # 분당 토큰·요청 한도 → 헤더가 알려주는 시간만큼 대기
            if "Request too large" in str(e):
                # 요청 하나가 분당 한도보다 크다 → 기다려도 같은 결과. 바로 실패시킨다(10/05 평가에서 77초 낭비)
                raise HTTPException(status_code=502, detail=f"AI 요청이 한도보다 큽니다: {e}")
            if any(h in str(e) for h in _DAILY_LIMIT_HINTS):
                # 하루 한도는 몇 분 기다려도 안 풀린다. 재시도로 시간을 끌지 않는다.
                raise AIUnavailable(f"AI 하루 사용 한도 소진: {e}")
            last_err = e
            wait = 0
            try:
                h = getattr(e, "response", None) and e.response.headers or {}
                wait = float(h.get("retry-after") or h.get("x-ratelimit-reset-tokens", "0").rstrip("s") or 0)
            except Exception:
                wait = 0
            time.sleep(min(max(wait, 5 * (attempt + 1)), 60))
            continue
        except APIConnectionError as e:
            last_err = e
        except APIStatusError as e:
            if e.status_code < 500:
                raise HTTPException(status_code=502, detail=f"Groq 요청 오류: {e.message}")
            last_err = e
        except (json.JSONDecodeError, ValueError) as e:
            last_err = e
        time.sleep(1.5 * (attempt + 1))
    raise HTTPException(status_code=502, detail=f"AI 응답 처리 실패({type(last_err).__name__}): {last_err}")
