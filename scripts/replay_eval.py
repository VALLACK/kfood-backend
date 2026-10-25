"""평가 결과를 '같은 인식 결과·같은 AI 답변'으로 새 코드에 다시 돌려, 위험 오판이 고쳐졌는지 확인한다.

Groq를 부르지 않는다. 평가 때 저장된 OCR 메뉴와 AI 재료 답변(raw.json)을 그대로 쓰고,
바뀐 규칙(메뉴명 규칙·재료 사전·판정 엔진)만 새로 적용한다.
그래서 메뉴판 사진을 다시 읽어서 생기는 차이(OCR이 매번 조금씩 다름)는 섞이지 않는다.

    python -m scripts.replay_eval          # 저장소에 있는 10/05 평가 원본으로 실행

--scored의 '채점_판정적절'이 '위험'인 줄(먹으면 안 되는데 SAFE)이 지금 코드에서
SAFE가 아니게 됐는지 하나씩 출력한다. EVALUATION_1005.md의 '수정 후 2건'은 이 결과다.
"""
import argparse
import csv
import gzip
import json
import tempfile
from collections import defaultdict
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services import analysis_cache, groq_service
from scripts.evaluate_menus import PROFILES


def _stored_ai_answers(raw: list[dict]) -> dict[str, dict]:
    """메뉴별 AI 답변. AI가 답하지 못한(provisional) 프로필 쪽보다 답한 쪽을 우선한다."""
    ai: dict[str, dict] = {}
    for blk in raw:
        for r in blk.get("analyze") or []:
            if r.get("provisional") and r["menu"] in ai:
                continue
            ai[r["menu"]] = {
                "menu": r["menu"],
                "menu_translated": r.get("menu_translated"),
                "ingredients": [dict(i, source="ai") for i in r.get("ingredients", [])
                                if i.get("source") in (None, "ai", "menu_board")],
            }
    return ai


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="docs/eval_1005_raw.json.gz", help="evaluate_menus 결과 raw.json (.gz 가능)")
    ap.add_argument("--scored", default="docs/eval_1005_scored.csv")
    args = ap.parse_args()

    opener = gzip.open if args.raw.endswith(".gz") else open
    with opener(args.raw, "rt", encoding="utf-8") as f:
        raw = json.load(f)
    ai = _stored_ai_answers(raw)

    def replay_llm(model, messages, **kw):   # 저장된 답변을 돌려주는 가짜 AI
        prompt = json.dumps(messages, ensure_ascii=False)
        return {"results": [ai[n] for n in ai if n in prompt]}

    groq_service.chat_json = replay_llm
    analysis_cache.PATH = Path(tempfile.mkdtemp()) / "cache.json"   # 실제 캐시 오염 방지
    client = TestClient(app)

    now = defaultdict(list)   # (사진, 프로필, 메뉴) → [새 판정, ...] (같은 이름 메뉴가 여러 줄일 수 있음)
    for blk in raw:
        if not blk.get("analyze"):
            continue
        res = client.post("/analyze", json={"menus": blk["ocr"]["menus"],
                                            "profile": PROFILES[blk["profile"]]})
        res.raise_for_status()
        for r in res.json()["results"]:
            now[(blk["photo"], blk["profile"], r["menu"])].append(r["risk"]["level"])

    rows = list(csv.DictReader(open(args.scored, encoding="utf-8-sig")))
    danger = [r for r in rows if r.get("채점_판정적절") == "위험"]
    seen = defaultdict(int)
    left = 0
    for r in danger:
        key = (r["사진"], r["프로필"], r["메뉴"])
        levels = now.get(key) or ["?"]
        level = levels[min(seen[key], len(levels) - 1)]
        seen[key] += 1
        fixed = level not in ("SAFE", "?")
        left += not fixed
        print(f"{'해결' if fixed else '남음'}  {r['프로필']:15s} {r['메뉴']:16s} SAFE → {level}")
    total = len([r for r in rows if r.get("채점_판정적절") != "제외"])
    print(f"\n위험 오판 {len(danger)}건 → {left}건 · 위험 오판 없는 비율 {(total - left) / total:.1%} ({total}건 기준)")


if __name__ == "__main__":
    main()
