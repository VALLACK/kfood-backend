"""시연 전날, 시연할 메뉴판의 성분 분석 결과를 미리 캐시에 채워둔다.

사용법 (서버를 먼저 띄운 상태에서):
    python -m scripts.warm_cache --dir photos\\demo
    python -m scripts.warm_cache --dir photos\\demo --lang ko   # 시연 프로필 언어가 한국어면

왜 필요한가:
    Groq 무료 등급은 하루 토큰 한도가 있어서, 발표 당일 리허설로 한도를 다 쓰면
    정작 시연 때 분석이 멈춘다. 전날 한 번 돌려두면 당일에는 성분 분석을
    캐시에서 꺼내므로 Groq 호출이 없고 결과도 즉시 나온다.

주의:
    - 캐시는 서버가 도는 컴퓨터의 app/data/analysis_cache.json 에 저장된다.
      시연도 **같은 노트북의 로컬 서버**로 해야 효과가 있다.
      (Render 무료 서버는 재시작하면 파일이 지워진다)
    - 메뉴판 사진 읽기(OCR)는 캐시되지 않으므로 시연 때 인터넷은 필요하다.
    - 캐시 키에 언어가 들어간다. 시연 프로필의 preferred_language와 --lang을 맞출 것.
"""
import argparse
import time
from pathlib import Path

import httpx

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".webp": "image/webp", ".heic": "image/heic", ".heif": "image/heif"}


def warm(client, photos: list[Path], lang: str = "en") -> list[dict]:
    """사진마다 OCR → 분석을 한 번 돌려 캐시를 채우고, 두 번째 호출 속도로 확인한다.

    client는 httpx.Client 또는 FastAPI TestClient (post 메서드만 쓴다).
    """
    report = []
    for ph in photos:
        row = {"photo": ph.name, "menus": 0, "first_sec": None, "second_sec": None, "error": None}
        try:
            r = client.post("/ocr", files={"file": (ph.name, ph.read_bytes(), MIME.get(ph.suffix.lower(), "image/jpeg"))})
            r.raise_for_status()
            menus = r.json().get("menus", [])
            row["menus"] = len(menus)
            if not menus:
                row["error"] = "메뉴를 못 읽음"
                report.append(row)
                continue

            body = {"menus": menus, "profile": {"preferred_language": lang}}
            t0 = time.time()
            client.post("/analyze", json=body).raise_for_status()   # 이때 캐시가 채워진다
            row["first_sec"] = round(time.time() - t0, 1)

            t1 = time.time()
            client.post("/analyze", json=body).raise_for_status()   # 캐시에서 나오는지 확인
            row["second_sec"] = round(time.time() - t1, 1)
        except Exception as e:
            r = getattr(e, "response", None)
            row["error"] = f"{r.status_code} {r.text[:200]}" if r is not None else str(e)
        report.append(row)
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="시연할 메뉴판 사진 폴더")
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--lang", default="en", choices=["en", "ko", "zh", "ja"],
                    help="시연 프로필의 언어 (캐시 키에 포함됨)")
    args = ap.parse_args()

    photos = sorted(p for p in Path(args.dir).iterdir() if p.suffix.lower() in IMG_EXT)
    if not photos:
        raise SystemExit(f"{args.dir} 에 이미지가 없습니다.")

    with httpx.Client(base_url=args.api, timeout=1800) as c:
        report = warm(c, photos, args.lang)

    print()
    for row in report:
        if row["error"]:
            print(f"  ❌ {row['photo']}: {row['error']}")
        else:
            print(f"  ✅ {row['photo']}: 메뉴 {row['menus']}개 — 처음 {row['first_sec']}초 → 캐시 {row['second_sec']}초")
    ok = sum(1 for r in report if not r["error"])
    print(f"\n{ok}/{len(report)}장 준비 완료. 시연은 이 서버(같은 노트북)로 하세요.")


if __name__ == "__main__":
    main()
