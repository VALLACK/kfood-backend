# kfood-backend

외국인을 위한 부산 음식 성분 필터링 앱 백엔드 (FastAPI + Supabase + Groq)

## 실행 방법

**Windows: `run.bat` 더블클릭** (가상환경·설치·.env 생성·서버 실행 자동) / 맥: `./run.sh`

수동 실행:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # 값 채워넣기 (팀 채널에서 공유받은 값 사용)
uvicorn app.main:app --reload
```

실행 후 `http://localhost:8000/health` 접속 시 `{"status":"ok"}`가 나오면 정상입니다.

API 문서(Swagger)는 `http://localhost:8000/docs`에서 확인할 수 있습니다.

## 환경 변수

`.env.example` 참고. 아래 값들이 필요합니다.

- `SUPABASE_URL`, `SUPABASE_KEY`: Supabase 프로젝트 설정에서 확인 (팀 채널 공유). 일반 서버 실행·로그인 사용자 기능에 사용
- `SUPABASE_SECRET_KEY`: RLS를 우회하는 관리자 권한 키(`sb_secret_...` 형식). `scripts/` 아래 관리자용 스크립트(예: 메뉴 DB 이관)에서만 사용하며, 일반 서버 실행에는 필요 없음. **절대 커밋 금지**, 값은 Supabase 대시보드(Settings > API Keys)에서 확인하거나 팀 채널로 전달받아 로컬 `.env`에 직접 추가
- `GROQ_API_KEY`: Groq 콘솔([console.groq.com](https://console.groq.com))에서 발급, OCR·AI 분석(`/ocr`, `/analyze`)에 필요

## 폴더 구조

```
app/
├── main.py          # FastAPI 진입점, 라우터 등록, CORS 설정
├── core/
│   ├── auth.py           # 로그인 토큰 검증 (AuthContext, require_auth, optional_auth)
│   └── config.py          # 환경 설정 통합
├── db/
│   └── supabase_client.py   # Supabase 클라이언트 초기화
├── routers/
│   ├── ocr.py           # POST /ocr - 메뉴판 이미지 → 메뉴 목록 (Groq Vision)
│   ├── analyze.py       # POST /analyze - 재료·비율 추론 + 규칙 기반 위험도
│   ├── qna.py           # POST /qna, /qna/confirm - 질의응답, 직원 답변 반영
│   ├── stt.py           # POST /stt - 음성 → 텍스트 (Groq Whisper)
│   └── profile_card.py  # GET /profile/card - 종업원에게 보여줄 식단 카드
├── services/
│   ├── menu_knowledge.py      # 메뉴 기준 DB 매칭 (필수/숨은/변형 재료). menu_items(DB) 우선, menu_base.json 폴백
│   ├── menuzen.py              # 농촌진흥청 메뉴젠 공공데이터 XML 파싱·태그 정규화
│   ├── menuzen_knowledge.py    # 메뉴젠 데이터로 계열 레시피 비교, 실제 중량 기반 성분 비율 (1순위 데이터 소스)
│   ├── dietary_rules.py        # 위험도 규칙 + 직원 질문 생성
│   ├── ingredient_lexicon.py   # 재료 사전(용어집), 숨은 재료 보정
│   ├── taxonomy.py             # 성분 태그·알레르기 매핑·다국어 라벨
│   ├── profile_service.py      # 로그인/비로그인 프로필 로딩
│   ├── analysis_service.py     # /analyze 파이프라인 (DB 매칭 → LLM 추론 → 규칙 판정)
│   └── groq_service.py         # 재시도·JSON 파싱
├── data/
│   ├── menu_base.json      # 부산/한식 메뉴 기준 데이터 (2순위 소스, 팀 검수 필요 — menu_items 테이블 이관 준비 중)
│   └── menuzen_menus.json  # 메뉴젠 공공데이터 (1순위 소스, scripts/fetch_menuzen.py로 생성)
└── models/schemas.py

scripts/
├── fetch_menuzen.py         # 메뉴젠 API 전체 수집·정규화 → app/data/menuzen_menus.json
├── add_menu.py              # 미매칭으로 기록된 메뉴를 menu_base.json에 추가
├── evaluate_menus.py        # 메뉴판 사진으로 실사용 검증 → eval_result/
├── warm_cache.py            # 시연 전날 시연 메뉴판을 미리 분석해 캐시 채우기
└── migrate_menu_items.py    # (진행 중) menu_base.json → Supabase menu_items 테이블 이관. SUPABASE_SECRET_KEY 필요, --dry-run으로 먼저 확인

supabase/
└── migrations/      # DB 스키마 및 RLS 정책 SQL 스크립트
```

## DB 스키마

- **profiles**: 사용자 프로필 (allergies, religious_diet, vegetarian_type, preferred_language)
- **scan_logs**: 메뉴판 스캔 기록 (raw_ocr_text, analysis_result)
- **qna_logs**: 스캔 결과에 대한 질의응답 기록
- **menu_items** (`08_create_menu_items.sql`, 진행 중): 메뉴 기준 데이터(필수/숨은/변형 재료)를 `menu_base.json` 대신 DB로 관리하기 위한 테이블. 현재는 스키마만 준비된 상태이며, `menu_base.json` 팀 검수가 끝난 뒤 `scripts/migrate_menu_items.py --yes`로 데이터를 이관할 예정. 읽기는 누구나 가능(공개 참조 데이터), 쓰기는 `SUPABASE_SECRET_KEY`로만 가능

네 테이블 모두 RLS(Row Level Security)가 적용되어 있어, `profiles`/`scan_logs`/`qna_logs`는 로그인한 본인의 데이터만 조회/수정 가능하고, `menu_items`는 읽기 전용으로 누구나 접근 가능합니다.

신규 사용자가 구글 로그인으로 가입하면 `profiles` 테이블에 자동으로 빈 프로필이 생성됩니다 (DB 트리거).

## Supabase / Google Cloud Console 사전 등록 필수

로컬에서 구글 로그인 및 인증 기반 기능을 테스트하려면 아래 등록이 선행되어야 합니다. 등록이 안 되어 있으면 로그인 자체가 거부되거나 리다이렉트가 실패합니다.

- **Supabase 프로젝트 팀원 초대**: Project Settings > Team에서 초대받아야 Table Editor, SQL Editor 등에 접근 가능
- **Google Cloud Console 테스트 사용자 등록**: OAuth consent screen이 테스트 모드이므로, Audience 탭에 본인 구글 계정 이메일이 테스트 사용자로 등록되어 있어야 로그인 가능 (미등록 계정은 "확인되지 않은 앱" 에러로 거부됨)
- **Redirect URL 등록 확인**: Supabase Authentication > URL Configuration의 Site URL / Redirect URLs에 로컬 개발 주소(`http://localhost:5173/**`)가 등록되어 있어야 로그인 후 리다이렉트가 정상 작동
- **Google OAuth Client의 Authorized redirect URIs**: Google Cloud Console의 Client 설정에 Supabase 콜백 URL(`https://<project-ref>.supabase.co/auth/v1/callback`)이 등록되어 있어야 함

## 의존성 버전 고정 계획

- 현재 `requirements.txt`는 `>=` 하한만 지정한다. 개발 중에는 최신 패치를 따라가기 위함이다.
- 정식 배포 직전, 최종 테스트(`pytest -q`와 시연 시나리오)를 마친 `.venv`에서 아래를 실행해 버전을 고정하고 커밋한다.
  ```bash
  pip freeze | grep -iE "^(fastapi|uvicorn|python-dotenv|python-multipart|pydantic|groq|supabase|httpx|pillow)=="
  ```
  `uvicorn`은 `uvicorn[standard]==버전`으로 표기한다.
- 고정 후 새 가상환경에서 `pip install -r requirements.txt && pytest -q`로 재현성을 확인한다.
- 고정 전까지는 배포 빌드마다 최신 버전이 설치된다. 배포 후 빌드나 동작에 이상이 있으면 의존성 버전 변경을 먼저 의심한다.

## 알려진 이슈

~~`app/routers/analyze.py` 필드명 불일치~~ → `feat/analyze-v2`에서 해결 (profiles는 `user_id`로 조회, scan_logs는 `profile_id`·`raw_ocr_text`·`analysis_result`로 저장).
~~`GET /profiles/test`: 인증 없이 `profiles` 전체를 조회하는 디버그용 엔드포인트~~ → `chore/vercel-prep`에서 제거 완료

- 저장소에 `venv/` 폴더(가상환경 바이너리)가 커밋되어 있음 → `git rm -r --cached venv` 필요
- Groq `meta-llama/llama-4-scout-17b-16e-instruct`(2026-07-17), `llama-3.3-70b-versatile`(2026-08-16) 서비스 종료 → 모델명은 `.env`로 관리
- `menu_items` DB 이관 진행 중: `menu_base.json` 팀 검수가 끝나기 전까지 `scripts/migrate_menu_items.py`는 실제 실행(`--yes`)하지 말 것. `app/services/menu_knowledge.py`는 DB에 데이터가 없으면 자동으로 `menu_base.json`을 계속 사용하므로, 코드 자체는 검수 전에 배포해도 안전함

## 테스트

```bash
pip install -r requirements-dev.txt
pytest -q
```

API 상세는 `docs/API.md`, 피드백 반영 내역은 `docs/FEEDBACK_RESPONSE.md` 참고.

## 문서

| 문서 | 내용 |
|---|---|
| `docs/API.md` | API 명세 (요청·응답 형식, 프로필 값 규약) |
| `docs/FRONTEND_GUIDE.md` | **프론트 연동 가이드** — 응답 구조 변경 대응, 로그인 토큰, 직원 확인 기능 |
| `docs/frontend/` | 수정 예시 코드(`ResultPage.example.jsx`), 실제 응답 예시 JSON |
| `docs/EVALUATION.md` | 실사용 검증 결과 (메뉴판 9장·메뉴 136개) |
| `docs/EVALUATION_SCORED.md` | 채점 결과 — 메뉴명 인식률, SAFE 오판 2건과 조치 |
| `docs/EVALUATION_1005.md` | 10/05 재평가 — 메뉴판 12장, 메뉴명 88.8%, 위험 오판 12→2건 |
| `docs/DEMO.md` | 시연 가이드 및 AI 구성 설명 |
| `docs/ADDING_MENU_DATA.md` | 메뉴 데이터 추가 방법 |
| `docs/FEEDBACK_RESPONSE.md` | 피드백 반영 정리 |
