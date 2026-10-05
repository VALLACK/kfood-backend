"""공공데이터·자체 DB에 없는 메뉴를 기록한다.

쓸수록 커버리지가 올라가는 구조:
  분석 중 미매칭 발생 → app/data/unmatched_menus.json 에 빈도 누적
  → 팀이 자주 나오는 메뉴부터 검수 → scripts/add_menu.py 로 메뉴 DB에 추가
AI 추론 결과를 그대로 저장하지 않는다(오류 데이터 축적 방지). 사람이 검수한 것만 DB에 들어간다.
"""
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "data" / "unmatched_menus.json"
_lock = threading.Lock()
MAX_ENTRIES = 2000


def _load() -> dict:
    if not PATH.exists():
        return {}
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def record(name: str, source_menu_board: str | None = None) -> None:
    name = (name or "").strip()
    if not name or len(name) > 40:
        return
    try:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with _lock:
            data = _load()
            item = data.get(name) or {"count": 0, "first_seen": now, "status": "대기"}
            item["count"] += 1
            item["last_seen"] = now
            if source_menu_board:
                item["last_source"] = source_menu_board
            data[name] = item
            if len(data) > MAX_ENTRIES:  # 오래되고 빈도 낮은 항목부터 정리
                data = dict(sorted(data.items(), key=lambda kv: (-kv[1]["count"], kv[1]["last_seen"]))[:MAX_ENTRIES])
            PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        return  # 읽기 전용 환경(Vercel 등)에서 기록 실패가 분석을 막으면 안 된다


def top(limit: int = 50, status: str | None = None) -> list[dict]:
    data = _load()
    rows = [{"menu": k, **v} for k, v in data.items()]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    return sorted(rows, key=lambda r: -r["count"])[:limit]


def mark_added(name: str) -> None:
    with _lock:
        data = _load()
        if name in data:
            data[name]["status"] = "DB 추가됨"
            PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def stats() -> dict:
    data = _load()
    return {
        "미매칭 메뉴 종류": len(data),
        "누적 발생 횟수": sum(v["count"] for v in data.values()),
        "검수 대기": sum(1 for v in data.values() if v.get("status") == "대기"),
        "DB 추가 완료": sum(1 for v in data.values() if v.get("status") == "DB 추가됨"),
    }
