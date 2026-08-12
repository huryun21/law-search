# Korean Law Search MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Windows-local Streamlit app that searches current Korean statutes, administrative rules, and optionally prioritized local ordinances through the official 국가법령정보 공동활용 API.

**Architecture:** A thin Streamlit UI delegates query parsing, region resolution, API access, normalization, ranking, and SQLite caching to focused Python modules. External API responses are normalized into immutable domain models; each API source is cached independently so partial failures can fall back without hiding successful live results.

**Tech Stack:** Python 3.12+, Streamlit, httpx, SQLite, standard-library dataclasses/tomllib/asyncio, pytest, httpx MockTransport

## Global Constraints

- Bind the application to `127.0.0.1` only.
- Search current statutes with `target=eflaw`, `nw=3`, `search=2`.
- Search current administrative rules with `target=admrul`, `nw=1`, `search=2`.
- Search current ordinances with `target=ordin`, `nw=1`, `search=2`, and official `org`/`sborg` codes.
- A query without an `@region` token must not call the ordinance API.
- `@region` results rank municipal ordinances, provincial ordinances, statutes, decrees, ministerial rules, administrative rules, then other regulations.
- Cache search lists and detail bodies separately for 24 hours; retain stale entries only for API-failure fallback; purge entries unused for 30 days.
- Never persist or log the API credential or a request URL containing the credential.
- Do not add AI summarization, case-law search, authentication, public hosting, or automatic legal conclusions.
- Show `출처: 국가법령정보센터` and the approved official-source warning in the UI.

---

## File Structure

```text
korean-law-search/
├─ .gitignore                         # local config, virtualenv, cache, logs
├─ README.md                          # setup, run, search syntax, legal caveat
├─ pyproject.toml                     # runtime and test dependencies
├─ run.bat                            # Windows venv bootstrap and local launch
├─ config.local.toml.example          # path-only credential configuration
├─ scripts/
│  └─ build_regions.py               # official code export → compact JSON
├─ src/lawsearch/
│  ├─ __init__.py
│  ├─ app.py                          # Streamlit composition only
│  ├─ api.py                          # sanitized httpx client and endpoint calls
│  ├─ cache.py                        # SQLite cache repository
│  ├─ config.py                       # path-only settings and credential loader
│  ├─ detail.py                       # recursive text/context extraction
│  ├─ models.py                       # immutable domain types and serialization
│  ├─ normalize.py                    # API JSON → SearchResult
│  ├─ query.py                        # @region parser and query variants
│  ├─ ranking.py                      # group and match-quality ordering
│  ├─ regions.py                      # region lookup and ambiguity handling
│  ├─ service.py                      # concurrent orchestration and fallback
│  └─ data/regions.json               # official org/sborg registry
└─ tests/
   ├─ fixtures/                       # credential-free official response shapes
   ├─ integration/test_live_api.py    # opt-in live contract checks
   ├─ conftest.py                     # fixture loader and domain factories
   ├─ test_api.py
   ├─ test_cache.py
   ├─ test_config.py
   ├─ test_detail.py
   ├─ test_normalize.py
   ├─ test_query.py
   ├─ test_ranking.py
   ├─ test_regions.py
   └─ test_service.py
```

---

### Task 1: Project Bootstrap and Secret-Safe Configuration

**Files:**
- Create: `.gitignore`
- Create: `pyproject.toml`
- Create: `config.local.toml.example`
- Create: `src/lawsearch/__init__.py`
- Create: `src/lawsearch/config.py`
- Create: `tests/test_config.py`

**Interfaces:**
- Produces: `Settings(api_key_file: Path, cache_path: Path)`
- Produces: `load_settings(project_root: Path, environ: Mapping[str, str] | None = None) -> Settings`
- Produces: `load_api_key(path: Path) -> str`
- Consumes: external credential file selected from `G:\내 드라이브\01_AI개발\00_인증정보`; its value is never printed

- [ ] **Step 1: Inspect only credential filenames and redacted file shape**

Run a PowerShell command that lists names under the authorized directory without reading values. Select the file whose name identifies 국가법령정보 공동활용. Inspect its format with a redacting filter that prints only field names and value lengths. Do not emit raw file content to the terminal.

- [ ] **Step 2: Write failing configuration tests**

```python
from pathlib import Path

import pytest

from lawsearch.config import ConfigError, load_api_key, load_settings


def test_settings_store_only_external_key_path(tmp_path: Path):
    key_file = tmp_path / "law-key.txt"
    config = tmp_path / "config.local.toml"
    config.write_text(
        f'api_key_file = "{key_file.as_posix()}"\ncache_path = "data/cache.db"\n',
        encoding="utf-8",
    )

    settings = load_settings(tmp_path, {})

    assert settings.api_key_file == key_file
    assert not hasattr(settings, "api_key")


def test_plaintext_key_is_trimmed(tmp_path: Path):
    key_file = tmp_path / "key.txt"
    key_file.write_text("  approved-key  \n", encoding="utf-8")
    assert load_api_key(key_file) == "approved-key"


def test_empty_key_file_is_rejected(tmp_path: Path):
    key_file = tmp_path / "key.txt"
    key_file.write_text(" \n", encoding="utf-8")
    with pytest.raises(ConfigError, match="비어"):
        load_api_key(key_file)
```

- [ ] **Step 3: Run the tests and verify RED**

Run: `python -m pytest tests/test_config.py -v`

Expected: collection fails with `ModuleNotFoundError: No module named 'lawsearch.config'`.

- [ ] **Step 4: Add minimal packaging and configuration implementation**

Use a `src` layout in `pyproject.toml`; runtime dependencies are `streamlit>=1.41,<2` and `httpx>=0.27,<1`, and the test extra contains `pytest>=8,<10`. Implement `Settings` as a frozen dataclass. `LAW_API_KEY_FILE` and `LAW_CACHE_PATH` environment variables override `config.local.toml`; resolve relative cache paths against the project root. Raise Korean `ConfigError` messages that never include file contents.

```python
@dataclass(frozen=True)
class Settings:
    api_key_file: Path
    cache_path: Path


def load_api_key(path: Path) -> str:
    value = path.read_text(encoding="utf-8-sig").strip()
    if not value:
        raise ConfigError("API 인증정보 파일이 비어 있습니다.")
    return value
```

Adapt `load_api_key` only to the inspected external file shape. Do not add speculative parsers for formats that are not present.

- [ ] **Step 5: Add Git exclusions and path-only example**

`.gitignore` must exclude `.venv/`, `config.local.toml`, `data/*.db*`, `.pytest_cache/`, `__pycache__/`, and `*.log`. The example config contains only:

```toml
api_key_file = "G:\\path\\to\\external-law-api-key.txt"
cache_path = "data/cache.db"
```

- [ ] **Step 6: Run tests and secret scan**

Run: `python -m pytest tests/test_config.py -v`

Expected: all configuration tests pass.

Run: `git grep -n -I -E "OC=|api_key[[:space:]]*=" -- ':!config.local.toml.example'`

Expected: no credential value or request URL containing `OC=` is tracked.

- [ ] **Step 7: Commit**

```powershell
git add .gitignore pyproject.toml config.local.toml.example src/lawsearch/__init__.py src/lawsearch/config.py tests/test_config.py
git commit -m "build: add secret-safe local configuration"
```

---

### Task 2: Official Region Registry and `@region` Query Parser

**Files:**
- Create: `scripts/build_regions.py`
- Create: `src/lawsearch/data/regions.json`
- Create: `src/lawsearch/models.py`
- Create: `src/lawsearch/regions.py`
- Create: `src/lawsearch/query.py`
- Create: `tests/conftest.py`
- Create: `tests/test_regions.py`
- Create: `tests/test_query.py`

**Interfaces:**
- Produces: `Region(province_name: str, municipality_name: str | None, org: str, sborg: str | None, aliases: tuple[str, ...])`
- Produces: `RegionRegistry.from_package_data() -> RegionRegistry`
- Produces: `RegionRegistry.resolve(token: str) -> RegionResolution`
- Produces: `ParsedQuery(keyword: str, region: Region | None, candidates: tuple[Region, ...])`
- Produces: `parse_query(raw: str, registry: RegionRegistry) -> ParsedQuery`
- Produces: `build_query_variants(keyword: str) -> tuple[QueryVariant, ...]`

- [ ] **Step 1: Obtain and record the official region source**

Export current 지방자치단체 institution codes from the official 행정표준코드관리시스템 institution-code search. Record the retrieval date and source URL in the generated JSON metadata. Keep the 2026-07-01 current structure: 16 province/metropolitan-city codes and 229 current city/county/district codes. Record the effective laws for 전남광주통합특별시 (법률 제21446호), the Incheon district reorganization (법률 제20161호), and 서구→서해구 (법률 제21734호). The source page is `https://code.go.kr/stdcode/orgCodeL.do`; the law API's `org`/`sborg` semantics are documented at `https://open.law.go.kr/LSO/openApi/guideResult.do?htmlName=ordinListGuide`.

- [ ] **Step 2: Write failing registry tests before adding data**

```python
from lawsearch.regions import RegionRegistry


def test_registry_contains_all_current_provinces_and_municipalities():
    registry = RegionRegistry.from_package_data()
    assert len({region.org for region in registry.regions}) == 16
    assert sum(region.sborg is not None for region in registry.regions) >= 229


def test_current_2026_regions_and_legacy_aliases():
    registry = RegionRegistry.from_package_data()
    assert registry.resolve("전남광주").region.org == "6130000"
    assert registry.resolve("광주/동구").region.sborg == "5805000"
    assert registry.resolve("제물포").region.sborg == "3501000"
    assert {item.municipality_name for item in registry.resolve("인천/중구").candidates} == {
        "영종구", "제물포구"
    }


def test_pyeongtaek_resolves_to_gyeonggi_municipality():
    resolution = RegionRegistry.from_package_data().resolve("평택")
    assert resolution.is_unique
    assert resolution.region.province_name == "경기도"
    assert resolution.region.municipality_name == "평택시"
    assert resolution.region.org.isdigit() and len(resolution.region.org) == 7
    assert resolution.region.sborg.isdigit() and len(resolution.region.sborg) == 7


def test_junggu_returns_multiple_candidates():
    resolution = RegionRegistry.from_package_data().resolve("중구")
    assert not resolution.is_unique
    assert len(resolution.candidates) >= 3
```

- [ ] **Step 3: Verify registry tests fail for missing implementation/data**

Run: `python -m pytest tests/test_regions.py -v`

Expected: `ModuleNotFoundError` or missing data failure.

- [ ] **Step 4: Implement the smallest registry and deterministic generator**

`build_regions.py` accepts an official export path and output path, emits UTF-8 JSON sorted by province then municipality, rejects missing/duplicate seven-digit codes, and includes source, retrieval, effective-law, and API-compatibility metadata. It keeps only current institution rows. `RegionRegistry` supports exact official names, suffix-stripped aliases such as `평택`, qualified aliases such as `경기/평택`, and explicit legacy successor aliases. It never picks the first ambiguous successor. A code listed as API-unverified resolves as a candidate even when it is the only match, preventing an unsafe ordinance request.

Define the shared immutable domain types in `models.py` with these exact fields:

```python
class SourceGroup(str, Enum):
    MUNICIPAL = "municipal"
    PROVINCIAL = "provincial"
    LAW = "law"
    DECREE = "decree"
    MINISTERIAL_RULE = "ministerial_rule"
    ADMIN_RULE = "admin_rule"
    OTHER = "other"


class MatchQuality(IntEnum):
    EXACT = 0
    COMPACT = 1
    ALL_TERMS = 2


@dataclass(frozen=True)
class Region:
    province_name: str
    municipality_name: str | None
    org: str
    sborg: str | None = None
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedQuery:
    keyword: str
    region: Region | None = None
    candidates: tuple[Region, ...] = ()


@dataclass(frozen=True)
class RegionResolution:
    region: Region | None
    candidates: tuple[Region, ...] = ()

    @property
    def is_unique(self) -> bool:
        return self.region is not None


@dataclass(frozen=True)
class QueryVariant:
    query: str
    quality: MatchQuality


@dataclass(frozen=True)
class SearchResult:
    uid: str
    source: SourceGroup
    quality: MatchQuality
    title: str
    category: str
    authority: str | None
    region_name: str | None
    promulgation_date: date | None
    effective_date: date | None
    is_current: bool
    official_url: str
    fetched_at: datetime
```

`tests/conftest.py` initially provides `load_fixture(name: str) -> dict` and `pyeongtaek -> Region`; later tasks extend it with factories without changing their signatures.

- [ ] **Step 5: Run registry tests and verify GREEN**

Run: `python -m pytest tests/test_regions.py -v`

Expected: all region coverage, Pyeongtaek, and Jung-gu ambiguity tests pass.

- [ ] **Step 6: Write failing parser and variant tests**

```python
import pytest

from lawsearch.query import QueryError, build_query_variants, parse_query
from lawsearch.regions import RegionRegistry


def test_keyword_without_region_does_not_request_ordinances():
    parsed = parse_query("주차 대수", RegionRegistry.from_package_data())
    assert parsed.keyword == "주차 대수"
    assert parsed.region is None


@pytest.mark.parametrize("raw", ["@평택 주차 대수", "주차 대수 @평택"])
def test_pyeongtaek_token_is_removed_from_keyword(raw):
    parsed = parse_query(raw, RegionRegistry.from_package_data())
    assert parsed.keyword == "주차 대수"
    assert parsed.region.municipality_name == "평택시"


def test_ambiguous_region_returns_candidates_without_searchable_region():
    parsed = parse_query("@중구 주차 대수", RegionRegistry.from_package_data())
    assert parsed.region is None
    assert len(parsed.candidates) >= 3


def test_multiple_region_tokens_are_rejected():
    with pytest.raises(QueryError, match="하나"):
        parse_query("@평택 @수원 주차", RegionRegistry.from_package_data())


def test_spaced_keyword_builds_exact_and_compact_variants():
    variants = build_query_variants("주차 대수")
    assert [(item.query, item.quality.name) for item in variants[:2]] == [
        ("주차 대수", "EXACT"),
        ("주차대수", "COMPACT"),
    ]
```

- [ ] **Step 7: Verify parser tests fail, implement, and verify GREEN**

Run: `python -m pytest tests/test_query.py -v`

Expected RED: missing `parse_query`/`build_query_variants`.

Implement one optional `@` token, whitespace normalization, current and legacy qualified aliases, ambiguity/successor-candidate return, API-unverified fallback, and exact/compact variants with duplicate removal. Run the same command and expect all tests to pass.

- [ ] **Step 8: Commit**

```powershell
git add docs/superpowers/specs/2026-08-11-korean-law-search-design.md docs/superpowers/plans/2026-08-11-korean-law-search-mvp.md scripts/build_regions.py src/lawsearch/data/regions.json src/lawsearch/models.py src/lawsearch/regions.py src/lawsearch/query.py tests/conftest.py tests/test_regions.py tests/test_query.py
git commit -m "feat: parse regional law searches"
```

---

### Task 3: Sanitized API Client, Normalization, and Detail Contexts

**Files:**
- Create: `src/lawsearch/api.py`
- Create: `src/lawsearch/normalize.py`
- Create: `src/lawsearch/detail.py`
- Create: `tests/fixtures/law-single.json`
- Create: `tests/fixtures/law-multiple.json`
- Create: `tests/fixtures/admrul.json`
- Create: `tests/fixtures/ordin.json`
- Create: `tests/fixtures/terms.json`
- Create: `tests/test_api.py`
- Create: `tests/test_normalize.py`
- Create: `tests/test_detail.py`

**Interfaces:**
- Produces: `LawApiClient(api_key: str, transport: httpx.AsyncBaseTransport | None = None)`
- Produces async: `search_laws(query: str, page: int = 1) -> dict[str, Any]`
- Produces async: `search_admin_rules(query: str, page: int = 1) -> dict[str, Any]`
- Produces async: `search_ordinances(query: str, region: Region, province_only: bool, page: int = 1) -> dict[str, Any]`
- Produces async: `suggest_terms(query: str) -> tuple[str, ...]`
- Produces async: `fetch_detail(result: SearchResult) -> dict[str, Any]`
- Produces: `normalize_results(payload: Mapping[str, Any], source: SourceGroup, quality: MatchQuality, fetched_at: datetime) -> tuple[SearchResult, ...]`
- Produces: `extract_contexts(payload: Any, keyword: str, limit: int = 5) -> tuple[str, ...]`

- [ ] **Step 1: Capture credential-free response fixtures**

Call each approved endpoint once through a redacting diagnostic that writes only response JSON to `tests/fixtures/`; never write the request URL or credential. Remove volatile counts and retain one representative single-item and multi-item shape. Endpoints:

```text
lawSearch.do target=eflaw nw=3 search=2 type=JSON
lawSearch.do target=admrul nw=1 search=2 type=JSON
lawSearch.do target=ordin nw=1 search=2 type=JSON org=<경기도> sborg=<평택시>
lawSearch.do target=lstrmAI type=JSON
lawService.do target=dlytrmRlt type=JSON
```

- [ ] **Step 2: Write failing API request/redaction tests**

```python
import asyncio
import httpx
import pytest

from lawsearch.api import ApiError, LawApiClient


def test_law_request_uses_current_effective_law_search():
    seen = {}

    def handler(request: httpx.Request):
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"LawSearch": {"totalCnt": "0"}})

    client = LawApiClient("top-secret", httpx.MockTransport(handler))
    asyncio.run(client.search_laws("주차 대수"))

    assert seen["params"]["OC"] == "top-secret"
    assert seen["params"]["target"] == "eflaw"
    assert seen["params"]["nw"] == "3"
    assert seen["params"]["search"] == "2"
    assert seen["params"]["type"] == "JSON"
    assert seen["params"]["display"] == "100"
    assert seen["params"]["page"] == "1"


def test_error_message_never_contains_key():
    def handler(request: httpx.Request):
        return httpx.Response(500, text="failure")

    client = LawApiClient("top-secret", httpx.MockTransport(handler))
    with pytest.raises(ApiError) as caught:
        asyncio.run(client.search_laws("주차"))
    assert "top-secret" not in str(caught.value)
    assert "OC=" not in str(caught.value)
```

The test may inspect the sample key in memory, but no production log or cache may contain it.

- [ ] **Step 3: Verify API tests fail, implement client, verify GREEN**

Run: `python -m pytest tests/test_api.py -v`

Expected RED: missing API client.

Implement one private `_request_json(path, safe_operation, params)` with a 10-second timeout and `https://www.law.go.kr/DRF/` base URL. Pass the key only in httpx params, use the safe operation name in errors, and reject non-object JSON. Implement endpoint methods exactly as defined above, including `org` only for provincial searches and `org+sborg` for municipal searches.

- [ ] **Step 4: Write failing single/multiple normalization tests**

```python
from datetime import UTC, datetime

from lawsearch.models import MatchQuality, SourceGroup
from lawsearch.normalize import normalize_results


def test_single_law_object_is_normalized(load_fixture):
    results = normalize_results(
        load_fixture("law-single.json"),
        SourceGroup.LAW,
        MatchQuality.EXACT,
        datetime(2026, 8, 11, tzinfo=UTC),
    )
    assert len(results) == 1
    assert results[0].title
    assert results[0].official_url.startswith("https://www.law.go.kr/")


def test_ordinance_has_authority_and_effective_date(load_fixture):
    result = normalize_results(
        load_fixture("ordin.json"), SourceGroup.MUNICIPAL, MatchQuality.EXACT,
        datetime(2026, 8, 11, tzinfo=UTC),
    )[0]
    assert result.authority == "평택시"
    assert result.effective_date is not None
```

- [ ] **Step 5: Verify normalization RED, implement defensive shape handling, verify GREEN**

Normalize Korean field aliases without mutating fixtures. A missing optional field becomes `None`; an unrecognized top-level response or a record missing ID, title, or official link raises a credential-free `ResponseShapeError` naming only the source. Convert relative official links to `https://www.law.go.kr/...` and reject links to other hosts.

Run: `python -m pytest tests/test_normalize.py -v`

Expected: single-object and list responses both pass.

- [ ] **Step 6: Write failing detail-context tests, implement recursive extraction, verify GREEN**

```python
from lawsearch.detail import extract_contexts


def test_context_extraction_strips_html_and_finds_compact_spacing():
    payload = {"조문": [{"내용": "<p>부설주차장의 주차대수는 별표와 같다.</p>"}]}
    assert extract_contexts(payload, "주차 대수") == (
        "부설주차장의 주차대수는 별표와 같다.",
    )


def test_context_extraction_is_limited_and_deduplicated():
    payload = {"a": ["주차 대수 기준", "주차 대수 기준", "주차 대수 예외"]}
    assert extract_contexts(payload, "주차 대수", limit=1) == ("주차 대수 기준",)
```

Run RED, implement recursive mapping/list/string traversal with HTML stripping, whitespace normalization, compact comparison, stable deduplication, and the hard limit. Run GREEN.

- [ ] **Step 7: Commit**

```powershell
git add src/lawsearch/api.py src/lawsearch/normalize.py src/lawsearch/detail.py tests/fixtures tests/test_api.py tests/test_normalize.py tests/test_detail.py
git commit -m "feat: integrate official law data APIs"
```

---

### Task 4: SQLite Cache with Fresh/Stale Semantics

**Files:**
- Create: `src/lawsearch/cache.py`
- Create: `tests/test_cache.py`

**Interfaces:**
- Produces: `CacheStore(path: Path, ttl: timedelta = timedelta(hours=24))`
- Produces: `CacheStore.get(key: str, now: datetime | None = None) -> CacheEntry | None`
- Produces: `CacheStore.put(key: str, payload: Mapping[str, Any], fetched_at: datetime | None = None) -> None`
- Produces: `CacheStore.purge_unused(before: datetime) -> int`
- Produces: `make_cache_key(source: str, keyword: str, region_codes: tuple[str, ...], page: int, detail_id: str | None = None) -> str`

- [ ] **Step 1: Write failing fresh/stale/purge tests**

```python
from datetime import UTC, datetime, timedelta

from lawsearch.cache import CacheStore, make_cache_key


def test_entry_is_fresh_before_24_hours(tmp_path):
    store = CacheStore(tmp_path / "cache.db")
    fetched = datetime(2026, 8, 11, 0, 0, tzinfo=UTC)
    store.put("k", {"value": 1}, fetched)
    hit = store.get("k", fetched + timedelta(hours=23, minutes=59))
    assert hit.is_fresh
    assert hit.payload == {"value": 1}


def test_entry_is_stale_at_24_hours(tmp_path):
    store = CacheStore(tmp_path / "cache.db")
    fetched = datetime(2026, 8, 11, tzinfo=UTC)
    store.put("k", {"value": 1}, fetched)
    assert not store.get("k", fetched + timedelta(hours=24)).is_fresh


def test_cache_key_never_contains_api_key():
    key = make_cache_key("law", "주차 대수", (), 1)
    assert "OC=" not in key
    assert "주차 대수" not in key
```

- [ ] **Step 2: Verify RED, implement schema and transactions, verify GREEN**

Run: `python -m pytest tests/test_cache.py -v`

Expected RED: missing cache module.

Implement a single `cache_entries` table with `key`, JSON `payload`, `fetched_at`, and `accessed_at`. Use UTC ISO timestamps, SHA-256 semantic keys, parameterized SQL, WAL mode, and context-managed connections. Reading updates `accessed_at`; stale entries remain readable. Purge only entries with `accessed_at < before`.

Use this exact cache return model:

```python
@dataclass(frozen=True)
class CacheEntry:
    payload: dict[str, Any]
    fetched_at: datetime
    is_fresh: bool
```

- [ ] **Step 3: Verify no credential-like values in the database fixture**

Add a test that writes representative payloads, reads raw SQLite bytes, and asserts `b"OC="` and the sample secret are absent.

- [ ] **Step 4: Commit**

```powershell
git add src/lawsearch/cache.py tests/test_cache.py
git commit -m "feat: add persistent law search cache"
```

---

### Task 5: Concurrent Search Orchestration and Deterministic Ranking

**Files:**
- Create: `src/lawsearch/ranking.py`
- Create: `src/lawsearch/service.py`
- Create: `tests/test_ranking.py`
- Create: `tests/test_service.py`

**Interfaces:**
- Produces: `rank_results(results: Iterable[SearchResult], region: Region | None) -> tuple[SearchResult, ...]`
- Produces: `SearchService(api: LawApiClient, cache: CacheStore, clock: Callable[[], datetime])`
- Produces async: `SearchService.search(parsed: ParsedQuery, refresh: bool = False, page: int = 1) -> SearchResponse`
- Produces async: `SearchService.load_contexts(result: SearchResult, keyword: str, refresh: bool = False) -> DetailResponse`

- [ ] **Step 1: Write failing rank-order tests**

```python
from lawsearch.models import MatchQuality, SourceGroup
from lawsearch.ranking import rank_results


def test_regional_group_order(result_factory, pyeongtaek):
    unordered = [
        result_factory(SourceGroup.ADMIN_RULE),
        result_factory(SourceGroup.LAW),
        result_factory(SourceGroup.PROVINCIAL),
        result_factory(SourceGroup.MUNICIPAL),
        result_factory(SourceGroup.DECREE),
        result_factory(SourceGroup.MINISTERIAL_RULE),
    ]
    ranked = rank_results(unordered, pyeongtaek)
    assert [item.source for item in ranked] == [
        SourceGroup.MUNICIPAL,
        SourceGroup.PROVINCIAL,
        SourceGroup.LAW,
        SourceGroup.DECREE,
        SourceGroup.MINISTERIAL_RULE,
        SourceGroup.ADMIN_RULE,
    ]


def test_match_quality_precedes_effective_date(result_factory):
    compact = result_factory(SourceGroup.LAW, quality=MatchQuality.COMPACT, effective="20260811")
    exact = result_factory(SourceGroup.LAW, quality=MatchQuality.EXACT, effective="20200101")
    assert rank_results([compact, exact], None) == (exact, compact)
```

- [ ] **Step 2: Verify RED, implement ranking only, verify GREEN**

Classify normalized `법령구분명` into law, decree, ministerial rule, or other in `normalize.py`; keep ranking itself as a pure tuple key. Run `python -m pytest tests/test_ranking.py -v` until green.

- [ ] **Step 3: Write failing orchestration tests with a fake API**

First extend `tests/conftest.py` with a `FakeApi` whose async methods add only safe operation names to `calls`, optionally raise `ApiError` for names in `fail`, and return fixture payloads otherwise. Add `result_factory`, `parsed_plain`, `parsed_pyeongtaek`, and `service_factory` fixtures. `service_factory` must create a temporary `CacheStore`, insert source-specific stale payloads requested by its `stale` argument, and return `(SearchService, FakeApi)`.

```python
import asyncio

from lawsearch.service import SearchService


def test_nonregional_search_never_calls_ordinances(service_factory, parsed_plain):
    service, fake_api = service_factory()
    asyncio.run(service.search(parsed_plain))
    assert fake_api.calls == {"laws", "admin_rules", "terms"}


def test_regional_search_calls_municipal_and_provincial_sources(service_factory, parsed_pyeongtaek):
    service, fake_api = service_factory()
    response = asyncio.run(service.search(parsed_pyeongtaek))
    assert {"municipal", "provincial"} <= fake_api.calls
    assert response.results[0].source.name == "MUNICIPAL"


def test_partial_failure_returns_successes_and_source_error(service_factory, parsed_plain):
    service, fake_api = service_factory(fail={"admin_rules"})
    response = asyncio.run(service.search(parsed_plain))
    assert any(item.source.name == "LAW" for item in response.results)
    assert response.errors[0].source == "admin_rules"


def test_api_failure_uses_stale_cache_with_timestamp(service_factory, parsed_plain):
    service, fake_api = service_factory(fail={"laws"}, stale={"laws"})
    response = asyncio.run(service.search(parsed_plain))
    assert response.source_states["laws"].name == "STALE_FALLBACK"
```

- [ ] **Step 4: Verify orchestration RED**

Run: `python -m pytest tests/test_service.py -v`

Expected: missing SearchService and response models.

- [ ] **Step 5: Implement minimal orchestration**

Extend `models.py` with these exact response types before implementing the service:

```python
class SourceState(str, Enum):
    LIVE = "live"
    FRESH_CACHE = "fresh_cache"
    STALE_FALLBACK = "stale_fallback"
    EMPTY = "empty"
    ERROR = "error"


@dataclass(frozen=True)
class SourceError:
    source: str
    message: str


@dataclass(frozen=True)
class SearchResponse:
    results: tuple[SearchResult, ...]
    suggestions: tuple[str, ...]
    errors: tuple[SourceError, ...]
    source_states: Mapping[str, SourceState]


@dataclass(frozen=True)
class DetailResponse:
    contexts: tuple[str, ...]
    state: SourceState
    fetched_at: datetime
```

For each source and query variant, compute a semantic cache key. A fresh hit bypasses the API unless `refresh=True`. A live success normalizes, stores, and returns results. A live failure reads stale cache and records `STALE_FALLBACK`; with no stale entry it records a source error. Use `asyncio.gather(..., return_exceptions=True)` so sources are isolated.

Merge duplicate `(source, uid)` results while retaining the best `MatchQuality`. Call term suggestions independently and never fail the main response because term lookup failed. If an ambiguous region candidate list is present, raise a validation response before any API call.

- [ ] **Step 6: Add exact/compact/all-term fallback tests and implementation**

Search the exact and compact variants first. Only if both return no items for a source and the keyword has two or more tokens, search each token and intersect result IDs; tag those results `ALL_TERMS`. Add a test proving no token fallback calls occur when exact results exist.

- [ ] **Step 7: Add lazy detail caching test and implementation**

Verify `load_contexts` fetches detail only on first expansion, reuses fresh detail cache, refreshes expired detail, and uses stale detail only after API failure. Context extraction uses `extract_contexts` and never returns the complete raw body.

- [ ] **Step 8: Run service suite and commit**

Run: `python -m pytest tests/test_ranking.py tests/test_service.py -v`

Expected: all tests pass with no warnings.

```powershell
git add src/lawsearch/ranking.py src/lawsearch/service.py src/lawsearch/normalize.py src/lawsearch/models.py tests/conftest.py tests/test_ranking.py tests/test_service.py
git commit -m "feat: orchestrate and rank unified searches"
```

---

### Task 6: Streamlit UI and Windows Launcher

**Files:**
- Create: `src/lawsearch/app.py`
- Create: `run.bat`
- Create: `tests/test_app.py`

**Interfaces:**
- Consumes: `load_settings`, `RegionRegistry`, `parse_query`, `SearchService`
- Produces: `build_grouped_view(response: SearchResponse) -> tuple[ResultGroupView, ...]`
- Produces: Streamlit entry command `python -m streamlit run src/lawsearch/app.py --server.address 127.0.0.1`

- [ ] **Step 1: Write failing pure view-model tests**

```python
from lawsearch.app import build_grouped_view


def test_view_groups_keep_ranked_source_order(search_response_factory):
    groups = build_grouped_view(search_response_factory())
    assert [group.label for group in groups[:3]] == [
        "평택시 자치법규",
        "경기도 자치법규",
        "법률",
    ]


def test_stale_source_has_visible_retrieval_warning(search_response_factory):
    groups = build_grouped_view(search_response_factory(stale={"municipal"}))
    assert "이전 결과" in groups[0].status_message
    assert groups[0].fetched_at is not None
```

- [ ] **Step 2: Verify RED, implement view models, verify GREEN**

Run: `python -m pytest tests/test_app.py -v`

Expected RED: missing UI module.

Keep view-model construction pure. Streamlit calls belong only in `main()` so tests import the module without starting a server.

Use these exact immutable view types:

```python
@dataclass(frozen=True)
class ResultGroupView:
    label: str
    results: tuple[SearchResult, ...]
    state: SourceState
    status_message: str
    fetched_at: datetime | None
```

- [ ] **Step 3: Implement the approved screen**

Add the title and examples `주차 대수`, `@평택 주차 대수`, `@경기/평택 주차 대수`. Use one search input and one button. When a token is ambiguous, show a selectbox with fully qualified region names and rerun only after selection. Show the selected region as a visible chip-like label with a clear action.

Render collapsible groups in ranked order. Each result shows title, category, authority, promulgation/effective dates, current status, retrieval/cache state, `본문 펼치기`, and a host-validated official link. On expansion call `load_contexts`; show at most five exact contexts. Put `출처: 국가법령정보센터` and `참고자료이며 최종 확인은 공식 원문 및 소관기관 기준` in persistent visible UI.

- [ ] **Step 4: Add force-refresh and partial-error behavior**

The refresh button calls `search(..., refresh=True)`. Show successful groups even when another source fails. Each failure row includes source name and a retry action; stale fallback contains the exact retrieval time. Never pass raw exception text to `st.error`.

- [ ] **Step 5: Create the launcher**

`run.bat` must:

1. `cd /d` to its own directory.
2. Create `.venv` with `py -3.12 -m venv .venv` only if missing.
3. Install the project with `.venv\Scripts\python.exe -m pip install -e .` only when the package import fails.
4. Launch Streamlit on `127.0.0.1` with browser auto-open enabled.
5. Keep the terminal open with an actionable Korean error when Python or config is missing.

- [ ] **Step 6: Run UI unit tests and local smoke test**

Run: `python -m pytest tests/test_app.py -v`

Run: `python -m streamlit run src/lawsearch/app.py --server.address 127.0.0.1 --server.headless true`

Expected: Streamlit health endpoint responds on localhost; no non-loopback bind appears in `Get-NetTCPConnection` for the process.

- [ ] **Step 7: Commit**

```powershell
git add src/lawsearch/app.py tests/test_app.py run.bat
git commit -m "feat: add local law search interface"
```

---

### Task 7: Live Contract Verification, Documentation, and Security Audit

**Files:**
- Create: `tests/integration/test_live_api.py`
- Create: `README.md`
- Modify: `config.local.toml` (local only, remains ignored)

**Interfaces:**
- Consumes all prior public interfaces
- Produces opt-in command: `RUN_LIVE_LAW_API=1 python -m pytest tests/integration/test_live_api.py -v`

- [ ] **Step 1: Write opt-in live contract tests before enabling them**

```python
import os

import pytest


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_LAW_API") != "1",
    reason="live law API contract test is opt-in",
)


def test_live_plain_search_returns_valid_official_links(live_service, parsed_plain):
    response = run(live_service.search(parsed_plain, refresh=True))
    assert response.results
    assert all(item.official_url.startswith("https://www.law.go.kr/") for item in response.results)


def test_live_pyeongtaek_search_includes_regional_sources(live_service, parsed_pyeongtaek):
    response = run(live_service.search(parsed_pyeongtaek, refresh=True))
    assert "municipal" in response.source_states
    assert "provincial" in response.source_states
    assert response.source_states["municipal"].name in {"LIVE", "EMPTY"}
    assert response.source_states["provincial"].name in {"LIVE", "EMPTY"}
```

Use `asyncio.run` as the `run` helper. Do not assert changing counts or hard-code one law title.

- [ ] **Step 2: Create the local path-only config and verify credential access**

Set `api_key_file` to the exact authorized external file and `cache_path` to `data/cache.db`. Confirm `git status --short` does not list `config.local.toml`.

- [ ] **Step 3: Run live contracts and inspect failures by endpoint**

Run in PowerShell:

```powershell
$env:RUN_LIVE_LAW_API = '1'
python -m pytest tests/integration/test_live_api.py -v
Remove-Item Env:RUN_LIVE_LAW_API
```

Expected: law, administrative-rule, Pyeongtaek/Gyeonggi ordinance, and term endpoints return schema-compatible data or an explicit approved-endpoint error. If a subscribed API is not approved for this credential, report that exact external limitation; do not silently remove the source.

- [ ] **Step 4: Write README with exact operating instructions**

Document Windows prerequisites, `config.local.toml` path-only setup, `run.bat`, `@region` syntax, ambiguity behavior, 24-hour cache, refresh, stale warnings, source ordering, and the legal caveat. Include only verified official URLs and retrieval date `2026-08-11`.

- [ ] **Step 5: Run the full automated suite**

Run: `python -m pytest -v`

Expected: all unit tests pass; live tests skip unless explicitly enabled; no warnings or collection errors.

- [ ] **Step 6: Run security and repository checks**

```powershell
git diff --check
git status --short
git grep -n -I -E "OC=|approved-key|top-secret" -- ':!tests/**' ':!docs/**'
Get-ChildItem -Recurse -File | Where-Object { $_.FullName -notmatch '\\.git\\|\\.venv\\' } | Select-String -SimpleMatch -Pattern 'G:\내 드라이브\01_AI개발\00_인증정보'
```

Expected: no whitespace errors; only intended tracked files; no credential values; the authorized directory appears only in ignored local config or user documentation if explicitly needed.

- [ ] **Step 7: Perform manual acceptance checks**

Use the approved eight-point acceptance list from the design: plain query excludes ordinances; `@평택` prioritizes Pyeongtaek and Gyeonggi; contexts/dates/current status/links show; repeated search uses cache; refresh performs live calls; restart preserves cache; `run.bat` works; credential is absent from project, SQLite, and logs.

- [ ] **Step 8: Commit**

```powershell
git add README.md tests/integration/test_live_api.py
git commit -m "test: verify live law search workflow"
```

---

## Final Verification

- [ ] Run `python -m pytest -v` and record the exact pass/skip counts.
- [ ] Run the opt-in live suite and record per-endpoint results without printing request URLs.
- [ ] Launch with `run.bat` and execute `주차 대수` and `@평택 주차 대수`.
- [ ] Confirm result order against the approved design.
- [ ] Confirm cache state changes from live to fresh cache and refresh back to live.
- [ ] Confirm official links resolve to `https://www.law.go.kr/`.
- [ ] Confirm no credential value exists in tracked files, cache bytes, terminal transcript, or logs.
- [ ] Run `git status --short` and ensure the only untracked/modified files are explicitly understood local runtime artifacts ignored by Git.
