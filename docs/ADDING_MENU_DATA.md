# 메뉴 데이터 추가 가이드

새로운 메뉴(특히 메뉴젠 공공데이터에 없는 부산 향토음식)를 시스템에 등록하는 방법입니다.

## 먼저 확인할 것 — 이 메뉴가 정말 필요한가?

`app/services/menu_knowledge.py`의 `build_known_ingredients()`는 아래 순서로 데이터를 찾습니다.

1. **메뉴젠 공공데이터** (`app/data/menuzen_menus.json`) — 3,250개 음식 커버, 최우선
2. **자체 메뉴 DB** (`menu_base.json` 또는 이관 후 `menu_items` 테이블) — 메뉴젠에 없는 메뉴 보완
3. **AI 추론** — 둘 다 없을 때

즉, 추가하려는 메뉴가 메뉴젠에 이미 있는지부터 확인해야 헛수고를 피할 수 있습니다.

```bash
python -c "
from app.services.menuzen_knowledge import find_family, load_dishes
exact, fam = find_family('밀면', load_dishes())
print('정확 일치:', [d['name'] for d in exact])
print('계열:', [d['name'] for d in fam])
"
```

결과가 비어있다면(`계열: []`) 메뉴젠에 없는 메뉴이므로, 자체 DB에 추가해야 합니다.

## 항목 구조

`menu_base.json`(또는 `menu_items` 테이블)의 메뉴 하나는 이런 구조입니다.

```json
"밀면": {
  "aliases": ["부산밀면", "물밀면"],
  "category": "면",
  "required": [
    {"name": "메밀면", "tags": ["buckwheat"]},
    {"name": "육수", "tags": []}
  ],
  "hidden": [
    {"name": "다진 마늘", "tags": []},
    {"name": "참깨", "tags": ["sesame"]}
  ],
  "variants": [
    {
      "name": "비빔밀면",
      "keywords": ["비빔"],
      "ingredients": [
        {"name": "고추장 양념", "tags": []}
      ]
    }
  ]
}
```

| 필드 | 의미 | 판정 결과 |
|---|---|---|
| `aliases` | 메뉴판에 다르게 표기될 수 있는 이름 (예: "부산밀면", "물밀면") | `match_menu()`가 이 이름들로도 검색되게 함 |
| `category` | 분류 태그 (자유 텍스트, 예: "면", "국밥", "전") | 참고용, 판정에 영향 없음 |
| `required` | **거의 모든 가게가 쓰는 필수 재료** | 항상 `confirmed` → 문제 있으면 즉시 WARNING |
| `hidden` | 가게마다 있을 수도 없을 수도 있는 숨은 재료(육수 베이스, 조미료 등) | 항상 `possible` → CAUTION + 직원 질문 |
| `variants` | 메뉴명 키워드로 구분되는 변형(예: "비빔밀면" vs 그냥 "밀면") | 키워드 일치 시 `confirmed`, 안 하면 `possible` |

## 태그는 정해진 것만 사용

`tags`에 아무 문자열이나 쓰면 안 됩니다. `app/services/taxonomy.py`의 `TAGS` 딕셔너리에 있는 키만 유효합니다.

```bash
python -c "from app.services.taxonomy import TAGS; print(list(TAGS.keys()))"
```

```
['pork', 'beef', 'chicken', 'other_meat', 'fish', 'mackerel', 'shrimp', 'crab', 'squid',
 'mollusk', 'shellfish', 'egg', 'milk', 'wheat', 'buckwheat', 'soy', 'peanut', 'walnut',
 'pine_nut', 'sesame', 'peach', 'tomato', 'sulfite', 'alcohol', 'animal_gelatin']
```

재료에 태그를 붙일 게 없으면(예: "밥", "물") `"tags": []`로 비워두면 됩니다.

## 경로 A — `menu_items` 이관 전 (지금은 이 경로)

`app/data/menu_base.json`을 직접 편집합니다.

```bash
python -m json.tool app/data/menu_base.json > /dev/null  # JSON 문법 오류 확인
```

문법 오류가 없으면 서버를 재시작해서(`@lru_cache`가 걸려 있어 재시작해야 반영됨) 바로 확인합니다.

```bash
uvicorn app.main:app --reload
curl -X POST http://localhost:8000/analyze -H "Content-Type: application/json" \
  -d '{"menus":[{"name":"밀면"}]}'
```

`data_source: "menu_base"`, `matched_menu_db: true`로 나오고 `ingredients`가 의도한 대로 채워지면 성공입니다.

## 경로 B — `menu_items` 이관 후

이관이 끝나면 `menu_base.json`을 직접 고쳐도 앱에는 반영되지 않습니다(`load_menu_base()`가 DB를 우선 조회하기 때문). 이 시점부터는 **`menu_base.json`에 새 메뉴를 추가한 뒤, 이관 스크립트를 다시 돌려서 DB에 반영**합니다.

```bash
# 1. menu_base.json에 새 메뉴 추가 (경로 A와 동일한 형식)
# 2. 변환 결과 먼저 확인
python -m scripts.migrate_menu_items --dry-run
# 3. 문제 없으면 실제 반영 (SUPABASE_SECRET_KEY 필요)
python -m scripts.migrate_menu_items --yes
```

`upsert(on_conflict="name")` 방식이라, 기존 메뉴를 수정한 경우도 같은 이름으로 다시 실행하면 덮어써집니다. 새 메뉴 하나만 추가했다고 해서 전체 메뉴가 중복 생성되지 않습니다.

## 체크리스트 (PR 올리기 전)

- [ ] 메뉴젠에 이미 있는 메뉴인지 확인했다 (`find_family()`로 검색)
- [ ] `tags`에 `taxonomy.py`의 `TAGS` 키만 사용했다
- [ ] JSON 문법 오류가 없다 (`python -m json.tool`)
- [ ] `/analyze` 호출로 실제 판정 결과를 확인했다
- [ ] (이관 후라면) `--dry-run`으로 먼저 확인하고 `--yes`로 반영했다
- [ ] `aliases`에 메뉴판에서 흔히 쓰이는 표기(줄임말, 오타성 표기 포함)를 넣었다
