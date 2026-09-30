"""실제 식당 메뉴판 사진으로 서비스 효용성을 측정한다.

사용법 (서버를 먼저 띄운 상태에서):
    python -m scripts.evaluate_menus --dir photos            # 전체 측정
    python -m scripts.evaluate_menus --dir photos --limit 5  # 일부만 먼저 확인

결과 (eval_result/ 폴더):
    menus.csv    메뉴별 판정 결과 + 수동 채점란(정답 여부를 사람이 채움)
    photos.csv   사진별 OCR 결과 + 소요 시간
    summary.md   자동 집계 지표
    raw.json     원본 응답 (재검토용)
"""
import argparse
import csv
import json
import time
from datetime import datetime
from pathlib import Path

import httpx

# 측정용 프로필 3종 — 대표 식단 제약
PROFILES = {
    "shrimp_allergy": {"allergies": {"새우": "심각"}, "preferred_language": "en"},
    "halal": {"religious_diet": "halal", "preferred_language": "en"},
    "vegan": {"vegetarian_type": "vegan", "preferred_language": "en"},
}
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".webp": "image/webp", ".heic": "image/heic", ".heif": "image/heif"}


def _why(e: Exception) -> str:
    """서버가 돌려준 detail 메시지까지 보여준다."""
    r = getattr(e, "response", None)
    if r is not None:
        try:
            return f"{r.status_code} {r.json().get('detail', r.text)[:300]}"
        except Exception:
            return f"{r.status_code} {r.text[:300]}"
    return str(e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="메뉴판 사진이 들어있는 폴더")
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--out", default="eval_result")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-menus", type=int, default=0, help="사진당 분석할 메뉴 수 상한. 0=제한 없음(기본). 빨리 확인만 할 때 10 정도로 지정")
    ap.add_argument("--profiles", default="", help="쉼표로 구분 (shrimp_allergy,halal,vegan) — 지정하면 그 프로필만 측정")
    args = ap.parse_args()

    global PROFILES
    if args.profiles:
        want = [x.strip() for x in args.profiles.split(",") if x.strip()]
        PROFILES = {k: v for k, v in PROFILES.items() if k in want} or PROFILES
    photos = sorted(p for p in Path(args.dir).iterdir() if p.suffix.lower() in IMG_EXT)
    if args.limit:
        photos = photos[:args.limit]
    if not photos:
        raise SystemExit(f"{args.dir} 에 이미지가 없습니다.")
    out = Path(args.out)
    out.mkdir(exist_ok=True)

    raw, menu_rows, photo_rows = [], [], []
    with httpx.Client(timeout=1800) as c:  # 분당 토큰 한도 대기 포함, 넉넉히
        for i, ph in enumerate(photos, 1):
            print(f"[{i}/{len(photos)}] {ph.name}")
            t0 = time.time()
            try:
                r = c.post(f"{args.api}/ocr", files={"file": (ph.name, ph.read_bytes(), MIME.get(ph.suffix.lower(), "image/jpeg"))})
                r.raise_for_status()
                ocr = r.json()
            except Exception as e:
                print(f"   OCR 실패: {_why(e)}")
                photo_rows.append({"사진": ph.name, "OCR상태": f"실패({e})", "추출메뉴수": 0, "OCR초": round(time.time() - t0, 1)})
                continue
            ocr_sec = round(time.time() - t0, 1)
            menus = ocr.get("menus", [])
            if args.max_menus and len(menus) > args.max_menus:
                print(f"   메뉴 {len(menus)}개 중 상위 {args.max_menus}개만 분석")
                menus = menus[:args.max_menus]
            photo_rows.append({"사진": ph.name, "OCR상태": "성공", "추출메뉴수": len(menus),
                               "제외(음료등)": len(ocr.get("skipped", [])),
                               "OCR초": ocr_sec, "추출메뉴": " / ".join(m["name"] for m in menus),
                               "원산지표시": " / ".join(ocr.get("origin_info", []))})

            for pname, prof in PROFILES.items():
                t1 = time.time()
                try:
                    a = c.post(f"{args.api}/analyze", json={"menus": menus, "profile": prof})
                    a.raise_for_status()
                    res = a.json()["results"]
                except Exception as e:
                    print(f"   분석 실패({pname}): {_why(e)}")
                    continue
                sec = round(time.time() - t1, 1)
                raw.append({"photo": ph.name, "profile": pname, "ocr": ocr, "analyze": res})
                for item in res:
                    risk = item["risk"]
                    menu_rows.append({
                        "사진": ph.name, "프로필": pname, "메뉴": item["menu"],
                        "데이터출처": item.get("data_source", "ai"),
                        "비교레시피수": len(item.get("family", [])),
                        "위험도": risk["level"],
                        "확정사유": " / ".join(f'{x["ingredient"]}({x["label"]})' for x in risk["confirmed_reasons"]),
                        "가능사유": " / ".join(f'{x["ingredient"]}({x["label"]})' for x in risk["possible_reasons"]),
                        "직원질문수": len(risk["staff_questions"]),
                        "직원질문": " / ".join(q["ko"] for q in risk["staff_questions"]),
                        "비율출처": "menuzen" if any(x.get("ratio_source") == "menuzen" for x in item["ingredients"]) else "ai추정",
                        "분석초": sec,
                        "채점_메뉴명정확": "", "채점_판정적절": "", "채점_비고": "",
                    })

    _write_csv(out / "photos.csv", photo_rows)
    _write_csv(out / "menus.csv", menu_rows)
    (out / "raw.json").write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    summary(out, photo_rows, menu_rows)
    print(f"\n완료 → {out}/summary.md  (menus.csv의 '채점_' 열을 채운 뒤 다시 집계하면 정확도까지 나옵니다)")


def _write_csv(path, rows):
    if not rows:
        return
    keys = list({k: 1 for r in rows for k in r})
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def summary(out: Path, photos: list[dict], menus: list[dict]):
    ok = [p for p in photos if p["OCR상태"] == "성공"]
    n_menu = len(menus)
    per_profile = len(PROFILES)
    uniq = n_menu // per_profile if per_profile else 0
    src = {k: sum(1 for m in menus if m["데이터출처"] == k) for k in ("menuzen", "menu_base", "ai")}
    lvl = {k: sum(1 for m in menus if m["위험도"] == k) for k in ("WARNING", "CAUTION", "SAFE")}
    ratio_db = sum(1 for m in menus if m["비율출처"] == "menuzen")
    q = [m["직원질문수"] for m in menus]
    ocr_sec = [p["OCR초"] for p in ok]
    an_sec = [m["분석초"] for m in menus]
    pct = lambda a, b: f"{a/b*100:.1f}%" if b else "-"
    avg = lambda xs: f"{sum(xs)/len(xs):.1f}" if xs else "-"

    md = f"""# 메뉴판 사진 기반 효용성 검증 결과
측정일: {datetime.now():%Y-%m-%d %H:%M} · 사진 {len(photos)}장 · 프로필 {per_profile}종(새우 알레르기 / 할랄 / 비건)

## 1. 처리 성공률
| 항목 | 값 |
|---|---|
| OCR 성공 사진 | {len(ok)} / {len(photos)} ({pct(len(ok), len(photos))}) |
| 추출된 메뉴 (사진당 평균) | {sum(p['추출메뉴수'] for p in ok)}개 ({avg([p['추출메뉴수'] for p in ok])}개) |
| 분석 완료 메뉴 (프로필 1종 기준) | {uniq}개 |

## 2. 판정 근거 확보율  ← 효용성의 핵심
| 데이터 출처 | 건수 | 비율 |
|---|---|---|
| 메뉴젠 공공데이터 | {src['menuzen']} | {pct(src['menuzen'], n_menu)} |
| 자체 메뉴 DB | {src['menu_base']} | {pct(src['menu_base'], n_menu)} |
| AI 추론만 사용 | {src['ai']} | {pct(src['ai'], n_menu)} |
| **실측 중량 기반 성분 비율 제공** | {ratio_db} | {pct(ratio_db, n_menu)} |

## 3. 위험도 분포 (프로필 3종 합산 {n_menu}건)
| 판정 | 건수 | 비율 |
|---|---|---|
| WARNING (먹으면 안 됨) | {lvl['WARNING']} | {pct(lvl['WARNING'], n_menu)} |
| CAUTION (직원 확인 필요) | {lvl['CAUTION']} | {pct(lvl['CAUTION'], n_menu)} |
| SAFE | {lvl['SAFE']} | {pct(lvl['SAFE'], n_menu)} |

## 4. 직원 확인 부담
| 항목 | 값 |
|---|---|
| 메뉴당 평균 질문 수 | {avg(q)}개 |
| 질문이 필요 없는 메뉴 | {sum(1 for x in q if x == 0)} / {n_menu} ({pct(sum(1 for x in q if x == 0), n_menu)}) |
| 질문 3개 이상 (부담 큼) | {sum(1 for x in q if x >= 3)} ({pct(sum(1 for x in q if x >= 3), n_menu)}) |

## 5. 응답 속도
| 단계 | 평균 | 최대 |
|---|---|---|
| OCR | {avg(ocr_sec)}초 | {max(ocr_sec) if ocr_sec else '-'}초 |
| 분석 (메뉴판 1장 전체) | {avg(an_sec)}초 | {max(an_sec) if an_sec else '-'}초 |

## 6. 수동 채점 (menus.csv)
아래 두 열을 팀원이 채운 뒤 정확도를 산출합니다.
- `채점_메뉴명정확` : 사진의 메뉴명을 정확히 읽었는가 (O/X)
- `채점_판정적절` : 해당 프로필 기준 위험도와 질문이 타당한가 (O/X)

> 계획서 목표치: OCR 메뉴 인식률 95% · 알레르기 필터 정확도 100%
"""
    (out / "summary.md").write_text(md, encoding="utf-8")


if __name__ == "__main__":
    main()
