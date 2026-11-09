"""메뉴판 사진으로 OCR 메뉴명 인식률을 잰다 — 설정을 바꿔 가며 비교하는 용도.

정답은 10/05 채점표(docs/eval_1005_scored.csv)에서 가져온다.
  - 채점 O인 메뉴명은 그대로 정답
  - 채점 X인데 비고에 실제 이름이 적힌 것(예: "게란말이 | 계란말이")은 비고의 이름이 정답
사진 파일명이 채점표의 '사진' 칸과 같아야 한다 (예: 스크린샷 2026-09-23 193106.png).

사용법 (서버를 먼저 띄운 상태에서, 사진 폴더 지정):
    python -m scripts.compare_ocr --dir eval_photos
    # 서버를 OCR_MAX_SIDE=2048 로 다시 띄운 뒤 한 번 더 → 두 결과의 '인식률'을 비교
    python -m scripts.compare_ocr --dir eval_photos --only 193106,193251,193421   # 작은 글씨 많은 사진만

Groq를 사진 1장당 1번 쓴다(12장 ≈ 12번). 결과는 화면과 eval_result/compare_ocr_<시각>.csv에 남는다.
"""
import argparse
import csv
import re
import time
from datetime import datetime
from pathlib import Path

import httpx

SCORED = Path("docs/eval_1005_scored.csv")
MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


def norm(name: str) -> str:
    return re.sub(r"[\s()·,./]", "", name or "")


def answer_key() -> dict[str, set[str]]:
    """사진 파일명 → 정답 메뉴명 집합."""
    key: dict[str, set[str]] = {}
    for r in csv.DictReader(SCORED.open(encoding="utf-8-sig")):
        names = key.setdefault(r["사진"], set())
        if r["채점_메뉴명정확"] == "O":
            names.add(norm(r["메뉴"]))
        else:
            real = re.match(r'^(?:실제\s*)?"?([가-힣]{2,})"?$', (r["채점_비고"] or "").split("/")[0].strip())
            if real:
                names.add(norm(real.group(1)))
    return key


def ocr(api: str, path: Path) -> tuple[list[str], float]:
    t = time.time()
    with path.open("rb") as f:
        r = httpx.post(f"{api}/ocr", files={"file": (path.name, f, MIME.get(path.suffix.lower(), "image/png"))},
                       timeout=120)
    r.raise_for_status()
    return [m["name"] for m in r.json().get("menus", [])], time.time() - t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="10/05 평가 사진 폴더")
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--only", default="", help="파일명에 들어간 숫자로 일부만 (쉼표 구분)")
    args = ap.parse_args()

    key = answer_key()
    only = [s for s in args.only.split(",") if s]
    photos = [p for p in sorted(Path(args.dir).iterdir())
              if p.name in key and (not only or any(o in p.name for o in only))]
    if not photos:
        raise SystemExit(f"{args.dir}에 채점표와 같은 이름의 사진이 없습니다.")

    out_dir = Path("eval_result"); out_dir.mkdir(exist_ok=True)
    out = out_dir / f"compare_ocr_{datetime.now():%m%d_%H%M}.csv"
    hit = total = extra = 0
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["사진", "정답수", "맞춘수", "인식률", "정답에없는메뉴", "놓친메뉴", "초"])
        for p in photos:
            try:
                names, sec = ocr(args.api, p)
            except Exception as e:  # noqa: BLE001 — 한 장 실패해도 계속
                print(f"{p.name}: 실패 {e}")
                continue
            got = {norm(n) for n in names}
            want = key[p.name]
            ok = want & got
            hit += len(ok); total += len(want); extra += len(got - want)
            rate = len(ok) / len(want) if want else 0
            w.writerow([p.name, len(want), len(ok), f"{rate:.0%}", " / ".join(sorted(got - want)),
                        " / ".join(sorted(want - got)), f"{sec:.1f}"])
            print(f"{p.name}: {len(ok)}/{len(want)} ({rate:.0%})  정답에 없는 메뉴 {len(got - want)}개  {sec:.1f}초")
    print(f"\n전체 인식률 {hit}/{total} = {hit / max(total, 1):.1%}, 정답에 없는 메뉴 {extra}개")
    print(f"저장: {out}")


if __name__ == "__main__":
    main()
