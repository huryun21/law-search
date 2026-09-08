# 전체 페이지네이션 + 단계적 본문 검증 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 본문 검색 후보가 API 페이지 상한(1페이지=100건) 때문에 통째로 빠지는 회귀(예: "통합심의"에서 도시 및 주거환경정비법 누락)를 없애고, 그러면서도 체감 속도를 지키기 위해 우선순위 후보를 먼저 검증·표시한 뒤 나머지를 화면 전체를 다시 그리지 않고 점진적으로 검증·추가한다.

**Architecture:** `SearchService`가 각 자료원의 `totalCnt`까지 모든 페이지를 받아오도록 확장하고(§1~2 관련 기존 단일 페이지 로직은 그대로 재사용), 검증 직전에 후보를 법령명 키워드 기준 우선순위/나머지로 나눈다(새 순수 함수). 우선순위만 즉시 검증해 기존과 동일한 `SearchResponse`로 반환하고, 나머지는 검증되지 않은 채 `SearchResponse.pending`에 실어 보낸다. `app.py`는 검색 직후 `pending`을 세션 상태 큐에 저장하고, `st.fragment(run_every="2s")`로 감싼 작은 조각이 몇 초마다 큐에서 일부를 꺼내 검증해 결과 목록에 자동으로 추가한다.

**Tech Stack:** Python, Streamlit(`st.fragment`), httpx(기존 `LawApiClient`), pytest.

**Spec:** `docs/superpowers/specs/2026-09-08-progressive-body-verification-design.md` — 이 계획은 그 스펙을 구현 순서로 옮긴 것이며, 실행자는 스펙과 이 계획을 함께 읽는다.

## Global Constraints

- 본문에 검색어의 정확 일치가 없으면 그 문서를 본문 결과로 표시하지 않는다 — 이번 변경은 "검증 대상에 오르는 후보의 범위와 순서"만 바꾸고, 정확 일치 판정 로직(`detail.py`, `_verify_one`이 될 기존 검증 로직)은 그대로 둔다.
- 우선순위 키워드가 없으면(빈 튜플) 지금과 완전히 동일하게 동작해야 한다 — 기존 테스트는 코드 수정 없이 그대로 통과해야 한다.
- API 요청 파라미터(`display=100` 등)와 캐시 TTL(24시간)은 바꾸지 않는다. 페이지 개수만 늘어난다.
- 화면 전체가 다시 그려지거나 스크롤이 튀는 방식은 쓰지 않는다 — 점진적 진행 표시는 `st.fragment`가 감싼 영역만 다시 그린다.
- 나중에 확인된 결과는 버튼 없이 자동으로 기존 그룹(법률/대통령령/총리령·부령/행정규칙/자치법규)에 추가된다.
- API 키·인증값은 소스·로그·화면에 노출하지 않는다(기존 원칙 유지).
- 각 태스크 끝에 관련 pytest를 실행하고, 전체 태스크가 끝나면 `python -m pytest -v`로 전체 스위트를 한 번 더 확인한다.

---

## Task 1: `totalCnt` 추출 헬퍼

**Files:**
- Modify: `src/lawsearch/normalize.py`
- Test: `tests/test_normalize.py`

**Interfaces:**
- Produces: `extract_total_count(payload: Mapping[str, Any], source: SourceGroup) -> int | None` — 이후 태스크(페이지네이션 루프)가 이 함수로 "더 받아올 페이지가 있는지" 판단한다.

- [ ] **Step 1: Write the failing test**

`tests/test_normalize.py` 맨 아래에 추가:

```python
def test_extract_total_count_reads_wrapper_field():
    from lawsearch.normalize import extract_total_count

    payload = {"LawSearch": {"totalCnt": "806", "law": []}}
    assert extract_total_count(payload, SourceGroup.LAW) == 806


def test_extract_total_count_returns_none_when_missing_or_invalid():
    from lawsearch.normalize import extract_total_count

    assert extract_total_count({"LawSearch": {}}, SourceGroup.LAW) is None
    assert extract_total_count({}, SourceGroup.LAW) is None
    assert extract_total_count({"LawSearch": {"totalCnt": "abc"}}, SourceGroup.LAW) is None
```

(파일 상단에 `SourceGroup`이 이미 import돼 있는지 확인하고 없으면 `from lawsearch.models import SourceGroup`를 추가한다.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_normalize.py -k extract_total_count -v`
Expected: FAIL with `ImportError: cannot import name 'extract_total_count'`

- [ ] **Step 3: Write minimal implementation**

`src/lawsearch/normalize.py`에 `_shape_error` 함수 위(파일 맨 아래 근처)에 추가:

```python
def extract_total_count(payload: Mapping[str, Any], source: SourceGroup) -> int | None:
    wrapper_name, _ = _SOURCE_SHAPES[source]
    wrapper = payload.get(wrapper_name)
    if not isinstance(wrapper, Mapping):
        return None
    raw = wrapper.get("totalCnt", wrapper.get("검색결과개수"))
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_normalize.py -v`
Expected: 전체 PASS (기존 테스트 포함)

- [ ] **Step 5: Commit**

```bash
git add src/lawsearch/normalize.py tests/test_normalize.py
git commit -m "feat: add extract_total_count for pagination decisions"
```

---

## Task 2: `SearchResponse.pending` 필드 추가

**Files:**
- Modify: `src/lawsearch/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: 없음 (독립적인 데이터 모델 변경)
- Produces: `SearchResponse.pending: tuple[SearchResult, ...]` (기본값 `()`) — 이후 `SearchService.search()`가 검증되지 않은 "나머지" 후보를 여기 담아 반환하고, `app.py`가 이걸 읽어 점진적 검증 큐를 채운다.

- [ ] **Step 1: Write the failing test**

`tests/test_models.py`에 추가:

```python
def test_search_response_pending_defaults_to_empty_tuple():
    response = SearchResponse(
        results=(), suggestions=(), errors=(), source_states={}, source_fetched_at={}
    )
    assert response.pending == ()


def test_search_response_accepts_explicit_pending(result_factory):
    pending_result = result_factory(SourceGroup.LAW, uid="p1", title="대기 법령")
    response = SearchResponse(
        results=(),
        pending=(pending_result,),
        suggestions=(),
        errors=(),
        source_states={},
        source_fetched_at={},
    )
    assert response.pending == (pending_result,)
```

(`result_factory`는 `tests/conftest.py`의 기존 fixture다. `test_models.py`가 `SourceGroup`을 이미 import하고 있는지 확인.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_models.py -k pending -v`
Expected: FAIL with `TypeError: SearchResponse.__init__() got an unexpected keyword argument 'pending'`

- [ ] **Step 3: Write minimal implementation**

`src/lawsearch/models.py`의 `SearchResponse` 정의를 수정 (반드시 **맨 뒤**에 기본값 있는 필드로 추가 — 기존 위치 기반 생성 코드가 없다는 건 이미 확인했지만, 필드 순서를 지켜 하위 호환을 보장한다):

```python
@dataclass(frozen=True)
class SearchResponse:
    results: tuple[SearchResult, ...]
    suggestions: tuple[str, ...]
    errors: tuple[SourceError, ...]
    source_states: Mapping[str, SourceState]
    source_fetched_at: Mapping[str, datetime]
    pending: tuple[SearchResult, ...] = ()

    def __post_init__(self) -> None:
        ...  # 기존 검증 로직 그대로 둔다
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_models.py -v`
Expected: 전체 PASS

- [ ] **Step 5: Commit**

```bash
git add src/lawsearch/models.py tests/test_models.py
git commit -m "feat: add SearchResponse.pending field for staged verification"
```

---

## Task 3: `FakeApi`가 페이지별로 다른 응답을 줄 수 있게 확장

**Files:**
- Modify: `tests/conftest.py`

**Interfaces:**
- Consumes: 없음
- Produces: `FakeApi`의 `responses` 딕셔너리가 `(operation, query, page)` 3-튜플 키도 지원(우선 조회, 없으면 기존 `(operation, query)` 2-튜플로 대체). `.requests` 리스트 형태(2-튜플)는 **바꾸지 않는다** — 기존 테스트가 `("laws", "주차 단속") in fake_api.requests` 같은 2-튜플 단언을 쓰고 있어서, 이 형태를 건드리면 무관한 기존 테스트가 깨진다.

이 태스크는 그 자체로 관찰 가능한 동작 변화가 없으므로(운영 코드가 아직 페이지를 더 요청하지 않음), 별도 신규 테스트 없이 기존 스위트가 그대로 통과하는 것으로 검증한다.

- [ ] **Step 1: Modify `FakeApi._search` and its callers**

`tests/conftest.py`의 `FakeApi` 클래스를 수정:

```python
    def _search(self, operation: str, query: str, fixture: str, page: int = 1):
        self.calls.add(operation)
        self.requests.append((operation, query))
        if operation in self.fail or (operation, query) in self.fail:
            raise ApiError(f"{operation} failed safely")
        configured = self.responses.get((operation, query, page))
        if configured is None:
            configured = self.responses.get((operation, query))
        if configured is not None:
            return deepcopy(configured)
        if operation.endswith("_titles"):
            wrapper = {
                "laws_titles": "LawSearch",
                "admin_rules_titles": "AdmRulSearch",
                "municipal_titles": "OrdinSearch",
                "provincial_titles": "OrdinSearch",
            }[operation]
            return {wrapper: {"totalCnt": "0"}}
        return load_fixture(fixture)

    async def search_laws(self, query: str, page: int = 1, *, title_only=False):
        operation = "laws_titles" if title_only else "laws"
        return self._search(operation, query, "law-multiple.json", page)

    async def search_admin_rules(self, query: str, page: int = 1, *, title_only=False):
        operation = "admin_rules_titles" if title_only else "admin_rules"
        return self._search(operation, query, "admrul.json", page)

    async def search_ordinances(
        self, query, region, province_only, page=1, *, title_only=False
    ):
        operation = "provincial" if province_only else "municipal"
        if title_only:
            operation += "_titles"
        fixture = "ordin-provincial.json" if province_only else "ordin.json"
        return self._search(operation, query, fixture, page)
```

(바뀐 부분: `_search`가 `page` 매개변수를 받고, 3-튜플 키를 먼저 찾아본 뒤 없으면 기존 2-튜플로 대체하며, 세 개의 `search_*` 메서드가 `page`를 `_search`로 넘긴다. `self.requests.append((operation, query))`는 그대로다.)

- [ ] **Step 2: Run full suite to confirm nothing broke**

Run: `.venv/Scripts/python.exe -m pytest -v`
Expected: 전체 PASS (동작 변화 없음 — page 인자를 받기만 하고, 아직 아무도 page>1로 호출하지 않음)

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "test: make FakeApi page-aware for pagination tests"
```

---

## Task 4: 본문 검색 전체 페이지 조회

**Files:**
- Modify: `src/lawsearch/service.py`
- Test: `tests/test_service.py`

**Interfaces:**
- Consumes: `extract_total_count`(Task 1), `FakeApi`의 page-aware `responses`(Task 3)
- Produces: `SearchService._search_variant(...)`가 이제 `totalCnt`까지 모든 페이지를 합쳐서 반환한다. 반환 타입(`SourceOutcome`, 4-튜플)은 바뀌지 않는다 — 내부적으로만 여러 페이지를 순회한다.

- [ ] **Step 1: Write the failing test**

`tests/test_service.py` 끝에 추가:

```python
def test_law_search_fetches_additional_pages_until_total_count_is_covered(
    service_factory, parsed_plain
):
    page_one = {
        "LawSearch": {
            "totalCnt": "4",
            "law": [
                {
                    "법령ID": f"100{i}",
                    "법령일련번호": f"100{i}",
                    "법령명한글": f"앞자리법{i}",
                    "법령구분명": "법률",
                    "현행연혁코드": "현행",
                    "공포일자": "20260101",
                    "법령상세링크": f"/법령/앞자리법{i}",
                }
                for i in range(3)
            ],
        }
    }
    page_two = {
        "LawSearch": {
            "totalCnt": "4",
            "law": [
                {
                    "법령ID": "2000",
                    "법령일련번호": "2000",
                    "법령명한글": "도시 및 주거환경정비법",
                    "법령구분명": "법률",
                    "현행연혁코드": "현행",
                    "공포일자": "20260101",
                    "법령상세링크": "/법령/도시정비법",
                }
            ],
        }
    }
    responses = {
        ("laws", "주차 단속"): page_one,
        ("laws", "주차 단속", 2): page_two,
    }
    service, fake_api = service_factory(responses=responses)

    response = run(service.search(parsed_plain))

    titles = {result.title for result in response.results}
    assert "도시 및 주거환경정비법" in titles
    assert ("laws", "주차 단속") in fake_api.requests
```

(파일 상단에 이미 있는 `run`, `service_factory`, `parsed_plain`을 그대로 쓴다. `FakeApi.fetch_detail`이 항상 "주차 단속 근거 조문"이 포함된 고정 payload를 반환하므로, 이 4건 모두 본문 검증을 통과한다.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_service.py -k additional_pages -v`
Expected: FAIL — "도시 및 주거환경정비법"이 `titles`에 없음 (지금은 1페이지만 봄)

- [ ] **Step 3: Write minimal implementation**

`src/lawsearch/service.py`에서 기존 `_search_variant` 메서드 전체를 **`_fetch_page`로 이름을 바꾸고**, `total_count`를 추가로 반환하도록 수정한다. 그 자리에 페이지를 순회하는 **새 `_search_variant`**를 만든다.

기존 `_search_variant` (지울 것):
```python
    async def _search_variant(
        self,
        name: str,
        group: SourceGroup,
        query: str,
        quality: MatchQuality,
        parsed: ParsedQuery,
        refresh: bool,
        page: int,
        scope: SearchScope,
    ) -> SourceOutcome:
        now = self._clock()
        region_codes = _region_codes(parsed, name)
        cache_source = f"{name}_titles" if scope is SearchScope.TITLE else name
        key = make_cache_key(cache_source, query, region_codes, page)
        cached = self._cache.get(key, now)
        if cached is not None and cached.is_fresh and not refresh:
            normalized = normalize_results(
                cached.payload, group, quality, cached.fetched_at, scope=scope,
            )
            return (
                _filter_provincial_results(name, parsed, normalized),
                SourceState.FRESH_CACHE, False, cached.fetched_at,
            )
        try:
            payload = await self._call_source(
                name, query, parsed, page, title_only=scope is SearchScope.TITLE
            )
            fetched_at = self._clock()
            normalized = normalize_results(payload, group, quality, fetched_at, scope=scope)
        except (ApiError, ResponseShapeError):
            if cached is None:
                return (), SourceState.ERROR, True, None
            normalized = normalize_results(
                cached.payload, group, quality, cached.fetched_at, scope=scope,
            )
            return (
                _filter_provincial_results(name, parsed, normalized),
                SourceState.STALE_FALLBACK, True, cached.fetched_at,
            )
        self._cache.put(key, payload, fetched_at)
        normalized = _filter_provincial_results(name, parsed, normalized)
        return (
            normalized,
            SourceState.LIVE if normalized else SourceState.EMPTY,
            False, fetched_at,
        )
```

새 코드 (이 자리에 그대로 대체):
```python
    async def _fetch_page(
        self,
        name: str,
        group: SourceGroup,
        query: str,
        quality: MatchQuality,
        parsed: ParsedQuery,
        refresh: bool,
        page: int,
        scope: SearchScope,
    ) -> tuple[tuple[SearchResult, ...], SourceState, bool, datetime | None, int | None]:
        now = self._clock()
        region_codes = _region_codes(parsed, name)
        cache_source = f"{name}_titles" if scope is SearchScope.TITLE else name
        key = make_cache_key(cache_source, query, region_codes, page)
        cached = self._cache.get(key, now)
        if cached is not None and cached.is_fresh and not refresh:
            normalized = normalize_results(
                cached.payload, group, quality, cached.fetched_at, scope=scope,
            )
            return (
                _filter_provincial_results(name, parsed, normalized),
                SourceState.FRESH_CACHE,
                False,
                cached.fetched_at,
                extract_total_count(cached.payload, group),
            )
        try:
            payload = await self._call_source(
                name, query, parsed, page, title_only=scope is SearchScope.TITLE
            )
            fetched_at = self._clock()
            normalized = normalize_results(payload, group, quality, fetched_at, scope=scope)
        except (ApiError, ResponseShapeError):
            if cached is None:
                return (), SourceState.ERROR, True, None, None
            normalized = normalize_results(
                cached.payload, group, quality, cached.fetched_at, scope=scope,
            )
            return (
                _filter_provincial_results(name, parsed, normalized),
                SourceState.STALE_FALLBACK,
                True,
                cached.fetched_at,
                extract_total_count(cached.payload, group),
            )
        self._cache.put(key, payload, fetched_at)
        normalized = _filter_provincial_results(name, parsed, normalized)
        return (
            normalized,
            SourceState.LIVE if normalized else SourceState.EMPTY,
            False,
            fetched_at,
            extract_total_count(payload, group),
        )

    async def _search_variant(
        self,
        name: str,
        group: SourceGroup,
        query: str,
        quality: MatchQuality,
        parsed: ParsedQuery,
        refresh: bool,
        page: int,
        scope: SearchScope,
    ) -> SourceOutcome:
        results, state, error, fetched_at, total = await self._fetch_page(
            name, group, query, quality, parsed, refresh, page, scope
        )
        if error:
            return results, state, error, fetched_at
        accumulated = list(results)
        current_page = page
        while total is not None and len(accumulated) < total and results:
            current_page += 1
            results, page_state, page_error, page_fetched_at, total = await self._fetch_page(
                name, group, query, quality, parsed, refresh, current_page, scope
            )
            if page_error or not results:
                break
            accumulated.extend(results)
            state = _result_state([state, page_state])
            if page_fetched_at is not None:
                fetched_at = (
                    page_fetched_at
                    if fetched_at is None
                    else min(fetched_at, page_fetched_at)
                )
        return tuple(accumulated), state, error, fetched_at
```

`normalize.py`에서 `extract_total_count`를 import하는 줄을 파일 상단 import 목록에 추가한다:

```python
from lawsearch.normalize import ResponseShapeError, extract_total_count, normalize_results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_service.py -v`
Expected: 전체 PASS (새 테스트 포함, 기존 테스트도 전부 그대로 — 기존 fixture들은 `totalCnt`가 이미 있는 레코드 수와 같아서 추가 페이지를 요청하지 않는다)

- [ ] **Step 5: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -v`
Expected: 전체 PASS (216건대에서 이 태스크까지 몇 건 늘어난 숫자로 PASS, 0 FAIL)

- [ ] **Step 6: Commit**

```bash
git add src/lawsearch/service.py tests/test_service.py
git commit -m "fix: fetch every page of body-search candidates, not just the first"
```

---

## Task 5: `classify_candidates()` 순수 함수

**Files:**
- Create: `src/lawsearch/prioritization.py`
- Test: `tests/test_prioritization.py`

**Interfaces:**
- Consumes: `SearchResult`, `SourceState`(둘 다 `lawsearch.models`에서 import)
- Produces: `classify_candidates(candidates: tuple[tuple[SearchResult, SourceState], ...], keywords: tuple[str, ...]) -> tuple[tuple[tuple[SearchResult, SourceState], ...], tuple[tuple[SearchResult, SourceState], ...]]` (우선순위, 나머지) 및 `PRIORITY_KEYWORDS: tuple[str, ...]` 상수 — Task 6이 `service.py`에서, Task 8이 `app.py`에서 이 상수를 가져다 쓴다.

- [ ] **Step 1: Write the failing test**

`tests/test_prioritization.py` (새 파일):

```python
from lawsearch.models import SourceState
from lawsearch.prioritization import PRIORITY_KEYWORDS, classify_candidates


def test_classify_candidates_splits_by_title_keyword(result_factory):
    from lawsearch.models import SourceGroup

    matching = result_factory(SourceGroup.LAW, uid="1", title="도시 및 주거환경정비법")
    other = result_factory(SourceGroup.LAW, uid="2", title="관세법")
    candidates = (
        (matching, SourceState.LIVE),
        (other, SourceState.LIVE),
    )

    priority, rest = classify_candidates(candidates, ("도시",))

    assert priority == ((matching, SourceState.LIVE),)
    assert rest == ((other, SourceState.LIVE),)


def test_classify_candidates_treats_all_as_priority_when_no_keywords(result_factory):
    from lawsearch.models import SourceGroup

    a = result_factory(SourceGroup.LAW, uid="1", title="관세법")
    candidates = ((a, SourceState.LIVE),)

    priority, rest = classify_candidates(candidates, ())

    assert priority == candidates
    assert rest == ()


def test_priority_keywords_constant_is_nonempty():
    assert len(PRIORITY_KEYWORDS) > 0
    assert "도시" in PRIORITY_KEYWORDS
    assert "소방" in PRIORITY_KEYWORDS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_prioritization.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lawsearch.prioritization'`

- [ ] **Step 3: Write minimal implementation**

`src/lawsearch/prioritization.py` (새 파일):

```python
from lawsearch.models import SearchResult, SourceState


PRIORITY_KEYWORDS: tuple[str, ...] = (
    # 정비사업 핵심
    "도시", "주택", "주거", "정비", "재건축", "재개발", "도심",
    # 인허가·계획
    "국토", "개발", "건축", "택지", "혁신도시", "공업지역", "부동산",
    # 기반시설·설비
    "도로", "하천", "수도", "하수도", "공원", "녹지", "교통", "주차장",
    "설비", "전력", "에너지",
    # 안전·재난
    "소방", "화재", "재난", "위험물", "안전관리", "승강기", "다중이용업소",
    # 환경·자연
    "환경", "산지", "산림", "농지",
    # 행정·재무
    "조세", "감정평가", "건설산업",
    # 기타
    "문화재", "장애인",
)


def classify_candidates(
    candidates: tuple[tuple[SearchResult, SourceState], ...],
    keywords: tuple[str, ...] = PRIORITY_KEYWORDS,
) -> tuple[
    tuple[tuple[SearchResult, SourceState], ...],
    tuple[tuple[SearchResult, SourceState], ...],
]:
    """Split candidates into (priority, rest) by whether their title contains
    any of ``keywords``. This only affects verification *order* — it never
    decides whether a result is ultimately accepted."""
    if not keywords:
        return tuple(candidates), ()
    priority = []
    rest = []
    for item in candidates:
        result, _ = item
        if any(keyword in result.title for keyword in keywords):
            priority.append(item)
        else:
            rest.append(item)
    return tuple(priority), tuple(rest)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_prioritization.py -v`
Expected: 전체 PASS

- [ ] **Step 5: Commit**

```bash
git add src/lawsearch/prioritization.py tests/test_prioritization.py
git commit -m "feat: add classify_candidates and the confirmed priority keyword list"
```

---

## Task 6: `_search_source`/`search()`에 우선순위 분류 연결

**Files:**
- Modify: `src/lawsearch/service.py`
- Test: `tests/test_service.py`

**Interfaces:**
- Consumes: `classify_candidates`(Task 5), `SearchResponse.pending`(Task 2)
- Produces: `SearchService.search(parsed, refresh=False, page=1, priority_keywords=())` — `priority_keywords`가 비어 있으면(기본값) 지금과 완전히 동일하게 전체를 검증한다. 비어 있지 않으면 우선순위만 검증하고 나머지는 `response.pending`으로 돌려준다.

- [ ] **Step 1: Write the failing test**

`tests/test_service.py`에 추가:

```python
def test_priority_keywords_defer_non_matching_candidates_to_pending(
    service_factory, parsed_plain
):
    responses = {
        ("laws", "주차 단속"): {
            "LawSearch": {
                "totalCnt": "2",
                "law": [
                    {
                        "법령ID": "1", "법령일련번호": "1",
                        "법령명한글": "도시 및 주거환경정비법",
                        "법령구분명": "법률", "현행연혁코드": "현행",
                        "공포일자": "20260101", "법령상세링크": "/법령/도시정비법",
                    },
                    {
                        "법령ID": "2", "법령일련번호": "2",
                        "법령명한글": "관세법",
                        "법령구분명": "법률", "현행연혁코드": "현행",
                        "공포일자": "20260101", "법령상세링크": "/법령/관세법",
                    },
                ],
            }
        },
    }
    service, fake_api = service_factory(responses=responses)

    response = run(
        service.search(parsed_plain, priority_keywords=("도시",))
    )

    result_titles = {result.title for result in response.results}
    pending_titles = {result.title for result in response.pending}
    assert "도시 및 주거환경정비법" in result_titles
    assert "관세법" not in result_titles
    assert "관세법" in pending_titles
    assert [op for op, _ in fake_api.requests].count("detail") == 1


def test_empty_priority_keywords_behaves_exactly_like_before(
    service_factory, parsed_plain
):
    service, fake_api = service_factory()

    default_response = run(service.search(parsed_plain))
    explicit_response = run(service.search(parsed_plain, priority_keywords=()))

    assert default_response.results == explicit_response.results
    assert default_response.pending == () == explicit_response.pending
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_service.py -k priority_keywords -v`
Expected: FAIL with `TypeError: search() got an unexpected keyword argument 'priority_keywords'`

- [ ] **Step 3: Write minimal implementation**

`src/lawsearch/service.py`에서 `search()`, `_search_source()`를 수정한다. 우선 import 줄에 추가:

```python
from lawsearch.prioritization import classify_candidates
```

`search()` 시그니처와 소스 태스크 생성 부분:

```python
    async def search(
        self,
        parsed: ParsedQuery,
        refresh: bool = False,
        page: int = 1,
        priority_keywords: tuple[str, ...] = (),
    ) -> SearchResponse:
        if parsed.candidates:
            raise SearchValidationError("지역 후보를 하나로 확정해야 검색할 수 있습니다.")

        sources = [
            ("laws", SourceGroup.LAW),
            ("admin_rules", SourceGroup.ADMIN_RULE),
        ]
        if parsed.region is not None:
            if parsed.region.sborg is not None:
                sources.append(("municipal", SourceGroup.MUNICIPAL))
            sources.append(("provincial", SourceGroup.PROVINCIAL))

        detail_semaphore = asyncio.Semaphore(_DETAIL_VERIFICATION_CONCURRENCY)
        source_tasks = [
            self._search_source(
                name, group, parsed, refresh, page, detail_semaphore, priority_keywords
            )
            for name, group in sources
        ]
        gathered = await asyncio.gather(
            *source_tasks,
            self._suggest(parsed.keyword, refresh),
            return_exceptions=True,
        )

        results: list[SearchResult] = []
        pending: list[SearchResult] = []
        errors: list[SourceError] = []
        states: dict[str, SourceState] = {}
        fetched_at: dict[str, datetime] = {}
        for (name, _), outcome in zip(sources, gathered[:-1]):
            if isinstance(outcome, BaseException):
                states[name] = SourceState.ERROR
                errors.append(SourceError(name, f"{name} search failed"))
                continue
            source_results, state, source_error, source_fetched_at, source_pending = outcome
            results.extend(source_results)
            pending.extend(source_pending)
            states[name] = state
            if source_fetched_at is not None:
                fetched_at[name] = source_fetched_at
            if source_error is not None:
                errors.append(source_error)

        suggestion_outcome = gathered[-1]
        if isinstance(suggestion_outcome, BaseException):
            suggestions = ()
            errors.append(SourceError("terms", "terms search failed"))
        else:
            suggestions = suggestion_outcome

        return SearchResponse(
            results=rank_results(_deduplicate(results), parsed.region, parsed.keyword),
            pending=tuple(pending),
            suggestions=suggestions,
            errors=tuple(errors),
            source_states=states,
            source_fetched_at=fetched_at,
        )
```

`_search_source()` 시그니처와 우선순위 분류 부분:

```python
    async def _search_source(
        self,
        name: str,
        group: SourceGroup,
        parsed: ParsedQuery,
        refresh: bool,
        page: int,
        detail_semaphore: asyncio.Semaphore,
        priority_keywords: tuple[str, ...] = (),
    ) -> tuple[
        tuple[SearchResult, ...],
        SourceState,
        SourceError | None,
        datetime | None,
        tuple[SearchResult, ...],
    ]:
        variants = build_query_variants(parsed.keyword)
        outcomes = [
            await self._search_variant(
                name, group, variants[0].query, variants[0].quality,
                parsed, refresh, page, SearchScope.TITLE,
            )
        ]
        for variant in variants:
            outcomes.append(
                await self._search_variant(
                    name, group, variant.query, variant.quality,
                    parsed, refresh, page, SearchScope.BODY,
                )
            )

        retained = _retain_best_results(outcomes)
        had_failure = any(outcome[2] for outcome in outcomes)
        if not retained and not had_failure:
            tokens = tuple(dict.fromkeys(parsed.keyword.split()))
            if len(tokens) >= 2:
                token_outcomes = []
                for token in tokens:
                    outcome = await self._search_variant(
                        name, group, token, MatchQuality.ALL_TERMS,
                        parsed, refresh, page, SearchScope.BODY,
                    )
                    token_outcomes.append(outcome)
                    outcomes.append(outcome)
                retained = _intersect_token_outcomes(token_outcomes)

        priority, rest = classify_candidates(retained, priority_keywords)

        retained, validation_failed = await self._verify_body_results(
            priority, parsed.keyword, refresh, detail_semaphore,
        )
        state = (
            SourceState.ERROR
            if validation_failed and not retained
            else _combine_state(outcomes, retained)
        )
        error = (
            SourceError(name, f"{name} search failed")
            if validation_failed or any(outcome[2] for outcome in outcomes)
            else None
        )
        source_fetched_at = (
            min(item.fetched_at for item, _ in retained)
            if retained
            else _outcome_fetched_at(outcomes, state)
        )
        pending = tuple(result for result, _ in rest)
        return (
            tuple(item[0] for item in retained),
            state,
            error,
            source_fetched_at,
            pending,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_service.py -v`
Expected: 전체 PASS

- [ ] **Step 5: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -v`
Expected: 전체 PASS

- [ ] **Step 6: Commit**

```bash
git add src/lawsearch/service.py tests/test_service.py
git commit -m "feat: verify only priority candidates when priority_keywords is set"
```

---

## Task 7: `verify_pending()` — 나중에 나머지를 검증하는 메서드

**Files:**
- Modify: `src/lawsearch/service.py`
- Test: `tests/test_service.py`

**Interfaces:**
- Consumes: 없음 (기존 `load_contexts` 재사용)
- Produces: `SearchService.verify_pending(pending: tuple[SearchResult, ...], keyword: str, refresh: bool = False) -> tuple[SearchResult, ...]` — Task 9에서 `app.py`가 이 메서드를 호출해 큐에서 꺼낸 한 묶음을 검증한다.

- [ ] **Step 1: Write the failing test**

`tests/test_service.py`에 추가:

```python
def test_verify_pending_keeps_only_exact_matches(service_factory, result_factory):
    service, fake_api = service_factory()
    candidate = result_factory(SourceGroup.LAW, uid="p1", title="대기 법령")

    confirmed = run(service.verify_pending((candidate,), "주차 단속"))

    assert len(confirmed) == 1
    assert confirmed[0].match_context is not None
    assert [op for op, _ in fake_api.requests].count("detail") == 1


def test_verify_pending_drops_candidates_with_no_exact_context(
    service_factory, result_factory
):
    service, fake_api = service_factory()
    candidate = result_factory(SourceGroup.LAW, uid="p1", title="대기 법령")

    confirmed = run(service.verify_pending((candidate,), "전혀 다른 문구"))

    assert confirmed == ()
```

(`SourceGroup`이 `test_service.py` 상단에 이미 import되어 있는지 확인.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_service.py -k verify_pending -v`
Expected: FAIL with `AttributeError: 'SearchService' object has no attribute 'verify_pending'`

- [ ] **Step 3: Write minimal implementation**

`src/lawsearch/service.py`에서 기존 `_verify_body_results`를 아래처럼 바꾸고(내부 로직을 `_verify_one`으로 뽑아낸다), `verify_pending`을 새로 추가한다:

```python
    async def _verify_one(
        self,
        result: SearchResult,
        keyword: str,
        refresh: bool,
        semaphore: asyncio.Semaphore,
    ) -> tuple[SearchResult | None, bool]:
        if result.scope is SearchScope.TITLE and _title_matches_query(
            result.title, keyword
        ):
            return result, False
        async with semaphore:
            detail = await self.load_contexts(result, keyword, refresh)
        if detail.state is SourceState.ERROR:
            return None, True
        if not detail.contexts:
            return None, False
        context = detail.contexts[0]
        if result.scope is SearchScope.TITLE:
            return replace(result, scope=SearchScope.BODY, match_context=context), False
        return replace(result, match_context=context), False

    async def _verify_body_results(
        self,
        retained: tuple[tuple[SearchResult, SourceState], ...],
        keyword: str,
        refresh: bool,
        semaphore: asyncio.Semaphore,
    ) -> tuple[tuple[tuple[SearchResult, SourceState], ...], bool]:
        async def verify(
            item: tuple[SearchResult, SourceState],
        ) -> tuple[tuple[SearchResult, SourceState] | None, bool]:
            result, state = item
            verified, failed = await self._verify_one(result, keyword, refresh, semaphore)
            if verified is None:
                return None, failed
            return (verified, state), failed

        verified = await asyncio.gather(*(verify(item) for item in retained))
        return (
            tuple(item for item, _ in verified if item is not None),
            any(failed for _, failed in verified),
        )

    async def verify_pending(
        self,
        pending: tuple[SearchResult, ...],
        keyword: str,
        refresh: bool = False,
    ) -> tuple[SearchResult, ...]:
        """Verify a batch of previously-deferred candidates. Silently drops
        any that fail verification or don't have an exact match — this is
        best-effort background work, never a source of user-facing errors."""
        semaphore = asyncio.Semaphore(_DETAIL_VERIFICATION_CONCURRENCY)
        verified = await asyncio.gather(
            *(self._verify_one(result, keyword, refresh, semaphore) for result in pending)
        )
        return tuple(result for result, _ in verified if result is not None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_service.py -v`
Expected: 전체 PASS

- [ ] **Step 5: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -v`
Expected: 전체 PASS

- [ ] **Step 6: Commit**

```bash
git add src/lawsearch/service.py tests/test_service.py
git commit -m "refactor: extract _verify_one and add verify_pending for staged checks"
```

---

## Task 8: 검색 직후 `pending` 큐를 세션 상태에 저장

**Files:**
- Modify: `src/lawsearch/app.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `PRIORITY_KEYWORDS`(Task 5), `SearchService.search(..., priority_keywords=...)`(Task 6)
- Produces: 검색 후 `st.session_state`에 `pending_queue`(list), `pending_total`(int), `pending_checked`(int), `pending_found`(int)이 채워진다. Task 9의 진행 표시 함수가 이 키들을 읽고 쓴다.

- [ ] **Step 1: Write the failing test**

`tests/test_app.py`에서 기존 `test_new_search_resets_workspace_and_detail_state` 근처에 추가:

```python
def test_perform_search_seeds_pending_queue_from_response(monkeypatch, result_factory):
    streamlit = ControllerStub()
    streamlit.spinner = lambda message: nullcontext()
    pending_result = result_factory(SourceGroup.LAW, uid="p1", title="대기 법령")
    response = SearchResponse(
        results=(),
        pending=(pending_result,),
        suggestions=(),
        errors=(),
        source_states={},
        source_fetched_at={},
    )

    async def fake_search(settings, parsed, refresh):
        return response

    monkeypatch.setattr(app, "_search", fake_search)

    app._perform_search(streamlit, object(), ParsedQuery("통합심의"), refresh=False)

    assert streamlit.session_state["pending_queue"] == [pending_result]
    assert streamlit.session_state["pending_total"] == 1
    assert streamlit.session_state["pending_checked"] == 0
    assert streamlit.session_state["pending_found"] == 0


def test_clear_response_also_clears_pending_state():
    streamlit = ControllerStub(
        {
            "pending_queue": [1, 2],
            "pending_total": 2,
            "pending_checked": 1,
            "pending_found": 0,
        }
    )

    app._clear_response(streamlit)

    for key in ("pending_queue", "pending_total", "pending_checked", "pending_found"):
        assert key not in streamlit.session_state
```

(파일 상단에 `SourceGroup`, `SearchResponse`가 이미 import돼 있는지 확인하고 없으면 추가한다.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_app.py -k pending -v`
Expected: FAIL — `KeyError: 'pending_queue'`

- [ ] **Step 3: Write minimal implementation**

`src/lawsearch/app.py` 상단 import에 추가:

```python
from lawsearch.prioritization import PRIORITY_KEYWORDS
```

`_search()`를 수정:

```python
async def _search(settings: Settings, parsed: ParsedQuery, refresh: bool) -> SearchResponse:
    async with LawApiClient(resolve_api_key(settings, _app_secrets())) as api:
        service = SearchService(api, CacheStore(settings.cache_path), lambda: datetime.now(UTC))
        return await service.search(parsed, refresh=refresh, priority_keywords=PRIORITY_KEYWORDS)
```

`_clear_response()`를 수정:

```python
def _clear_response(st: Any) -> None:
    st.session_state.pop("response", None)
    st.session_state.pop("parsed_query", None)
    st.session_state.pop("pending_queue", None)
    st.session_state.pop("pending_total", None)
    st.session_state.pop("pending_checked", None)
    st.session_state.pop("pending_found", None)
    _reset_workspace(st)
    _clear_detail_state(st)
```

`_perform_search()`를 수정 (성공 경로 마지막 부분):

```python
    st.session_state.parsed_query = parsed
    st.session_state.response = response
    st.session_state.pending_queue = list(response.pending)
    st.session_state.pending_total = len(response.pending)
    st.session_state.pending_checked = 0
    st.session_state.pending_found = 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_app.py -v`
Expected: 전체 PASS

- [ ] **Step 5: Commit**

```bash
git add src/lawsearch/app.py tests/test_app.py
git commit -m "feat: seed a pending-verification queue after each search"
```

---

## Task 9: 점진적 검증 진행 표시 (`st.fragment`)

**Files:**
- Modify: `src/lawsearch/app.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `st.session_state["pending_queue"/"pending_total"/"pending_checked"/"pending_found"/"response"]`(Task 8), `SearchService.verify_pending`(Task 7)
- Produces: `_render_pending_progress(st, settings, parsed)` — 순수하게 테스트 가능한 일반 함수(그 자체는 `st.fragment`로 감싸지 않는다). `main()`이 이 함수를 `st.fragment(run_every="2s")`로 감싸서 호출한다.

- [ ] **Step 1: Write the failing tests**

`tests/test_app.py` 끝에 추가:

```python
def test_pending_progress_does_nothing_when_no_pending_work():
    streamlit = FakeStreamlit(session_state={"pending_total": 0})

    app._render_pending_progress(streamlit, object(), ParsedQuery("통합심의"))

    assert streamlit.calls == []


def test_pending_progress_verifies_one_chunk_and_appends_confirmed_results(
    monkeypatch, result_factory
):
    pending_a = result_factory(SourceGroup.LAW, uid="p1", title="대기법1")
    pending_b = result_factory(SourceGroup.LAW, uid="p2", title="대기법2")
    confirmed = result_factory(
        SourceGroup.LAW, uid="p1", title="대기법1", match_context="일치 문맥"
    )
    existing = result_factory(SourceGroup.LAW, uid="e1", title="기존 법령")
    response = SearchResponse(
        results=(existing,),
        pending=(),
        suggestions=(),
        errors=(),
        source_states={},
        source_fetched_at={},
    )
    streamlit = FakeStreamlit(
        session_state={
            "response": response,
            "pending_queue": [pending_a, pending_b],
            "pending_total": 2,
            "pending_checked": 0,
            "pending_found": 0,
        }
    )

    async def fake_verify_pending(settings, chunk, keyword):
        assert chunk == (pending_a, pending_b)
        assert keyword == "통합심의"
        return (confirmed,)

    monkeypatch.setattr(app, "_verify_pending", fake_verify_pending)

    app._render_pending_progress(streamlit, object(), ParsedQuery("통합심의"))

    assert streamlit.session_state["pending_queue"] == []
    assert streamlit.session_state["pending_checked"] == 2
    assert streamlit.session_state["pending_found"] == 1
    assert confirmed in streamlit.session_state["response"].results
    assert existing in streamlit.session_state["response"].results
    assert "전체 확인 완료 (추가로 1건 발견)" in streamlit.text()


def test_pending_progress_shows_running_total_while_queue_remains(monkeypatch, result_factory):
    pending_items = [
        result_factory(SourceGroup.LAW, uid=f"p{i}", title=f"대기법{i}") for i in range(25)
    ]
    response = SearchResponse(
        results=(), pending=(), suggestions=(), errors=(),
        source_states={}, source_fetched_at={},
    )
    streamlit = FakeStreamlit(
        session_state={
            "response": response,
            "pending_queue": pending_items,
            "pending_total": 25,
            "pending_checked": 0,
            "pending_found": 0,
        }
    )

    async def fake_verify_pending(settings, chunk, keyword):
        assert len(chunk) == 20
        return ()

    monkeypatch.setattr(app, "_verify_pending", fake_verify_pending)

    app._render_pending_progress(streamlit, object(), ParsedQuery("통합심의"))

    assert len(streamlit.session_state["pending_queue"]) == 5
    assert streamlit.session_state["pending_checked"] == 20
    assert "나머지 확인 중… (20 / 25)" in streamlit.text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_app.py -k pending_progress -v`
Expected: FAIL — `AttributeError: module 'lawsearch.app' has no attribute '_render_pending_progress'`

- [ ] **Step 3: Write minimal implementation**

`src/lawsearch/app.py` 상단 import에 추가:

```python
from dataclasses import replace
from lawsearch.ranking import rank_results
```

`_search()` 아래 근처에 새 async 헬퍼 추가:

```python
async def _verify_pending(
    settings: Settings, pending: tuple[SearchResult, ...], keyword: str
) -> tuple[SearchResult, ...]:
    async with LawApiClient(resolve_api_key(settings, _app_secrets())) as api:
        service = SearchService(api, CacheStore(settings.cache_path), lambda: datetime.now(UTC))
        return await service.verify_pending(pending, keyword)
```

`_render_results` 함수 뒤에 새 함수 추가:

```python
_PENDING_CHUNK_SIZE = 20


def _render_pending_progress(st: Any, settings: Settings, parsed: ParsedQuery) -> None:
    queue = st.session_state.get("pending_queue")
    if not queue:
        if st.session_state.get("pending_total", 0):
            found = st.session_state.get("pending_found", 0)
            st.caption(
                f"전체 확인 완료 (추가로 {found}건 발견)" if found else "전체 확인 완료"
            )
        return
    chunk = tuple(queue[:_PENDING_CHUNK_SIZE])
    remaining = queue[_PENDING_CHUNK_SIZE:]
    try:
        confirmed = _run(_verify_pending(settings, chunk, parsed.keyword))
    except Exception as error:
        _logger.warning("나머지 결과 확인 실패: %s", type(error).__name__)
        confirmed = ()
    st.session_state.pending_queue = remaining
    st.session_state.pending_checked = st.session_state.get("pending_checked", 0) + len(chunk)
    if confirmed:
        st.session_state.pending_found = st.session_state.get("pending_found", 0) + len(confirmed)
        response = st.session_state.response
        combined = rank_results(response.results + confirmed, parsed.region, parsed.keyword)
        st.session_state.response = replace(response, results=combined)
    total = st.session_state.get("pending_total", 0)
    checked = st.session_state.get("pending_checked", 0)
    if remaining:
        st.caption(f"나머지 확인 중… ({checked} / {total})")
    else:
        found = st.session_state.get("pending_found", 0)
        st.caption(
            f"전체 확인 완료 (추가로 {found}건 발견)" if found else "전체 확인 완료"
        )
```

`main()`에서 결과 화면을 그리는 부분(기존 `else: _render_results(...)` 분기) 뒤에 추가:

```python
    else:
        _render_results(st, settings, response, parsed)
        if st.session_state.get("pending_total", 0):
            st.fragment(run_every="2s")(_render_pending_progress)(st, settings, parsed)
```

(이 마지막 줄은 실제 Streamlit에서만 의미가 있고, `main()` 자체는 이 저장소의 어떤 테스트도 직접 호출하지 않으므로 이 변경으로 깨지는 기존 테스트는 없다 — Step 4/5에서 확인한다.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_app.py -v`
Expected: 전체 PASS

- [ ] **Step 5: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -v`
Expected: 전체 PASS

- [ ] **Step 6: Commit**

```bash
git add src/lawsearch/app.py tests/test_app.py
git commit -m "feat: verify pending candidates progressively via st.fragment"
```

---

## Task 10: 로컬 수동 검증

**Files:** 없음 (코드 변경 없음, 실행 확인만)

- [ ] **Step 1: 로컬 앱 실행**

Run: `run.bat` (또는 이미 설정된 `.claude/launch.json`의 `law-search` preview로 Browser 도구 사용)

- [ ] **Step 2: "통합심의" 검색**

검색창에 `통합심의` 입력 후 검색. 우선순위 결과(도시/국토/건축 등 키워드가 제목에 있는 법령)가 먼저 뜨는지 확인.

- [ ] **Step 3: 점진적 진행 확인**

화면 하단(또는 사이드바 인근, `_render_results` 다음)에 "나머지 확인 중… (N / M)"이 몇 초 간격으로 갱신되는지, 이 동안 이미 뜬 카드들이 깜빡이거나 스크롤이 튀지 않는지 확인.

- [ ] **Step 4: 완료 후 "도시 및 주거환경정비법" 확인**

진행이 끝나면 "전체 확인 완료 (추가로 N건 발견)"으로 바뀌는지, 그리고 법률 그룹(또는 "법률 · 본문 관련 추가 결과")에 "도시 및 주거환경정비법"과 그 시행령이 실제로 나타나는지 확인. 카드 클릭 → 미리보기에서 "통합심의" 문맥이 실제로 보이는지 확인.

- [ ] **Step 5: 회귀 확인 — 방화구획**

기존 핵심 회귀 사례("방화구획" 검색에 "방화"만 있는 문서가 안 뜨는 것)가 여전히 지켜지는지 재검색으로 확인.

- [ ] **Step 6: CLAUDE_HANDOFF.md에 기록**

`docs/CLAUDE_HANDOFF.md`의 "해결한 실패 사례" 섹션에 이번 문제(법제처 API가 관련도순이 아니라 법령명 가나다순으로 응답해 페이지 상한에 걸린 문서가 통째로 빠지던 문제)와 수정(전체 페이지 조회 + 우선순위/점진적 검증)을 짧게 추가하고 커밋한다.

```bash
git add docs/CLAUDE_HANDOFF.md
git commit -m "docs: record the pagination recall fix in the handoff doc"
```
