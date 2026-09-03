# Desktop Search Workspace UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single vertical result list with a width-limited desktop workspace: 2-column result cards, a navigation sidebar, a single-document preview, and a side-by-side compare view — all reusing already-fetched results and the existing 24-hour SQLite cache.

**Architecture:** All rendering-independent decisions (grouping, card fields, sidebar tree, compare option lists, official-URL validation) move into a new pure module `lawsearch.viewmodels` that never imports Streamlit. `lawsearch.app` becomes a thin Streamlit layer that owns `st.session_state`, dispatches on a `view_mode` state machine (`results` / `preview` / `compare`), and renders what `viewmodels` computed. `SearchResult` gains an optional `match_context`; `SearchService` fills it with the first verified exact-match context during body verification so cards and previews can show a match line without a second API call.

**Tech Stack:** Python 3.11+, Streamlit 1.41–1.x, httpx 0.27–0.x, pytest. No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-09-03-desktop-search-workspace-design.md` (extends `docs/superpowers/specs/2026-08-11-korean-law-search-design.md`). Read both before starting, plus `docs/CLAUDE_HANDOFF.md` and `CLAUDE.md`.

**Out of scope for this plan (separate follow-up plan):** Streamlit Community Cloud private deployment — spec §8 and §12 step 5 (`config.py` dual local-file / `st.secrets` auth, `streamlit_app.py` entrypoint, `requirements.txt`, `.streamlit/secrets.toml` ignore, deploy docs). This plan keeps the app local-only and does not touch `config.py`.

## Global Constraints

Every task's requirements implicitly include this section. Values are copied verbatim from the spec and `CLAUDE.md`.

- **No AI expansion.** Never generate or search synonyms, related terms, or legal conclusions. Preserve the exact-phrase priority order: exact phrase → spacing-only variant → all-terms-in-one-document supplementary results.
- **Body results require a verified exact match.** A document with only a partial term (the `방화구획` → `방화` regression) must never appear as a body result. Never show generic metadata or an arbitrary article as if it were a match.
- **`match_context` provenance.** Only ever the first exact-match context string returned by body verification (`DetailResponse.contexts[0]`). Results matched by title only keep `match_context = None`.
- **Secrets.** API key, key-file path, and DRF `OC=` values must never appear in source, git, SQLite, logs, error messages, test output, or the screen.
- **`lawsearch.viewmodels` must not import `streamlit`** (add a test that asserts this).
- **Official links:** render a link button only when the URL passes `is_official_url` (HTTPS, host `law.go.kr` or `*.law.go.kr`, no credentials, port 443/none). Otherwise render no button.
- **Sidebar is navigation, not a filter.** Selecting a sidebar entry never hides other results and never calls the search or detail API directly. The full result set stays in the results view.
- **Compare never judges.** No automatic delegation/priority/difference detection. Always show the notice: `키워드 일치 조문을 나란히 표시하며 법적 연계 관계를 자동 확정하지 않습니다`.
- **Preview lazy-loads.** Title-only matches call the detail API on first preview open; body-verified matches reuse the cache populated during verification. A loaded detail is reused from `st.session_state` and the 24-hour SQLite cache. Returning to results never calls an API.
- **Interpreter:** `.venv/Scripts/python.exe`. Run `.venv/Scripts/python.exe -m pytest -q` for the suite. Live API tests stay opt-in (`RUN_LIVE_LAW_API=1`) and are not run here.
- **Commits:** one purpose per commit. End every commit message with:
  ```
  Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
  ```
  No `git push`, deployment, or repo-setting change without explicit user approval.

## Design decisions where the spec left room

These resolve spec ambiguities. Implement them exactly as stated here.

1. **Result identity key:** `f"{result.source.value}:{result.uid}"` (e.g. `law:001498`). Used for `selected_result_key`, `compare_left_result_key`, `compare_right_result_key`, and Streamlit widget keys. This is distinct from the existing `detail_session_key(source, uid, keyword)`, which stays the cache/session key for a loaded `DetailResponse`.
2. **Sidebar order follows the ranked card order,** not the illustrative tree in spec §4.2. Two fixed sections — `자치법규` and `상위법령` — where the section containing the first ranked result comes first (so `자치법규` leads when a region is selected, `상위법령` leads otherwise). Within a section, groups and entries follow `response.results` order. This satisfies spec §10 "사이드바 그룹과 카드 그룹이 기존 우선순위를 보존한다".
3. **Sidebar group labels** use fixed clean names: `법률`, `대통령령(시행령)`, `총리령·부령(시행규칙)`, `행정규칙`, `기타 법령`, and for local law the region-qualified label from the existing `_group_label` helper.
4. **Sidebar entry click opens the preview** (`view_mode = "preview"`, `selected_result_key = key`). It does not attempt in-page scroll-to-anchor. The click handler itself performs no fetch; the preview view then lazy-loads exactly as when opened from a card.
5. **Content width:** `layout="wide"` plus an injected `<style>` capping `.block-container` at `1100px`. The sidebar is Streamlit's native `st.sidebar`.
6. **Preview context limit:** `load_contexts` / `extract_contexts` are called with `limit=20` for the preview (re-extracted from the already-cached payload, so no extra API call), vs the default `limit=5` used during verification and on cards.
7. **Mode toggle:** the common top bar has two buttons, `기본 보기` and `비교하기`. `기본 보기` maps to `view_mode = "results"`; `비교하기` to `"compare"`. Preview is entered only from a card or sidebar entry.

## File Structure

**Created:**

| File | Responsibility |
| --- | --- |
| `src/lawsearch/viewmodels.py` | All Streamlit-independent presentation logic: `result_key`, result grouping (`ResultGroupView`, `build_grouped_view`), error messages, sidebar tree (`SidebarSection`/`SidebarGroup`/`SidebarEntry`, `sidebar_sections`), cards (`CardView`, `card_view`, `card_rows`), compare options (`CompareOption`, `compare_options`), official-URL validation (`is_official_url`), region label (`fully_qualified_region_name`), timestamp formatting (`format_timestamp`), `detail_session_key`, status-message text. |
| `tests/test_viewmodels.py` | Unit tests for `viewmodels`. Absorbs the grouping/label/URL tests currently in `tests/test_app.py` plus new card/sidebar/compare tests. |
| `tests/streamlit_stub.py` | `FakeStreamlit`: a recording stub supporting the widget/layout calls the render functions use (`columns`, `container`, `sidebar`, `expander`, `button`, `radio`, `selectbox`, `markdown`, `caption`, `subheader`, `link_button`, `info`, `warning`, `error`, `divider`, `rerun`). Shared by the app render tests. |

**Modified:**

| File | Change |
| --- | --- |
| `src/lawsearch/models.py` | Add `SearchResult.match_context: str \| None = None`. |
| `src/lawsearch/service.py` | `_verify_body_results` attaches `DetailResponse.contexts[0]` to the retained result's `match_context`. `load_contexts` gains `limit: int = 5`. |
| `src/lawsearch/app.py` | Remove the pure logic now in `viewmodels` (import from there). Add the `view_mode` state machine, session-state reset helpers, top bar with mode toggle, content-width CSS, and the four render functions: `_render_results` (2-column cards), `_render_sidebar`, `_render_preview`, `_render_compare`. |
| `tests/test_app.py` | Drop the tests that moved to `test_viewmodels.py`. Add state-machine, reset, and render-dispatch tests using `FakeStreamlit`. |
| `tests/test_service.py` | Add `match_context` threading tests. |
| `tests/test_models.py` | Add the `match_context` default test. |
| `tests/conftest.py` | `result_factory` gains `match_context: str \| None = None` and `scope: SearchScope = SearchScope.BODY` keyword params. |
| `README.md` | Replace the "실행과 검색 문법" result-list description with the workspace description. |
| `docs/CLAUDE_HANDOFF.md` | Move the implemented items out of §7 "아직 구현하지 않은 UI"; update §3 status table. |

---

## Task 1: `SearchResult.match_context` field

**Files:**
- Modify: `src/lawsearch/models.py:60-74`
- Modify: `tests/conftest.py:31-61`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `SearchResult.match_context: str | None` (default `None`), the last field of the frozen dataclass.
- Produces: `result_factory(source, *, uid=None, quality=MatchQuality.EXACT, effective="20260811", current=True, title=None, scope=SearchScope.BODY, match_context=None) -> SearchResult`.

- [ ] **Step 1: Write the failing test**

In `tests/test_models.py`, add:

```python
from lawsearch.models import SearchResult, SearchScope, SourceGroup  # extend existing import line


def test_search_result_defaults_match_context_to_none():
    result = SearchResult(
        uid="001498",
        source=SourceGroup.LAW,
        quality=__import__("lawsearch.models", fromlist=["MatchQuality"]).MatchQuality.EXACT,
        title="주차장법",
        category="법률",
        authority=None,
        region_name=None,
        promulgation_date=None,
        effective_date=None,
        is_current=True,
        official_url="https://www.law.go.kr/example",
        fetched_at=datetime(2026, 8, 11, tzinfo=UTC),
    )
    assert result.match_context is None
```

Prefer a clean import: change the top of `tests/test_models.py` from
`from lawsearch.models import SearchResponse, SourceState` to
`from lawsearch.models import MatchQuality, SearchResponse, SearchResult, SearchScope, SourceGroup, SourceState`
and write the test body with `quality=MatchQuality.EXACT` directly.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_models.py::test_search_result_defaults_match_context_to_none -q`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument` is not it; it fails on `AttributeError: 'SearchResult' object has no attribute 'match_context'`.

- [ ] **Step 3: Add the field**

In `src/lawsearch/models.py`, in the `SearchResult` dataclass, add after `scope: SearchScope = SearchScope.BODY`:

```python
    match_context: str | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_models.py -q`
Expected: PASS

- [ ] **Step 5: Extend the test factory**

In `tests/conftest.py`, update `result_factory`'s `make_result` signature and body:

```python
    def make_result(
        source: SourceGroup,
        *,
        uid: str | None = None,
        quality: MatchQuality = MatchQuality.EXACT,
        effective: str | None = "20260811",
        current: bool = True,
        title: str | None = None,
        scope: SearchScope = SearchScope.BODY,
        match_context: str | None = None,
    ) -> SearchResult:
```

and pass `scope=scope, match_context=match_context` into the `SearchResult(...)` call. Add `SearchScope` to the conftest import from `lawsearch.models`.

- [ ] **Step 6: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS (166 passed, 7 skipped)

- [ ] **Step 7: Commit**

```bash
git add src/lawsearch/models.py tests/test_models.py tests/conftest.py
git commit -m "feat: add optional match_context to SearchResult"
```

---

## Task 2: Service threads the first verified context into `match_context`

**Files:**
- Modify: `src/lawsearch/service.py:108-141` (`load_contexts`), `src/lawsearch/service.py:225-254` (`_verify_body_results`)
- Test: `tests/test_service.py`

**Interfaces:**
- Consumes: `SearchResult.match_context` (Task 1).
- Produces: `SearchService.load_contexts(self, result, keyword, refresh=False, *, limit=5) -> DetailResponse` (new keyword-only `limit`, forwarded to `extract_contexts`).
- Produces: after `SearchService.search(...)`, every result with `scope is SearchScope.BODY` has a non-empty `match_context`; every result with `scope is SearchScope.TITLE` has `match_context is None`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_service.py`, add:

```python
def test_body_verified_results_carry_their_first_exact_context(
    service_factory, parsed_plain
):
    service, _ = service_factory()

    response = run(service.search(parsed_plain))

    body_hits = [r for r in response.results if r.scope is SearchScope.BODY]
    assert body_hits
    assert all(r.match_context and " — " in r.match_context for r in body_hits)


def test_title_matched_results_keep_match_context_none(
    service_factory, parsed_plain, load_fixture
):
    title_payload = load_fixture("law-single.json")
    title_payload["LawSearch"]["law"]["법령명한글"] = "주차 단속법"
    service, _ = service_factory(
        responses={("laws_titles", "주차 단속"): title_payload}
    )

    response = run(service.search(parsed_plain))

    law = next(
        r for r in response.results
        if r.uid == "001498" and r.scope is SearchScope.TITLE
    )
    assert law.match_context is None


def test_load_contexts_limit_is_forwarded(service_factory, parsed_plain, result_factory):
    service, _ = service_factory()
    result = result_factory(SourceGroup.LAW, uid="001498")

    one = run(service.load_contexts(result, "주차", limit=1))

    assert len(one.contexts) <= 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_service.py -q -k "match_context or limit_is_forwarded"`
Expected: FAIL — `match_context` is `None` on body hits; `load_contexts()` rejects the `limit` keyword.

- [ ] **Step 3: Add `limit` to `load_contexts`**

In `src/lawsearch/service.py`, change the signature:

```python
    async def load_contexts(
        self,
        result: SearchResult,
        keyword: str,
        refresh: bool = False,
        *,
        limit: int = 5,
    ) -> DetailResponse:
```

and replace every `extract_contexts(<payload>, keyword)` call inside that method with `extract_contexts(<payload>, keyword, limit)` (three call sites: fresh-cache branch, stale-fallback branch, live branch).

- [ ] **Step 4: Thread the context in `_verify_body_results`**

In `src/lawsearch/service.py`, in the nested `verify` function, replace the tail (from `if not detail.contexts:` onward):

```python
            if not detail.contexts:
                return None, False
            context = detail.contexts[0]
            if result.scope is SearchScope.TITLE:
                return (
                    replace(result, scope=SearchScope.BODY, match_context=context),
                    state,
                ), False
            return (replace(result, match_context=context), state), False
```

Leave the earlier `if result.scope is SearchScope.TITLE and _title_matches_query(...)` fast-path unchanged — those keep `match_context = None`.

- [ ] **Step 5: Run the targeted tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_service.py -q`
Expected: PASS

- [ ] **Step 6: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS. Pay attention to `test_body_search_keeps_only_results_with_a_matching_article` and `test_body_verification_failure_never_exposes_unverified_results` — the `방화구획` regression guards must still pass.

- [ ] **Step 7: Commit**

```bash
git add src/lawsearch/service.py tests/test_service.py
git commit -m "feat: carry first verified context on body search results"
```

---

## Task 3: Create `lawsearch.viewmodels` and move pure logic out of `app.py`

Behavior-preserving refactor. No new behavior; the moved tests must pass unchanged except for their import line.

**Files:**
- Create: `src/lawsearch/viewmodels.py`
- Create: `tests/test_viewmodels.py`
- Modify: `src/lawsearch/app.py` (delete moved code, import from `viewmodels`)
- Modify: `tests/test_app.py` (delete moved tests)

**Interfaces:**
- Produces (all in `lawsearch.viewmodels`, identical signatures/behavior to today's `app.py`):
  - `ResultGroupView` (frozen dataclass: `label: str`, `results: tuple[SearchResult, ...]`, `state: SourceState`, `status_message: str`, `fetched_at: datetime | None`, `expanded: bool`)
  - `build_grouped_view(response: SearchResponse, region: Region | None = None) -> tuple[ResultGroupView, ...]`
  - `build_error_messages(response: SearchResponse) -> tuple[str, ...]`
  - `detail_session_key(source: SourceGroup, uid: str, keyword: str) -> str`
  - `fully_qualified_region_name(region: Region) -> str`
  - `is_official_url(value: str) -> bool`
  - `format_timestamp(value: datetime) -> str` (renamed from `_format_timestamp`, now public)
- Consumes in `app.py`: the same names, imported from `lawsearch.viewmodels`.

- [ ] **Step 1: Create the module by moving code**

Create `src/lawsearch/viewmodels.py`. Move from `src/lawsearch/app.py` **verbatim** (adjusting only what's noted):

- Imports needed: `from __future__ import annotations`, `hashlib`, `from dataclasses import dataclass`, `from datetime import datetime`, `from urllib.parse import urlsplit`, `from zoneinfo import ZoneInfo`, and from `lawsearch.models`: `Region, SearchResponse, SearchResult, SearchScope, SourceGroup, SourceState`.
- Constants: `_SEOUL`, `_SOURCE_ORDER`, `_SOURCE_KEYS`, `_DEFAULT_LABELS`, `_SOURCE_LABELS`, `_STATE_MESSAGES`.
- Functions/classes: `ResultGroupView`, `build_grouped_view`, `build_error_messages`, `detail_session_key`, `fully_qualified_region_name`, `is_official_url`, `_group_label`, `_empty_source_label`, `_status_message`.
- Rename `_format_timestamp` → `format_timestamp` (public) and update its one caller `_status_message`.

- [ ] **Step 2: Rewire `app.py`**

In `src/lawsearch/app.py`:
- Delete the moved constants, `ResultGroupView`, and the moved functions.
- Delete now-unused imports (`hashlib`, `urlsplit`, `ZoneInfo`, `dataclass` if unused elsewhere — `_render... ` uses none; keep `dataclass` only if still referenced).
- Add:
  ```python
  from lawsearch.viewmodels import (
      build_error_messages,
      build_grouped_view,
      detail_session_key,
      format_timestamp,
      fully_qualified_region_name,
      is_official_url,
  )
  ```
- Replace the two `_format_timestamp(` call sites in `_render_result` / `_render_response`-area with `format_timestamp(`.
- Keep `_PROJECT_ROOT`, `_run`, `_search`, `_contexts`, `_load_resources`, `_render_search_form`, `main`, `_handle_search`, `_apply_region_candidate`, `_clear_ambiguity`, `_clear_response`, `_perform_search`, `_render_response`, `_render_result` in `app.py` for now (they change in later tasks).

- [ ] **Step 3: Split the tests**

Create `tests/test_viewmodels.py`. Move these test functions **unchanged** from `tests/test_app.py`, and move the `make_response` helper they share:

- `make_response` (helper)
- `test_view_groups_keep_ranked_source_order`
- `test_provincial_group_label_uses_selected_province_not_result_authority`
- `test_stale_source_has_visible_retrieval_warning`
- `test_error_group_is_retained_without_raw_error_text`
- `test_empty_law_subgroups_are_not_rendered`
- `test_decree_only_response_does_not_invent_empty_law_group`
- `test_body_only_hits_are_kept_in_a_collapsed_additional_group`
- `test_all_title_match_groups_precede_any_body_only_group`
- `test_regional_body_results_stay_above_national_title_results`
- `test_empty_ordinance_labels_come_from_selected_region`
- `test_empty_ordinance_groups_keep_priority_before_national_results`
- `test_zero_result_stale_group_uses_source_retrieval_timestamp`
- `test_official_link_allows_only_https_law_go_kr_hosts`
- `test_region_label_is_fully_qualified`
- `test_detail_state_is_scoped_to_normalized_query_identity`
- `test_source_errors_are_named_and_diagnostics_are_redacted`

Header for `tests/test_viewmodels.py`:

```python
from dataclasses import replace
from datetime import UTC, datetime

from lawsearch.viewmodels import (
    build_error_messages,
    build_grouped_view,
    detail_session_key,
    fully_qualified_region_name,
    is_official_url,
)
from lawsearch.models import (
    SearchResponse,
    SearchScope,
    SourceError,
    SourceGroup,
    SourceState,
)
```

In `tests/test_app.py`, delete those 16 test functions and the `make_response` helper, and prune the now-unused imports (`build_error_messages`, `build_grouped_view`, `detail_session_key`, `fully_qualified_region_name`, `is_official_url`, `SearchScope`, `SourceError` if unused). Keep `import lawsearch.app as app` and `from lawsearch.models import ParsedQuery, SearchResponse, SourceGroup, SourceState` (check which are still referenced).

- [ ] **Step 4: Add the "no streamlit import" guard**

In `tests/test_viewmodels.py`:

```python
def test_viewmodels_module_does_not_import_streamlit():
    import sys
    import importlib

    sys.modules.pop("lawsearch.viewmodels", None)
    sys.modules.pop("streamlit", None)
    importlib.import_module("lawsearch.viewmodels")
    assert "streamlit" not in sys.modules
```

- [ ] **Step 5: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS, same count as before the split (166 passed, 7 skipped). If a moved test fails, the move was not verbatim — fix the module, not the test.

- [ ] **Step 6: Commit**

```bash
git add src/lawsearch/viewmodels.py src/lawsearch/app.py tests/test_viewmodels.py tests/test_app.py
git commit -m "refactor: extract pure presentation logic into lawsearch.viewmodels"
```

---

## Task 4: `result_key`, `CardView`, and `card_rows`

**Files:**
- Modify: `src/lawsearch/viewmodels.py`
- Test: `tests/test_viewmodels.py`

**Interfaces:**
- Consumes: `SearchResult` (with `match_context`, `scope`), `is_official_url`.
- Produces:
  - `result_key(result: SearchResult) -> str` → `f"{result.source.value}:{result.uid}"`
  - `CardView` (frozen dataclass): `key: str`, `title: str`, `match_kind: str` (`"제목 일치"` or `"본문 일치"`), `match_line: str | None`, `official_url: str | None`, `meta_fields: tuple[str, ...]`
  - `card_view(result: SearchResult) -> CardView`
  - `card_rows(results: Iterable[SearchResult], columns: int = 2) -> tuple[tuple[CardView, ...], ...]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_viewmodels.py`:

```python
from lawsearch.viewmodels import CardView, card_rows, card_view, result_key


def _result(result_factory, **kwargs):
    scope = kwargs.pop("scope", SearchScope.BODY)
    return replace(result_factory(kwargs.pop("source", SourceGroup.LAW), **kwargs), scope=scope)


def test_result_key_combines_source_and_uid(result_factory):
    assert result_key(result_factory(SourceGroup.LAW, uid="001498")) == "law:001498"


def test_card_view_exposes_verified_match_line(result_factory):
    result = replace(
        result_factory(SourceGroup.LAW, uid="004743", title="건축법 시행령"),
        scope=SearchScope.BODY,
        match_context="제46조(방화구획 등의 설치) — 주요구조부를 방화구획으로 구획한다",
    )

    card = card_view(result)

    assert card.key == "law:004743"
    assert card.match_kind == "본문 일치"
    assert card.match_line == "제46조(방화구획 등의 설치) — 주요구조부를 방화구획으로 구획한다"


def test_card_view_for_title_match_has_no_match_line(result_factory):
    card = card_view(replace(result_factory(SourceGroup.LAW), scope=SearchScope.TITLE))

    assert card.match_kind == "제목 일치"
    assert card.match_line is None


def test_card_view_meta_fields_include_currency_and_dates(result_factory):
    from datetime import date

    result = replace(
        result_factory(SourceGroup.DECREE, title="주차장법 시행령", current=False),
        promulgation_date=date(2025, 1, 2),
        effective_date=date(2025, 7, 1),
        authority="국토교통부",
    )

    card = card_view(result)

    assert card.meta_fields == (
        "decree",
        "국토교통부",
        "연혁",
        "공포 2025-01-02",
        "시행 2025-07-01",
    )


def test_card_view_drops_non_official_url(result_factory):
    result = replace(result_factory(SourceGroup.LAW), official_url="http://law.go.kr/x")

    assert card_view(result).official_url is None


def test_card_rows_batch_two_per_row_in_result_order(result_factory):
    results = tuple(result_factory(SourceGroup.LAW, uid=str(index)) for index in range(5))

    rows = card_rows(results, columns=2)

    assert [len(row) for row in rows] == [2, 2, 1]
    assert [[card.key for card in row] for row in rows] == [
        ["law:0", "law:1"],
        ["law:2", "law:3"],
        ["law:4"],
    ]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_viewmodels.py -q -k "card or result_key"`
Expected: FAIL — `ImportError` for `CardView`/`card_rows`/`card_view`/`result_key`.

- [ ] **Step 3: Implement**

Append to `src/lawsearch/viewmodels.py` (add `from collections.abc import Iterable` and `from lawsearch.models import ... SearchScope` if not already imported):

```python
def result_key(result: SearchResult) -> str:
    return f"{result.source.value}:{result.uid}"


@dataclass(frozen=True)
class CardView:
    key: str
    title: str
    match_kind: str
    match_line: str | None
    official_url: str | None
    meta_fields: tuple[str, ...]


def card_view(result: SearchResult) -> CardView:
    fields = [result.category]
    if result.authority:
        fields.append(result.authority)
    fields.append("현행" if result.is_current else "연혁")
    if result.promulgation_date:
        fields.append(f"공포 {result.promulgation_date.isoformat()}")
    if result.effective_date:
        fields.append(f"시행 {result.effective_date.isoformat()}")
    return CardView(
        key=result_key(result),
        title=result.title,
        match_kind="제목 일치" if result.scope is SearchScope.TITLE else "본문 일치",
        match_line=result.match_context,
        official_url=result.official_url if is_official_url(result.official_url) else None,
        meta_fields=tuple(fields),
    )


def card_rows(
    results: Iterable[SearchResult], columns: int = 2
) -> tuple[tuple[CardView, ...], ...]:
    cards = [card_view(result) for result in results]
    return tuple(
        tuple(cards[start : start + columns])
        for start in range(0, len(cards), columns)
    )
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_viewmodels.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/lawsearch/viewmodels.py tests/test_viewmodels.py
git commit -m "feat: add result_key, CardView, and card_rows view models"
```

---

## Task 5: `sidebar_sections`

**Files:**
- Modify: `src/lawsearch/viewmodels.py`
- Test: `tests/test_viewmodels.py`

**Interfaces:**
- Consumes: `SearchResponse.results` (already ranked by `SearchService`), `Region`, `_group_label`, `_DEFAULT_LABELS`, `result_key`.
- Produces:
  - `SidebarEntry` (frozen): `key: str`, `title: str`
  - `SidebarGroup` (frozen): `label: str`, `count: int`, `entries: tuple[SidebarEntry, ...]`
  - `SidebarSection` (frozen): `label: str` (`"자치법규"` or `"상위법령"`), `groups: tuple[SidebarGroup, ...]`
  - `sidebar_sections(response: SearchResponse, region: Region | None = None) -> tuple[SidebarSection, ...]`

Rules: only sources with ≥1 result appear. Section order: the section holding the first ranked result comes first. Within a section, group order and entry order follow `response.results`. Total entries across all sections equals `len(response.results)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_viewmodels.py`:

```python
from lawsearch.viewmodels import (
    SidebarEntry,
    SidebarGroup,
    SidebarSection,
    sidebar_sections,
)

_FETCHED = datetime(2026, 8, 11, tzinfo=UTC)


def _response(results, states):
    return SearchResponse(
        results=results,
        suggestions=(),
        errors=(),
        source_states=states,
        source_fetched_at={name: _FETCHED for name in states},
    )


def test_sidebar_sections_lead_with_local_law_when_region_selected(
    result_factory, pyeongtaek
):
    results = (
        replace(
            result_factory(SourceGroup.MUNICIPAL, uid="m1", title="평택시 주차장 조례"),
            scope=SearchScope.BODY,
        ),
        replace(
            result_factory(SourceGroup.LAW, uid="l1", title="주차장법"),
            scope=SearchScope.TITLE,
        ),
        replace(
            result_factory(SourceGroup.DECREE, uid="d1", title="주차장법 시행령"),
            scope=SearchScope.TITLE,
        ),
    )
    sections = sidebar_sections(
        _response(results, {"municipal": SourceState.LIVE, "laws": SourceState.LIVE}),
        pyeongtaek,
    )

    assert [section.label for section in sections] == ["자치법규", "상위법령"]
    national = sections[1]
    assert [(group.label, group.count) for group in national.groups] == [
        ("법률", 1),
        ("대통령령(시행령)", 1),
    ]
    assert national.groups[0].entries == (SidebarEntry("law:l1", "주차장법"),)


def test_sidebar_sections_lead_with_national_without_region(result_factory):
    results = (
        replace(
            result_factory(SourceGroup.LAW, uid="l1", title="주차장법"),
            scope=SearchScope.TITLE,
        ),
    )
    sections = sidebar_sections(_response(results, {"laws": SourceState.LIVE}))

    assert [section.label for section in sections] == ["상위법령"]


def test_sidebar_entry_count_equals_result_count(result_factory, pyeongtaek):
    results = (
        replace(result_factory(SourceGroup.MUNICIPAL, uid="m1"), scope=SearchScope.BODY),
        replace(result_factory(SourceGroup.PROVINCIAL, uid="p1"), scope=SearchScope.BODY),
        replace(result_factory(SourceGroup.LAW, uid="l1"), scope=SearchScope.TITLE),
        replace(result_factory(SourceGroup.LAW, uid="l2"), scope=SearchScope.BODY),
        replace(result_factory(SourceGroup.ADMIN_RULE, uid="a1"), scope=SearchScope.BODY),
    )
    sections = sidebar_sections(
        _response(
            results,
            {
                "municipal": SourceState.LIVE,
                "provincial": SourceState.LIVE,
                "laws": SourceState.LIVE,
                "admin_rules": SourceState.LIVE,
            },
        ),
        pyeongtaek,
    )

    total = sum(len(group.entries) for section in sections for group in section.groups)
    assert total == len(results)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_viewmodels.py -q -k sidebar`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement**

Append to `src/lawsearch/viewmodels.py`:

```python
_LOCAL_SOURCES = (SourceGroup.MUNICIPAL, SourceGroup.PROVINCIAL)
_NATIONAL_SOURCES = (
    SourceGroup.LAW,
    SourceGroup.DECREE,
    SourceGroup.MINISTERIAL_RULE,
    SourceGroup.ADMIN_RULE,
    SourceGroup.OTHER,
)
_SIDEBAR_GROUP_LABELS = {
    SourceGroup.LAW: "법률",
    SourceGroup.DECREE: "대통령령(시행령)",
    SourceGroup.MINISTERIAL_RULE: "총리령·부령(시행규칙)",
    SourceGroup.ADMIN_RULE: "행정규칙",
    SourceGroup.OTHER: "기타 법령",
}


@dataclass(frozen=True)
class SidebarEntry:
    key: str
    title: str


@dataclass(frozen=True)
class SidebarGroup:
    label: str
    count: int
    entries: tuple[SidebarEntry, ...]


@dataclass(frozen=True)
class SidebarSection:
    label: str
    groups: tuple[SidebarGroup, ...]


def sidebar_sections(
    response: SearchResponse, region: Region | None = None
) -> tuple[SidebarSection, ...]:
    order = {source: index for index, source in enumerate(response.results)}

    def section_for(source: SourceGroup) -> str:
        return "자치법규" if source in _LOCAL_SOURCES else "상위법령"

    buckets: dict[str, dict[SourceGroup, list[SearchResult]]] = {}
    first_rank: dict[str, int] = {}
    for rank, result in enumerate(response.results):
        section = section_for(result.source)
        buckets.setdefault(section, {}).setdefault(result.source, []).append(result)
        first_rank.setdefault(section, rank)

    def group_label(source: SourceGroup, items: list[SearchResult]) -> str:
        if source in _LOCAL_SOURCES:
            return _group_label(source, tuple(items), region)
        return _SIDEBAR_GROUP_LABELS[source]

    sections: list[SidebarSection] = []
    for section_label in sorted(buckets, key=lambda name: first_rank[name]):
        by_source = buckets[section_label]
        ordered_sources = sorted(
            by_source, key=lambda source: min(response.results.index(item) for item in by_source[source])
        )
        groups = tuple(
            SidebarGroup(
                label=group_label(source, by_source[source]),
                count=len(by_source[source]),
                entries=tuple(
                    SidebarEntry(result_key(item), item.title) for item in by_source[source]
                ),
            )
            for source in ordered_sources
        )
        sections.append(SidebarSection(section_label, groups))
    return tuple(sections)
```

Note: `order` is unused — remove it; keep `response.results.index(...)` for source ordering. (Left here only to flag: do not ship dead code — the implementer must delete the `order = ...` line.)

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_viewmodels.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/lawsearch/viewmodels.py tests/test_viewmodels.py
git commit -m "feat: add sidebar_sections navigation view model"
```

---

## Task 6: `compare_options`

**Files:**
- Modify: `src/lawsearch/viewmodels.py`
- Test: `tests/test_viewmodels.py`

**Interfaces:**
- Consumes: `SearchResponse.results`, `_DEFAULT_LABELS`, `result_key`.
- Produces:
  - `CompareOption` (frozen): `key: str`, `label: str`
  - `compare_options(response: SearchResponse) -> tuple[CompareOption, ...]` — one option per result, in ranked order, any source. Label: `f"{_DEFAULT_LABELS[result.source]} · {result.title}"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_viewmodels.py`:

```python
from lawsearch.viewmodels import CompareOption, compare_options


def test_compare_options_cover_every_result_in_ranked_order(result_factory):
    results = (
        replace(
            result_factory(SourceGroup.LAW, uid="l1", title="주차장법"),
            scope=SearchScope.TITLE,
        ),
        replace(
            result_factory(SourceGroup.MUNICIPAL, uid="m1", title="평택시 주차장 조례"),
            scope=SearchScope.BODY,
        ),
    )
    options = compare_options(_response(results, {"laws": SourceState.LIVE, "municipal": SourceState.LIVE}))

    assert options == (
        CompareOption("law:l1", "법률 · 주차장법"),
        CompareOption("municipal:m1", "기초지자체 자치법규 · 평택시 주차장 조례"),
    )


def test_compare_options_allow_the_same_source_on_both_sides(result_factory):
    results = tuple(
        replace(
            result_factory(SourceGroup.LAW, uid=f"l{index}", title=f"법령 {index}"),
            scope=SearchScope.TITLE,
        )
        for index in range(2)
    )
    options = compare_options(_response(results, {"laws": SourceState.LIVE}))

    assert {option.key for option in options} == {"law:l0", "law:l1"}
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_viewmodels.py -q -k compare`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement**

Append to `src/lawsearch/viewmodels.py`:

```python
@dataclass(frozen=True)
class CompareOption:
    key: str
    label: str


def compare_options(response: SearchResponse) -> tuple[CompareOption, ...]:
    return tuple(
        CompareOption(
            key=result_key(result),
            label=f"{_DEFAULT_LABELS[result.source]} · {result.title}",
        )
        for result in response.results
    )
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_viewmodels.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/lawsearch/viewmodels.py tests/test_viewmodels.py
git commit -m "feat: add compare_options view model"
```

---

## Task 7: `view_mode` state machine and workspace reset

**Files:**
- Modify: `src/lawsearch/app.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Produces (in `lawsearch.app`):
  - `_VIEW_RESULTS = "results"`, `_VIEW_PREVIEW = "preview"`, `_VIEW_COMPARE = "compare"`
  - `_view_mode(st) -> str` (defaults to `_VIEW_RESULTS`)
  - `_reset_workspace(st) -> None` — pops `view_mode`, `selected_result_key`, `compare_left_result_key`, `compare_right_result_key`, `compare_left_article`, `compare_right_article`
  - `_clear_detail_state(st) -> None` — pops every `st.session_state` key that is a `str` starting with `"detail-"`
  - `_open_preview(st, key: str) -> None` — sets `view_mode=preview`, `selected_result_key=key`
  - `_open_results(st) -> None` — sets `view_mode=results`, pops `selected_result_key`
  - `_open_compare(st) -> None` — sets `view_mode=compare`
- Consumes: `_clear_response` calls `_reset_workspace` and `_clear_detail_state`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_app.py`, add (the file already has `ControllerStub`, `SessionState`, `nullcontext`, `ParsedQuery`):

```python
def test_open_preview_sets_mode_and_selection():
    streamlit = ControllerStub()

    app._open_preview(streamlit, "law:001498")

    assert streamlit.session_state["view_mode"] == "preview"
    assert streamlit.session_state["selected_result_key"] == "law:001498"


def test_open_results_clears_selection():
    streamlit = ControllerStub(
        {"view_mode": "preview", "selected_result_key": "law:1"}
    )

    app._open_results(streamlit)

    assert streamlit.session_state["view_mode"] == "results"
    assert "selected_result_key" not in streamlit.session_state


def test_view_mode_defaults_to_results():
    assert app._view_mode(ControllerStub()) == "results"


def test_new_search_resets_workspace_and_detail_state(monkeypatch):
    streamlit = ControllerStub(
        {
            "view_mode": "compare",
            "selected_result_key": "law:1",
            "compare_left_result_key": "law:2",
            "detail-law-1-0123456789abcdef": object(),
        }
    )
    streamlit.spinner = lambda message: nullcontext()

    async def fake_search(settings, parsed, refresh):
        return object()

    monkeypatch.setattr(app, "_search", fake_search)

    app._perform_search(streamlit, object(), ParsedQuery("주차장"), refresh=False)

    for key in (
        "view_mode",
        "selected_result_key",
        "compare_left_result_key",
    ):
        assert key not in streamlit.session_state
    assert not any(
        isinstance(key, str) and key.startswith("detail-")
        for key in streamlit.session_state
    )
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_app.py -q -k "open_preview or open_results or view_mode or resets_workspace"`
Expected: FAIL — `AttributeError` on `app._open_preview` etc.

- [ ] **Step 3: Implement**

In `src/lawsearch/app.py`, add near the top (after imports):

```python
_VIEW_RESULTS = "results"
_VIEW_PREVIEW = "preview"
_VIEW_COMPARE = "compare"
_WORKSPACE_KEYS = (
    "view_mode",
    "selected_result_key",
    "compare_left_result_key",
    "compare_right_result_key",
    "compare_left_article",
    "compare_right_article",
)


def _view_mode(st: Any) -> str:
    return st.session_state.get("view_mode", _VIEW_RESULTS)


def _reset_workspace(st: Any) -> None:
    for key in _WORKSPACE_KEYS:
        st.session_state.pop(key, None)


def _clear_detail_state(st: Any) -> None:
    stale = [
        key
        for key in list(st.session_state)
        if isinstance(key, str) and key.startswith("detail-")
    ]
    for key in stale:
        st.session_state.pop(key, None)


def _open_preview(st: Any, key: str) -> None:
    st.session_state.view_mode = _VIEW_PREVIEW
    st.session_state.selected_result_key = key


def _open_results(st: Any) -> None:
    st.session_state.view_mode = _VIEW_RESULTS
    st.session_state.pop("selected_result_key", None)


def _open_compare(st: Any) -> None:
    st.session_state.view_mode = _VIEW_COMPARE
```

Update `_clear_response`:

```python
def _clear_response(st: Any) -> None:
    st.session_state.pop("response", None)
    st.session_state.pop("parsed_query", None)
    _reset_workspace(st)
    _clear_detail_state(st)
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_app.py -q`
Expected: PASS (existing `test_ui_error_never_exposes_exception_text`, `test_refresh_forwards_saved_query_and_refresh_flag`, `test_plain_query_does_not_inherit_previous_region` still pass.)

- [ ] **Step 5: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/lawsearch/app.py tests/test_app.py
git commit -m "feat: add view_mode state machine and workspace reset"
```

---

## Task 8: Content-width layout, top bar with mode toggle, and 2-column results view

**Files:**
- Create: `tests/streamlit_stub.py`
- Modify: `src/lawsearch/app.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `card_rows`, `build_grouped_view`, `build_error_messages`, `format_timestamp`, `is_official_url`, `_open_preview`, `_open_compare`, `_open_results`, `_view_mode`.
- Produces:
  - `FakeStreamlit` in `tests/streamlit_stub.py` (see Step 1)
  - `_CONTENT_MAX_WIDTH_PX = 1100`
  - `_inject_layout_css(st) -> None`
  - `_render_top_bar(st) -> None` — service name, examples caption, compact source/legal lines, `기본 보기`/`비교하기` toggle (rendered only when `"response" in st.session_state`)
  - `_render_results(st, settings, response, parsed) -> None` — suggestions caption, error messages, then per `build_grouped_view` group: a `st.subheader(f"{group.label} ({len(group.results)})")`, a status line, and `card_rows(group.results, columns=2)` rendered as `st.columns(2)` rows
  - `_render_card(st, card, keyword) -> None`
- `main()` calls `_inject_layout_css`, `_render_top_bar`, then dispatches: `_view_mode(st) == "compare"` → (compare, Task 11) else → `_render_results`. Preview branch added in Task 10. Until those tasks land, non-results modes fall through to `_render_results`.

- [ ] **Step 1: Create the Streamlit stub**

Create `tests/streamlit_stub.py`:

```python
"""Minimal recording stub for the Streamlit surface the app renders with."""

from __future__ import annotations

from contextlib import contextmanager


class SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as error:
            raise AttributeError(name) from error

    def __setattr__(self, name, value):
        self[name] = value


class FakeStreamlit:
    def __init__(self, session_state=None, *, buttons=None, selections=None):
        self.session_state = SessionState(session_state or {})
        self.calls: list[tuple[str, tuple, dict]] = []
        self.reruns = 0
        self._buttons = dict(buttons or {})
        self._selections = dict(selections or {})

    # recording helpers -------------------------------------------------
    def _record(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))

    def names(self) -> list[str]:
        return [name for name, _, _ in self.calls]

    # passive widgets -------------------------------------------------
    def markdown(self, *a, **k): self._record("markdown", *a, **k)
    def caption(self, *a, **k): self._record("caption", *a, **k)
    def subheader(self, *a, **k): self._record("subheader", *a, **k)
    def title(self, *a, **k): self._record("title", *a, **k)
    def write(self, *a, **k): self._record("write", *a, **k)
    def info(self, *a, **k): self._record("info", *a, **k)
    def warning(self, *a, **k): self._record("warning", *a, **k)
    def error(self, *a, **k): self._record("error", *a, **k)
    def divider(self, *a, **k): self._record("divider", *a, **k)
    def link_button(self, label, url, *a, **k): self._record("link_button", label, url, *a, **k)
    def set_page_config(self, *a, **k): self._record("set_page_config", *a, **k)

    # active widgets -------------------------------------------------
    def button(self, label, *a, **k):
        self._record("button", label, *a, **k)
        return bool(self._buttons.get(k.get("key", label), False))

    def form_submit_button(self, label, *a, **k):
        self._record("form_submit_button", label, *a, **k)
        return bool(self._buttons.get(label, False))

    def radio(self, label, options, *a, **k):
        self._record("radio", label, options, *a, **k)
        options = list(options)
        chosen = self._selections.get(k.get("key", label), options[0] if options else None)
        return chosen

    def selectbox(self, label, options, *a, **k):
        self._record("selectbox", label, options, *a, **k)
        options = list(options)
        return self._selections.get(k.get("key", label), options[0] if options else None)

    def text_input(self, *a, **k):
        self._record("text_input", *a, **k)
        return self._selections.get("text_input", "")

    def rerun(self):
        self.reruns += 1
        raise _Rerun()

    # layout -------------------------------------------------
    def columns(self, spec, *a, **k):
        self._record("columns", spec, *a, **k)
        count = spec if isinstance(spec, int) else len(spec)
        return [FakeStreamlit._Child(self) for _ in range(count)]

    @contextmanager
    def container(self, *a, **k):
        self._record("container", *a, **k)
        yield self

    @contextmanager
    def expander(self, label, *a, **k):
        self._record("expander", label, *a, **k)
        yield self

    @contextmanager
    def form(self, *a, **k):
        self._record("form", *a, **k)
        yield self

    @contextmanager
    def spinner(self, *a, **k):
        self._record("spinner", *a, **k)
        yield self

    @property
    def sidebar(self):
        child = FakeStreamlit._Child(self)
        self._record("sidebar", )
        return child

    class _Child:
        def __init__(self, parent):
            self._parent = parent

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def __getattr__(self, name):
            return getattr(self._parent, name)


class _Rerun(RuntimeError):
    pass
```

- [ ] **Step 2: Write the failing tests**

In `tests/test_app.py`:

```python
import pytest

from tests.streamlit_stub import FakeStreamlit, _Rerun
from lawsearch.viewmodels import build_grouped_view  # for assertions
from lawsearch.models import SearchResponse, SearchScope, SourceGroup, SourceState


def _fetched():
    return datetime(2026, 8, 11, tzinfo=UTC)


def _four_result_response(result_factory):
    results = tuple(
        replace(
            result_factory(source, uid=f"{source.value}-1", title=f"{source.value} 규정"),
            scope=SearchScope.BODY,
            match_context=f"제1조 — {source.value}",
        )
        for source in (SourceGroup.LAW, SourceGroup.DECREE, SourceGroup.ADMIN_RULE)
    )
    return SearchResponse(
        results=results,
        suggestions=(),
        errors=(),
        source_states={"laws": SourceState.LIVE, "admin_rules": SourceState.LIVE},
        source_fetched_at={"laws": _fetched(), "admin_rules": _fetched()},
    )


def test_results_view_lays_out_cards_two_per_row(result_factory):
    streamlit = FakeStreamlit()
    response = _four_result_response(result_factory)

    app._render_results(streamlit, object(), response, ParsedQuery("주차장"))

    column_calls = [args for name, args, _ in streamlit.calls if name == "columns"]
    assert (2,) in column_calls or 2 in [c[0] for c in column_calls]


def test_results_card_preview_button_opens_preview(result_factory):
    response = _four_result_response(result_factory)
    first_key = response.results[0].source.value + ":" + response.results[0].uid
    streamlit = FakeStreamlit(buttons={f"preview-{first_key}": True})

    with pytest.raises(_Rerun):
        app._render_results(streamlit, object(), response, ParsedQuery("주차장"))

    assert streamlit.session_state["view_mode"] == "preview"
    assert streamlit.session_state["selected_result_key"] == first_key


def test_results_card_hides_button_for_non_official_url(result_factory):
    bad = replace(
        result_factory(SourceGroup.LAW, uid="l1", title="주차장법"),
        scope=SearchScope.BODY,
        official_url="http://law.go.kr/x",
        match_context="제1조 — x",
    )
    response = SearchResponse(
        results=(bad,),
        suggestions=(),
        errors=(),
        source_states={"laws": SourceState.LIVE},
        source_fetched_at={"laws": _fetched()},
    )
    streamlit = FakeStreamlit()

    app._render_results(streamlit, object(), response, ParsedQuery("주차장"))

    assert "link_button" not in streamlit.names()
```

Note: because `tests/streamlit_stub.py` is imported as `tests.streamlit_stub`, ensure `tests/__init__.py` exists (it does not today — create an empty one) OR import as `from streamlit_stub import ...` relying on rootdir/conftest already adding `tests/` to `sys.path` (it does: `test_service.py` does `from conftest import FakeApi`). **Use `from streamlit_stub import FakeStreamlit, _Rerun`** to match the existing `from conftest import ...` convention — do not add `tests/__init__.py`.

- [ ] **Step 3: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_app.py -q -k "results_view or results_card"`
Expected: FAIL — `AttributeError: module 'lawsearch.app' has no attribute '_render_results'`.

- [ ] **Step 4: Implement layout + top bar + results view**

In `src/lawsearch/app.py`:

```python
_CONTENT_MAX_WIDTH_PX = 1100


def _inject_layout_css(st: Any) -> None:
    st.markdown(
        f"<style>.block-container{{max-width:{_CONTENT_MAX_WIDTH_PX}px;}}</style>",
        unsafe_allow_html=True,
    )


def _render_top_bar(st: Any) -> None:
    st.title("대한민국 법령 통합검색")
    st.caption("예: `주차장법`, `@평택 주차장`, `@경기/평택 주차장`")
    st.caption("출처: 국가법령정보센터 · 참고자료이며 최종 확인은 공식 원문 및 소관기관 기준")
    if "response" not in st.session_state:
        return
    mode = _view_mode(st)
    results_col, compare_col = st.columns(2)
    if results_col.button("기본 보기", disabled=mode == _VIEW_RESULTS, width="stretch"):
        _open_results(st)
        st.rerun()
    if compare_col.button("비교하기", disabled=mode == _VIEW_COMPARE, width="stretch"):
        _open_compare(st)
        st.rerun()


def _render_results(
    st: Any, settings: Settings, response: SearchResponse, parsed: ParsedQuery
) -> None:
    if response.suggestions:
        st.caption("연관 검색어: " + ", ".join(response.suggestions))
    for message in build_error_messages(response):
        st.error(message)
    for group in build_grouped_view(response, parsed.region):
        st.subheader(f"{group.label} ({len(group.results)})")
        if group.state is SourceState.STALE_FALLBACK:
            st.warning(group.status_message)
        elif group.state is SourceState.ERROR:
            st.error(group.status_message)
            st.caption("위의 새로고침 버튼으로 이 출처를 다시 조회할 수 있습니다.")
        else:
            st.caption(group.status_message)
        for row in card_rows(group.results, columns=2):
            columns = st.columns(2)
            for column, card in zip(columns, row):
                with column:
                    _render_card(st, card, parsed.keyword)


def _render_card(st: Any, card: "CardView", keyword: str) -> None:
    with st.container(border=True):
        st.markdown(f"**{card.title}**")
        st.caption(" · ".join(card.meta_fields))
        st.caption(card.match_kind)
        if card.match_line:
            st.markdown(f"> {card.match_line}")
        preview_col, official_col = st.columns(2)
        if preview_col.button("미리보기", key=f"preview-{card.key}", width="stretch"):
            _open_preview(st, card.key)
            st.rerun()
        if card.official_url:
            official_col.link_button("공식 원문", card.official_url, width="stretch")
```

Add the import: `from lawsearch.viewmodels import CardView, card_rows` (and keep the Task 3 import block; merge). Import `Settings` is already present.

Rewrite `main()` to use the new structure:

```python
def main() -> None:
    import streamlit as st

    st.set_page_config(
        page_title="대한민국 법령 통합검색", page_icon="⚖️", layout="wide"
    )
    _inject_layout_css(st)
    _render_top_bar(st)

    try:
        settings, registry = _load_resources(st)
    except ConfigError:
        st.error("로컬 설정을 읽지 못했습니다. config.local.toml을 확인해 주세요.")
        return

    selected = st.session_state.get("selected_region")
    if selected is not None:
        chip, clear = st.columns([5, 1])
        chip.markdown(f"**선택 지역:** `{fully_qualified_region_name(selected)}`")
        if clear.button("지역 지우기"):
            st.session_state.pop("selected_region", None)
            _clear_response(st)
            st.rerun()

    raw, search_clicked = _render_search_form(st)
    refresh_clicked = (
        st.button("공식 API에서 새로고침") if "response" in st.session_state else False
    )

    if search_clicked:
        _handle_search(st, raw, registry, settings, refresh=False)
    if refresh_clicked:
        saved = st.session_state.get("parsed_query")
        if saved is not None:
            _perform_search(st, settings, saved, refresh=True)

    candidates = st.session_state.get("region_candidates", ())
    if candidates:
        choices = {fully_qualified_region_name(item): item for item in candidates}
        choice = st.selectbox("지역을 정확히 선택하세요", tuple(choices))
        if st.button("선택 적용"):
            _apply_region_candidate(
                st, settings, st.session_state.pending_keyword, choices[choice]
            )

    response = st.session_state.get("response")
    if response is None:
        return
    parsed = st.session_state["parsed_query"]
    with st.sidebar:
        _render_sidebar(st, response, parsed)
    mode = _view_mode(st)
    if mode == _VIEW_PREVIEW:
        _render_preview(st, settings, response, parsed)
    elif mode == _VIEW_COMPARE:
        _render_compare(st, settings, response, parsed)
    else:
        _render_results(st, settings, response, parsed)
```

Because `_render_sidebar`, `_render_preview`, `_render_compare` do not exist until Tasks 9–11, add **temporary stubs** now so `main()` imports cleanly, and delete them as each task lands:

```python
def _render_sidebar(st: Any, response: SearchResponse, parsed: ParsedQuery) -> None:
    return None


def _render_preview(st, settings, response, parsed) -> None:
    _render_results(st, settings, response, parsed)


def _render_compare(st, settings, response, parsed) -> None:
    _render_results(st, settings, response, parsed)
```

Delete the old `_render_response` function and its call site (its behavior is now split across `_render_results` + later `_render_preview`). Delete the old `_render_result` (superseded by `_render_card` + Task 10 preview). Keep `_contexts`, `_run`, `_search`.

- [ ] **Step 5: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_app.py tests/test_viewmodels.py -q`
Expected: PASS

- [ ] **Step 6: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS

- [ ] **Step 7: Manual smoke (optional but recommended)**

If a local `config.local.toml` with a valid key file is present:
`.venv/Scripts/python.exe -m streamlit run src/lawsearch/app.py --server.address 127.0.0.1 --server.headless true`
Search `주차장법`; confirm 2-column cards under width-limited layout; Ctrl+C to stop. Do not commit any cache or config.

- [ ] **Step 8: Commit**

```bash
git add src/lawsearch/app.py tests/test_app.py tests/streamlit_stub.py
git commit -m "feat: render results as width-limited two-column cards"
```

---

## Task 9: Sidebar navigation

**Files:**
- Modify: `src/lawsearch/app.py` (replace the `_render_sidebar` stub)
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `sidebar_sections`, `_open_preview`.
- Produces: `_render_sidebar(st, response, parsed) -> None` — for each `SidebarSection`: `st.subheader(section.label)`; for each `SidebarGroup`: an `st.expander(f"{group.label} ({group.count})")` containing one `st.button` per `SidebarEntry` (`key=f"nav-{entry.key}"`). A button click calls `_open_preview(st, entry.key)` then `st.rerun()`. No API calls.

- [ ] **Step 1: Write the failing tests**

```python
def test_sidebar_lists_every_result_as_a_nav_button(result_factory, pyeongtaek):
    response = _four_result_response(result_factory)
    streamlit = FakeStreamlit(session_state={"response": response})

    app._render_sidebar(streamlit, response, ParsedQuery("주차장"))

    nav_buttons = [
        kwargs.get("key")
        for name, args, kwargs in streamlit.calls
        if name == "button" and str(kwargs.get("key", "")).startswith("nav-")
    ]
    assert len(nav_buttons) == len(response.results)


def test_sidebar_click_opens_preview_without_search(monkeypatch, result_factory):
    response = _four_result_response(result_factory)
    target = response.results[1]
    key = f"{target.source.value}:{target.uid}"
    streamlit = FakeStreamlit(buttons={f"nav-{key}": True})

    def forbidden(*a, **k):
        raise AssertionError("sidebar navigation must not call an API")

    monkeypatch.setattr(app, "_run", forbidden)

    with pytest.raises(_Rerun):
        app._render_sidebar(streamlit, response, ParsedQuery("주차장"))

    assert streamlit.session_state["view_mode"] == "preview"
    assert streamlit.session_state["selected_result_key"] == key
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_app.py -q -k sidebar`
Expected: FAIL — the stub `_render_sidebar` renders nothing, so no `nav-` buttons / no rerun.

- [ ] **Step 3: Implement**

Replace the `_render_sidebar` stub in `src/lawsearch/app.py`:

```python
def _render_sidebar(
    st: Any, response: SearchResponse, parsed: ParsedQuery
) -> None:
    for section in sidebar_sections(response, parsed.region):
        st.subheader(section.label)
        for group in section.groups:
            with st.expander(f"{group.label} ({group.count})"):
                for entry in group.entries:
                    if st.button(entry.title, key=f"nav-{entry.key}", width="stretch"):
                        _open_preview(st, entry.key)
                        st.rerun()
```

Add `sidebar_sections` to the `from lawsearch.viewmodels import ...` block.

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_app.py -q`
Expected: PASS

- [ ] **Step 5: Full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/lawsearch/app.py tests/test_app.py
git commit -m "feat: add result-navigation sidebar"
```

---

## Task 10: Single-document preview with lazy loading

**Files:**
- Modify: `src/lawsearch/app.py` (replace the `_render_preview` stub; add `_contexts` `limit`, `_find_result`, `_preview_detail`)
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `detail_session_key`, `format_timestamp`, `is_official_url`, `SearchService.load_contexts(..., limit=...)` (Task 2), `_open_results`, `_view_mode`.
- Produces:
  - `_PREVIEW_CONTEXT_LIMIT = 20`
  - `_contexts(settings, result, keyword, *, refresh=False, limit=5)` — pass `limit` through to `service.load_contexts`
  - `_find_result(response, key) -> SearchResult | None`
  - `_preview_detail(st, settings, result, keyword) -> DetailResponse | None` — returns the session-cached `DetailResponse` if present; otherwise calls `_run(_contexts(..., limit=_PREVIEW_CONTEXT_LIMIT))`, stores it under `detail_session_key`, and returns it; on exception shows `st.error` and returns `None`
  - `_render_preview(st, settings, response, parsed) -> None`

- [ ] **Step 1: Write the failing tests**

```python
from lawsearch.models import DetailResponse


def _preview_response(result_factory, *, scope, match_context=None):
    result = replace(
        result_factory(SourceGroup.LAW, uid="001498", title="주차장법"),
        scope=scope,
        match_context=match_context,
    )
    return result, SearchResponse(
        results=(result,),
        suggestions=(),
        errors=(),
        source_states={"laws": SourceState.LIVE},
        source_fetched_at={"laws": _fetched()},
    )


def test_preview_reuses_session_detail_without_calling_api(monkeypatch, result_factory):
    result, response = _preview_response(
        result_factory, scope=SearchScope.BODY, match_context="제2조 — 주차 대수"
    )
    key = f"law:{result.uid}"
    detail = DetailResponse(("제2조(주차 대수) — 시설별 주차 대수",), SourceState.FRESH_CACHE, _fetched())
    session_key = app.detail_session_key(result.source, result.uid, "주차 대수")
    streamlit = FakeStreamlit(
        session_state={
            "response": response,
            "view_mode": "preview",
            "selected_result_key": key,
            session_key: detail,
        }
    )

    def forbidden(*a, **k):
        raise AssertionError("preview reused cache but still called an API")

    monkeypatch.setattr(app, "_run", forbidden)

    app._render_preview(streamlit, object(), response, ParsedQuery("주차 대수"))

    joined = " ".join(str(a) for name, args, _ in streamlit.calls for a in args)
    assert "제2조(주차 대수)" in joined
    assert "정확히 일치하는 조문 1건" in joined


def test_preview_lazy_loads_title_match_once(monkeypatch, result_factory):
    result, response = _preview_response(result_factory, scope=SearchScope.TITLE)
    key = f"law:{result.uid}"
    streamlit = FakeStreamlit(
        session_state={
            "response": response,
            "view_mode": "preview",
            "selected_result_key": key,
        }
    )
    calls = []

    def fake_run(awaitable):
        awaitable.close()
        calls.append(True)
        return DetailResponse(("제1조(목적) — 주차장의 설치",), SourceState.LIVE, _fetched())

    monkeypatch.setattr(app, "_run", fake_run)

    app._render_preview(streamlit, object(), response, ParsedQuery("주차장"))

    assert calls == [True]
    session_key = app.detail_session_key(result.source, result.uid, "주차장")
    assert session_key in streamlit.session_state


def test_preview_back_button_returns_to_results_without_api(monkeypatch, result_factory):
    result, response = _preview_response(result_factory, scope=SearchScope.BODY, match_context="x")
    key = f"law:{result.uid}"
    streamlit = FakeStreamlit(
        session_state={"response": response, "view_mode": "preview", "selected_result_key": key},
        buttons={"preview-back": True},
    )

    monkeypatch.setattr(app, "_run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("api call")))

    with pytest.raises(_Rerun):
        app._render_preview(streamlit, object(), response, ParsedQuery("주차장"))

    assert streamlit.session_state["view_mode"] == "results"
    assert "selected_result_key" not in streamlit.session_state


def test_preview_without_exact_context_does_not_show_arbitrary_text(monkeypatch, result_factory):
    result, response = _preview_response(result_factory, scope=SearchScope.TITLE)
    key = f"law:{result.uid}"
    streamlit = FakeStreamlit(
        session_state={"response": response, "view_mode": "preview", "selected_result_key": key}
    )
    monkeypatch.setattr(
        app, "_run",
        lambda awaitable: (awaitable.close(), DetailResponse((), SourceState.EMPTY, _fetched()))[1],
    )

    app._render_preview(streamlit, object(), response, ParsedQuery("주차장"))

    joined = " ".join(str(a) for name, args, _ in streamlit.calls for a in args)
    assert "정확히 일치하는 조문이 없습니다" in joined
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_app.py -q -k preview`
Expected: FAIL — the stub `_render_preview` forwards to `_render_results`; assertions about preview text / back button fail.

- [ ] **Step 3: Implement**

In `src/lawsearch/app.py`, update `_contexts`:

```python
async def _contexts(
    settings: Settings,
    result: SearchResult,
    keyword: str,
    *,
    refresh: bool = False,
    limit: int = 5,
):
    async with LawApiClient(load_api_key(settings.api_key_file)) as api:
        service = SearchService(
            api, CacheStore(settings.cache_path), lambda: datetime.now(UTC)
        )
        return await service.load_contexts(result, keyword, refresh=refresh, limit=limit)
```

Add:

```python
_PREVIEW_CONTEXT_LIMIT = 20


def _find_result(response: SearchResponse, key: str | None) -> SearchResult | None:
    if key is None:
        return None
    for result in response.results:
        if f"{result.source.value}:{result.uid}" == key:
            return result
    return None


def _preview_detail(
    st: Any, settings: Settings, result: SearchResult, keyword: str
):
    session_key = detail_session_key(result.source, result.uid, keyword)
    cached = st.session_state.get(session_key)
    if cached is not None:
        return cached
    try:
        detail = _run(
            _contexts(settings, result, keyword, limit=_PREVIEW_CONTEXT_LIMIT)
        )
    except Exception:
        st.error("본문을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.")
        return None
    st.session_state[session_key] = detail
    return detail


def _render_preview(
    st: Any, settings: Settings, response: SearchResponse, parsed: ParsedQuery
) -> None:
    result = _find_result(response, st.session_state.get("selected_result_key"))
    if result is None:
        _open_results(st)
        st.rerun()
        return
    if st.button("← 검색 결과로 돌아가기", key="preview-back"):
        _open_results(st)
        st.rerun()
    st.markdown(f"### {result.title}")
    meta = [result.category]
    if result.authority:
        meta.append(result.authority)
    meta.append("현행" if result.is_current else "연혁")
    if result.effective_date:
        meta.append(f"시행 {result.effective_date.isoformat()}")
    st.caption(" · ".join(meta))
    if is_official_url(result.official_url):
        st.link_button("공식 원문 열기", result.official_url)

    detail = _preview_detail(st, settings, result, parsed.keyword)
    if detail is None:
        return
    if detail.state is SourceState.ERROR:
        st.error("본문을 불러오지 못했습니다.")
        return
    if not detail.contexts:
        st.caption("검색어와 정확히 일치하는 조문이 없습니다.")
        return
    if detail.state is SourceState.STALE_FALLBACK:
        st.warning(
            f"이전 본문 결과 · 조회 시각 {format_timestamp(detail.fetched_at)}"
        )
    st.caption(f"정확히 일치하는 조문 {len(detail.contexts)}건")
    if len(detail.contexts) > 1:
        labels = [context.split(" — ", 1)[0] for context in detail.contexts]
        index = st.radio(
            "조문 선택",
            range(len(detail.contexts)),
            format_func=lambda position: labels[position],
            key="preview-article",
        )
    else:
        index = 0
    st.markdown(f"> {detail.contexts[index]}")
```

Delete the temporary `_render_preview` stub.

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_app.py tests/test_service.py -q`
Expected: PASS

- [ ] **Step 5: Full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/lawsearch/app.py tests/test_app.py
git commit -m "feat: add lazy-loading single-document preview"
```

---

## Task 11: Side-by-side compare view

**Files:**
- Modify: `src/lawsearch/app.py` (replace the `_render_compare` stub)
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `compare_options`, `_find_result`, `_preview_detail`, `is_official_url`.
- Produces: `_render_compare(st, settings, response, parsed) -> None`
  - If `len(compare_options(response)) < 2`: `st.info("비교하려면 검색 결과가 2건 이상 필요합니다.")` and return.
  - Always render the notice `키워드 일치 조문을 나란히 표시하며 법적 연계 관계를 자동 확정하지 않습니다`.
  - `left_col, right_col = st.columns(2)`; each side via `_render_compare_side(st, settings, response, parsed, options, column, side)` where `side in {"left", "right"}`.
  - `_render_compare_side`: `selectbox` over option labels (`key=f"compare-{side}"`), store selected key in `st.session_state[f"compare_{side}_result_key"]`, resolve with `_find_result`, show metadata, call `_preview_detail`, show an article `radio` (`key=f"compare-{side}-article"`) when >1 context, render the chosen context, and an official-link button when valid. No cross-side interaction; a failure on one side does not affect the other.

- [ ] **Step 1: Write the failing tests**

```python
def _two_result_response(result_factory):
    left = replace(
        result_factory(SourceGroup.LAW, uid="l1", title="건축법"),
        scope=SearchScope.BODY,
        match_context="제49조 — 건축물의 피난시설",
    )
    right = replace(
        result_factory(SourceGroup.DECREE, uid="d1", title="건축법 시행령"),
        scope=SearchScope.BODY,
        match_context="제46조 — 방화구획의 설치",
    )
    return SearchResponse(
        results=(left, right),
        suggestions=(),
        errors=(),
        source_states={"laws": SourceState.LIVE},
        source_fetched_at={"laws": _fetched()},
    )


def test_compare_needs_two_results(result_factory):
    single = SearchResponse(
        results=(replace(result_factory(SourceGroup.LAW, uid="l1"), scope=SearchScope.BODY, match_context="x"),),
        suggestions=(),
        errors=(),
        source_states={"laws": SourceState.LIVE},
        source_fetched_at={"laws": _fetched()},
    )
    streamlit = FakeStreamlit()

    app._render_compare(streamlit, object(), single, ParsedQuery("주차장"))

    assert any(name == "info" for name, _, _ in streamlit.calls)


def test_compare_shows_non_judgement_notice_and_two_columns(monkeypatch, result_factory):
    response = _two_result_response(result_factory)
    streamlit = FakeStreamlit()
    monkeypatch.setattr(
        app, "_preview_detail",
        lambda st, settings, result, keyword: DetailResponse(
            (f"{result.match_context}",), SourceState.FRESH_CACHE, _fetched()
        ),
    )

    app._render_compare(streamlit, object(), response, ParsedQuery("방화구획"))

    joined = " ".join(str(a) for name, args, _ in streamlit.calls for a in args)
    assert "법적 연계 관계를 자동 확정하지 않습니다" in joined
    assert (2,) in [args for name, args, _ in streamlit.calls if name == "columns"] or 2 in [
        args[0] for name, args, _ in streamlit.calls if name == "columns"
    ]


def test_compare_allows_same_source_on_both_sides(monkeypatch, result_factory):
    same_source = SearchResponse(
        results=tuple(
            replace(result_factory(SourceGroup.LAW, uid=f"l{i}", title=f"법 {i}"), scope=SearchScope.BODY, match_context=f"제{i}조 — 내용")
            for i in range(2)
        ),
        suggestions=(),
        errors=(),
        source_states={"laws": SourceState.LIVE},
        source_fetched_at={"laws": _fetched()},
    )
    streamlit = FakeStreamlit(
        selections={"compare-left": "법률 · 법 0", "compare-right": "법률 · 법 1"}
    )
    monkeypatch.setattr(
        app, "_preview_detail",
        lambda st, settings, result, keyword: DetailResponse((result.match_context,), SourceState.FRESH_CACHE, _fetched()),
    )

    app._render_compare(streamlit, object(), same_source, ParsedQuery("내용"))

    assert streamlit.session_state["compare_left_result_key"] == "law:l0"
    assert streamlit.session_state["compare_right_result_key"] == "law:l1"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_app.py -q -k compare`
Expected: FAIL — stub `_render_compare` forwards to `_render_results`.

- [ ] **Step 3: Implement**

Replace the `_render_compare` stub in `src/lawsearch/app.py`:

```python
def _render_compare(
    st: Any, settings: Settings, response: SearchResponse, parsed: ParsedQuery
) -> None:
    options = compare_options(response)
    if len(options) < 2:
        st.info("비교하려면 검색 결과가 2건 이상 필요합니다.")
        return
    st.caption(
        "키워드 일치 조문을 나란히 표시하며 법적 연계 관계를 자동 확정하지 않습니다."
    )
    left_col, right_col = st.columns(2)
    _render_compare_side(st, settings, response, parsed, options, left_col, "left")
    _render_compare_side(st, settings, response, parsed, options, right_col, "right")


def _render_compare_side(
    st: Any,
    settings: Settings,
    response: SearchResponse,
    parsed: ParsedQuery,
    options: tuple["CompareOption", ...],
    column: Any,
    side: str,
) -> None:
    labels = {option.label: option.key for option in options}
    with column:
        chosen_label = st.selectbox(
            f"{'왼쪽' if side == 'left' else '오른쪽'} 문서",
            tuple(labels),
            key=f"compare-{side}",
        )
        key = labels[chosen_label]
        st.session_state[f"compare_{side}_result_key"] = key
        result = _find_result(response, key)
        if result is None:
            st.error("문서를 찾을 수 없습니다.")
            return
        meta = [result.category]
        if result.authority:
            meta.append(result.authority)
        meta.append("현행" if result.is_current else "연혁")
        st.caption(" · ".join(meta))
        if is_official_url(result.official_url):
            st.link_button("공식 원문 열기", result.official_url)
        detail = _preview_detail(st, settings, result, parsed.keyword)
        if detail is None or detail.state is SourceState.ERROR:
            st.error("본문을 불러오지 못했습니다.")
            return
        if not detail.contexts:
            st.caption("검색어와 정확히 일치하는 조문이 없습니다.")
            return
        if len(detail.contexts) > 1:
            article_labels = [c.split(" — ", 1)[0] for c in detail.contexts]
            index = st.radio(
                "조문 선택",
                range(len(detail.contexts)),
                format_func=lambda position: article_labels[position],
                key=f"compare-{side}-article",
            )
        else:
            index = 0
        st.markdown(f"> {detail.contexts[index]}")
```

Add `compare_options`, `CompareOption` to the `viewmodels` import block.

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_app.py -q`
Expected: PASS

- [ ] **Step 5: Full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/lawsearch/app.py tests/test_app.py
git commit -m "feat: add side-by-side compare view"
```

---

## Task 12: Documentation updates

**Files:**
- Modify: `README.md`
- Modify: `docs/CLAUDE_HANDOFF.md`

**Interfaces:** none (docs only).

- [ ] **Step 1: Update `README.md`**

In the "실행과 검색 문법" section, after the search-syntax bullets, replace nothing structural but add a "화면 구성" subsection before "## 캐시와 장애 동작":

```markdown
## 화면 구성

- 검색 결과는 최대 폭을 제한한 데스크톱 화면에서 법규 유형별 2열 카드로 표시됩니다. 좁은 화면에서는 1열로 재배치됩니다.
- 사이드바는 법률·시행령·시행규칙·행정규칙·자치법규별 건수와 문서 바로가기입니다. 사이드바 선택은 다른 결과를 숨기지 않으며 검색을 다시 실행하지 않습니다.
- 카드의 `미리보기`는 이미 가져온 본문 검증 결과와 캐시를 재사용합니다. 제목만 일치한 문서는 처음 열 때만 본문을 조회합니다. `검색 결과로 돌아가기`는 API를 호출하지 않습니다.
- 상단의 `비교하기`는 현재 검색 결과 중 두 문서를 좌우로 골라 정확 일치 조문을 나란히 봅니다. 법률↔조례뿐 아니라 모든 유형 조합이 가능하며, 위임 관계나 우선순위를 자동 판정하지 않습니다.
- AI 요약이나 유사어 확장 검색은 제공하지 않습니다.
```

- [ ] **Step 2: Update `docs/CLAUDE_HANDOFF.md`**

- In the §3 status table, add rows (or update existing) to reflect: `데스크톱 2열 카드`, `법규 유형별 사이드바 바로가기`, `단일 문서 미리보기(지연 로딩)`, `좌우 비교` — all `현재 상태: 구현됨`, with `src/lawsearch/viewmodels.py`, `src/lawsearch/app.py` as evidence files.
- In §7 "사용자에게 약속했지만 아직 구현하지 않은 UI", remove items 1–5 (2열 레이아웃, 사이드바 바로가기, 미리보기 재사용, 기본 나열 + 비교, 모든 유형 비교) now that they are implemented. Keep item 6 (모바일 1열 검증) as remaining. Add a short line: `상위 UI는 구현됨. 남은 것은 좁은 폭 1열 재배치의 수동 검증과 Streamlit Community Cloud 비공개 배포(§8).`
- In §9, add `src/lawsearch/viewmodels.py | 순수 뷰모델: 그룹·카드·사이드바·비교 목록 | tests/test_viewmodels.py`.
- Do **not** claim Community Cloud deployment is done — it is a separate plan.

- [ ] **Step 3: Verify no secret-like content was added**

Run: `git diff --staged -- README.md docs/CLAUDE_HANDOFF.md` and confirm no key paths / `OC=` values.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/CLAUDE_HANDOFF.md
git commit -m "docs: describe the desktop search workspace"
```

---

## Task 13: Final verification and acceptance

**Files:** none (verification only).

- [ ] **Step 1: Full test suite, verbose**

Run: `.venv/Scripts/python.exe -m pytest -v`
Expected: all pass; only the 7 live-API integration tests skipped. Record the pass/skip counts.

- [ ] **Step 2: Regression guard check**

Run: `.venv/Scripts/python.exe -m pytest -q -k "방화구획 or matching_article or verification_failure or match_context"`
Expected: PASS — confirms the `방화구획`→`방화` false-positive is still blocked and `match_context` only ever comes from verified contexts.

- [ ] **Step 3: Secret scan**

Run:
```bash
git grep -n -I -E "OC=[A-Za-z0-9]|내 드라이브|api_key_file *= *\"[A-Z]:" -- ':!docs/**' ':!config.local.toml.example'
```
Expected: no matches. Then `git diff --check` on the branch range.

- [ ] **Step 4: `viewmodels` purity check**

Run: `.venv/Scripts/python.exe -c "import ast,sys; tree=ast.parse(open('src/lawsearch/viewmodels.py',encoding='utf-8').read()); mods=[n.module or '' for n in ast.walk(tree) if isinstance(n,(ast.Import,ast.ImportFrom))] + [a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]; sys.exit('streamlit imported' if any('streamlit' in m for m in mods) else 0)"`
Expected: exit 0.

- [ ] **Step 5: Manual desktop acceptance (spec §10)**

With a valid local `config.local.toml`, run the app on `127.0.0.1` and confirm, without committing anything:
1. `방화구획` → grouped 2-column cards inside the width-limited container.
2. Sidebar `대통령령(시행령)` expander lists decree titles; clicking one opens its preview.
3. Open a preview, click `검색 결과로 돌아가기` → results reappear with no spinner / no network call (watch the Streamlit console).
4. Re-open the same preview → renders immediately.
5. `비교하기` → pick `건축법 시행령` on the left and a related `부령` on the right; both article panes render.
6. In compare, pick a 법률 on both sides — allowed.
7. A title-only match whose body has no exact hit shows `검색어와 정확히 일치하는 조문이 없습니다`, not an arbitrary article.
8. Narrow the browser window → cards reflow to a single column (Streamlit `st.columns` reflow; acceptable if it degrades to stacked).

- [ ] **Step 6: Report**

Summarize: test counts, which acceptance checks passed, anything deferred. Do not push. Hand back to the user for review and the deployment follow-up plan.

---

## Self-Review

**1. Spec coverage**

| Spec section | Covered by |
| --- | --- |
| §2.1 2-column cards, width-limited | Task 8 (`_inject_layout_css`, `_render_results`, `card_rows`) |
| §2.2 sidebar = shortcuts + counts, not filter | Task 5 + Task 9; Global Constraints; `test_sidebar_click_opens_preview_without_search` |
| §2.3–2.4 sidebar nav & re-open reuse cache, no re-search | Task 9 (`_run` forbidden), Task 10 (`_preview_detail` session reuse) |
| §2.5 compare any source combo | Task 6 + Task 11; `test_compare_allows_same_source_on_both_sides` |
| §2.6 body-load failure keeps link + metadata | Task 10 (`detail.state is ERROR` path keeps metadata/link already rendered) |
| §2.7 private deploy for ~10 users | **Deferred** — separate deployment plan (stated up front) |
| §2.8 no secrets in git/sqlite/logs/screen | Global Constraints; Task 13 Step 3 |
| §4.1 common top bar, compact source/legal, Enter submit | Task 8 (`_render_top_bar`, existing `_render_search_form` kept) |
| §4.2 sidebar tree + counts, expand to names, click = jump/preview, no API | Task 5 + Task 9; Design decision 2/4 |
| §4.3 2-column cards, fixed card fields, single top `비교하기` | Task 4 (`CardView` fields) + Task 8 (`_render_card`, toggle in top bar) |
| §4.4 preview order, back = no API, failure state, no arbitrary article | Task 10; `test_preview_*` |
| §4.5 compare split, per-side independent, notice, single-result guard | Task 11; `test_compare_*` |
| §5.1 `SearchResult.match_context` from first verified context; title-only = None | Task 1 + Task 2 |
| §5.2 session state keys; reset on new search; refresh invalidates detail | Task 7 (`_WORKSPACE_KEYS`, `_clear_response`, `_clear_detail_state`) |
| §6.1 search parallel, session-stored, sidebar/cards from stored only | existing `service.search`; Tasks 8–9 read `response` only |
| §6.2 body results reuse verification cache; title lazy on first open; no prefetch | Task 2 (cache populated in verify) + Task 10 (`_preview_detail`) |
| §7 `lawsearch.viewmodels` new pure module; `app` coordinates only | Task 3 + Global Constraints purity test |
| §7 `lawsearch.service` passes first context; compare details via service | Task 2; Task 10/11 use `_contexts` → `service.load_contexts` |
| §9 error/edge cases | Task 8 (group ERROR/STALE), Task 10 (preview failure), Task 11 (single-result guard, per-side failure) |
| §10 unit tests | Tasks 4–7, 9–11 test lists |
| §10 integration: cache reuse, lazy once, sidebar nav no extra calls | `test_preview_reuses_session_detail_without_calling_api`, `test_preview_lazy_loads_title_match_once`, `test_sidebar_click_opens_preview_without_search` |
| §10 manual acceptance | Task 13 Step 5 |
| §12 step 1 models/viewmodels | Tasks 1, 3–6 |
| §12 step 2 cards + sidebar | Tasks 8, 9 |
| §12 step 3 preview + lazy | Task 10 |
| §12 step 4 compare | Task 11 |
| §12 step 5 cloud entrypoint/deps/secrets | **Deferred** — separate plan |
| §12 step 6 tests + manual acceptance | Task 13 |
| §12 step 7 README + handoff | Task 12 |

Gap: spec §2.7/§8/§12.5 (Community Cloud deployment) is intentionally deferred to a separate plan and called out in the plan header and self-review. No other gaps.

**2. Placeholder scan** — No "TBD"/"handle edge cases"/"similar to Task N". Two spots deliberately instruct deleting scaffolding: Task 5 Step 3 (`order = ...` dead line) and Task 8 Step 4 (temporary `_render_sidebar/_render_preview/_render_compare` stubs, deleted in Tasks 9–11). Each says so explicitly.

**3. Type consistency**
- `result_key` format `f"{source.value}:{uid}"` — used identically in Task 4, 6, 7 tests, `_find_result` (Task 10), sidebar (Task 5).
- `detail_session_key(source, uid, keyword)` — unchanged from today; used in Task 10/11 for `DetailResponse` session storage. Distinct from `result_key`; both documented in Design decision 1.
- `_contexts(settings, result, keyword, *, refresh=False, limit=5)` — Task 10 defines; matches `service.load_contexts(result, keyword, refresh=False, *, limit=5)` from Task 2.
- `CardView` fields (`key,title,match_kind,match_line,official_url,meta_fields`) — Task 4 dataclass matches `_render_card` usage in Task 8.
- `SidebarSection.label` ∈ {`"자치법규"`,`"상위법령"`} — Task 5 impl and tests agree; Task 9 renders `section.label` directly.
- `DetailResponse(contexts, state, fetched_at)` — existing 3-field shape; Task 10/11 tests construct it positionally, matches `src/lawsearch/models.py`.
- `_view_mode` returns `"results"|"preview"|"compare"`; `main()` compares against `_VIEW_PREVIEW`/`_VIEW_COMPARE` constants (Task 7) — consistent.
