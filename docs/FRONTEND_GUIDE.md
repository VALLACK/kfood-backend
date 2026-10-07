# 프론트엔드 연동 가이드 (백엔드 김현수)

현재 `ScanPage.jsx` / `ResultPage.jsx`가 `/ocr`, `/analyze`를 이미 호출하고 있습니다.
다만 **백엔드 응답 구조가 바뀌어서 결과 화면이 실제 응답을 읽지 못합니다.** 아래 항목을 반영해주세요.

---

## 1. 결과 화면이 깨지는 원인 (가장 급함)

`ResultPage.jsx`가 옛 응답 형식을 읽고 있어서, 실제 분석 시 `item.risk.reasons.length`에서 **TypeError로 화면이 멈춥니다.**

| 지금 화면이 찾는 것 | 실제 응답 | 비고 |
|---|---|---|
| `risk.reasons` | `risk.confirmed_reasons` / `risk.possible_reasons` | 확정 / 가게마다 다름으로 분리됨 |
| `ingredients` (문자열 배열) | 객체 배열 `{name, tags, certainty, ratio_percent, ...}` | `.join()` 불가 |
| `hidden` | 없음 → `ingredients[].certainty === "possible"` | |
| `contains_pork`, `contains_alcohol` | 없음 → `ingredients[].tags`에 `pork`, `alcohol` | |
| — | **`risk.staff_questions`** (신규) | 직원에게 보여줄 한국어 질문 |

**`docs/frontend/ResultPage.example.jsx`** 가 위 구조에 맞춘 수정본입니다. 그대로 교체하시거나 필요한 부분만 참고해주세요.

---

## 2. 프로필이 적용되지 않는 문제

`/analyze` 요청에 `profile_id`를 보내고 계신데, 현재 백엔드에는 그 항목이 없어 **무시됩니다.**
결과가 전부 "프로필 없음" 기준(=거의 SAFE)으로 나옵니다.

```js
// 현재
axios.post(`${API_URL}/analyze`, {
  ocr_text: text,
  profile_id: localStorage.getItem('profile_id'),
});

// 수정 — 로그인 토큰을 헤더로 (비로그인이면 헤더 없이 호출)
const { data: { session } } = await supabase.auth.getSession();
const token = session?.access_token;              // 비로그인이면 session이 null
axios.post(`${API_URL}/analyze`, { menus }, {
  headers: token ? { Authorization: `Bearer ${token}` } : {},
  timeout: 180000,
});
```

`session`은 로그인하지 않았으면 `null`이라 `session.access_token`으로 바로 접근하면 오류가 납니다.
예시 파일의 `authHeader()`가 이 처리를 하고 있으니 그대로 쓰셔도 됩니다.

- 헤더를 붙이면 백엔드가 DB에서 프로필을 불러오고, 분석 기록을 `scan_logs`에 저장합니다 (`scan_log_id` 반환).
- 비로그인 상태로 테스트하려면 body에 `profile`을 직접 넣어도 됩니다.
  `{"menus": [...], "profile": {"allergies": {"새우": "심각"}, "religious_diet": "halal", "preferred_language": "en"}}`
- 응답의 `profile_applied: false`면 프로필이 안 걸린 상태입니다.

---

## 3. `/ocr` 결과는 `menus`를 넘겨주세요

```js
// ScanPage.jsx — 현재
navigate('/result', { state: { ocrText: res.data.text } });

// 수정
navigate('/result', { state: { menus: res.data.menus, ocrText: res.data.text } });
```

`/ocr` 응답:
```json
{
  "text": "짬뽕\n돌게탕",
  "menus": [
    { "name": "짬뽕", "price": "9,000", "note": null },
    { "name": "돌게탕", "price": "40,000", "note": "전복2,가리비2,꽃게,새우2,낙지,조개다수" }
  ],
  "skipped": ["소주", "음료수"],
  "origin_info": ["소고기(국산), 돼지고기(독일산)"]
}
```
`menus`를 넘기면 텍스트 재파싱을 건너뛰어 더 정확하고 빠릅니다. 음료·주류는 `skipped`로 자동 제외됩니다.

**`note`는 꼭 같이 넘겨주세요.** 메뉴판 괄호에 인쇄된 재료 문구입니다.
실제 검증에서 "메뉴판에 새우가 적혀 있는데 SAFE로 나온" 오판이 3건 있었고, 이 값으로 잡아냅니다.
`res.data.menus`를 통째로 넘기면 자동으로 포함되니, 이름만 뽑아서 다시 만들지만 마세요.

---

## 4. API 오류 시 데모 결과를 실제처럼 보여주지 않기 ⚠️

현재 `ResultPage.jsx`는 오류가 나면 `DEMO_RESULTS`(가짜 데이터)를 그대로 화면에 띄웁니다.
알레르기 판정 앱에서는 **사용자가 가짜 결과를 실제 판정으로 오해할 수 있어 위험합니다.**

```js
// 현재 — 오류가 나도 데모 결과가 그대로 보임
} catch (err) {
  setError(...);
  setResults(DEMO_RESULTS);   // ← 제거 필요
}

// 수정 — 오류 안내 + 다시 시도
} catch (err) {
  setError(...);
  setResults([]);
}
```

데모 화면이 필요하면 홈의 "데모 보기" 같은 **별도 진입점**으로 분리하고, 화면 상단에 "예시 화면입니다" 배지를 달아주세요. 첨부한 수정본에는 이미 데모 대체 로직이 빠져 있습니다.

---

## 5. 직원 확인 기능 (우리 핵심 기능, 현재 화면에 없음)

`risk.staff_questions`가 있으면 그 질문을 직원에게 보여주고, 답변을 받아 다시 판정합니다.

```json
"staff_questions": [
  {
    "kind": "contains",              // contains | variant | halal_meat | kosher_meat
    "ingredient": "새우",
    "tag": "shrimp",
    "options": [],                   // kind가 variant면 ["해물짬뽕","고기짬뽕","그 외"]
    "ko": "짬뽕에 새우가 들어가나요?",      // 직원에게 보여줄 문장
    "translated": "Does the Jjamppong contain shrimp?"
  }
]
```

**답변 반영 — `POST /qna/confirm`**
```js
axios.post(`${API_URL}/qna/confirm`, {
  menu_result: item,              // results[i] 통째로
  question: { kind, ingredient, tag, options },
  staff_answer: '예',              // '예' | '아니요' | variant면 옵션명 | 자연어도 가능
  input_type: 'text',
}, { headers: { Authorization: `Bearer ${token}` } });
// → { verdict, summary_translated, result }  ← result로 카드 교체
```

**TTS는 브라우저 내장 기능으로 충분합니다** (별도 API 불필요)
```js
const u = new SpeechSynthesisUtterance(question.ko);
u.lang = 'ko-KR';
window.speechSynthesis.speak(u);
```

음성으로 답변받고 싶으면 `POST /stt` (multipart `file`, form `language=ko`)로 텍스트 변환 후 `staff_answer`에 넣으면 됩니다.

---

## 6. 참고 — 응답 주요 필드

| 필드 | 설명 |
|---|---|
| `risk.level` | `SAFE` / `CAUTION` / `WARNING` |
| `risk.confirmed_reasons[]` | 확정된 위험 사유 `{kind, tag, label, ingredient, severity}` |
| `risk.possible_reasons[]` | 가게에 따라 다를 수 있는 사유 |
| `risk.needs_confirmation` | 직원 확인이 필요한지 |
| `ingredients[].certainty` | `confirmed`(필수) / `possible`(가게마다 다름) / `excluded`(직원이 없다고 확인) |
| `ingredients[].ratio_percent` | 성분 비율 |
| `ingredients[].ratio_source` | `"menuzen"`이면 **공공데이터 실제 중량 기준**, 없으면 AI 추정 |
| `ingredients[].seen_in` | 그 재료가 등장한 유사 레시피 이름 (근거 표시용) |
| `data_source` | `menuzen`(공공데이터) / `menu_base`(자체 DB) / `menu_board`(메뉴판 표기) / `ai`(추론) |
| `provisional` | `true`면 전체 재료를 모르는 상태. 이때는 SAFE가 나오지 않고 최소 CAUTION + 직원 질문 |
| `family[]` | 비교에 사용한 유사 레시피 목록 |
| `profile_applied` | 프로필이 적용됐는지 |

전체 응답 예시는 **`docs/frontend/sample_analyze_response.json`** 참고.
API 명세 전체는 저장소 `docs/API.md`, 서버 실행 후 `http://localhost:8000/docs`에서도 직접 테스트할 수 있습니다.

---

## 참고 — 즉시 판정 (`skip_ai`, 선택)

필수는 아닙니다. 화면을 먼저 빨리 그리고 싶을 때만 쓰세요.

```js
// 1) 1초 안에 위험도만 먼저 (AI 호출 없음, 번역·설명은 비어 있음)
const quick = await axios.post(`${API_URL}/analyze`, { menus, skip_ai: true }, { headers: authHeader() });
setResults(quick.data.results);
// 2) 이어서 전체 분석으로 교체 (번역·성분 비율 채워짐)
const full = await axios.post(`${API_URL}/analyze`, { menus }, { headers: authHeader(), timeout: 180000 });
setResults(full.data.results);
```

즉시 판정에서 `provisional: true`인 메뉴는 재료 정보가 부족한 상태라 🟢가 나오지 않습니다(🟡 직원 확인).

---

## 7. 프로필 저장값 — **이미 맞습니다, 수정 불필요**

`Profile.jsx`의 선택지가 백엔드와 전부 호환됩니다.

| 항목 | 현재 저장값 | 백엔드 인식 |
|---|---|---|
| 알레르기 | `peanuts` `shellfish` `eggs` `dairy` `gluten` `soy` `sesame` `tree_nuts` | 전부 매핑됨 |

> `shellfish`는 **조개류 + 새우 + 게**로 처리합니다. 영어권에서 "shellfish allergy"는 보통 새우·게를 뜻하는데,
> 선택지에 새우가 따로 없어서 새우 알레르기 관광객도 이걸 고르기 때문입니다. 수정할 건 없습니다.
| 종교 식단 | `halal` `kosher` | 매핑됨 (`hindu`도 지원) |
| 채식 | `vegetarian` `vegan` | 매핑됨 (`lacto` `ovo` `pescatarian`도 지원) |

**한 가지만 추가 제안:** `preferred_language`(`ko`/`en`/`zh`/`ja`)를 프로필에 넣어주시면
메뉴 설명·직원 질문 번역이 사용자 언어로 나옵니다. 지금은 기본값 `en`으로 동작합니다.

알레르기 심각도를 구분하고 싶으면 배열 대신 `{"shellfish": "심각", "eggs": "경미"}` 형태로 저장하면
백엔드가 그대로 읽어 카드에 표시합니다. (지금처럼 배열이어도 정상 동작합니다.)
