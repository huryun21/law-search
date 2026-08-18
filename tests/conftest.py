import json
from copy import deepcopy
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from lawsearch.api import ApiError
from lawsearch.cache import CacheStore, make_cache_key
from lawsearch.models import MatchQuality, ParsedQuery, Region, SearchResult, SourceGroup
from lawsearch.regions import RegionRegistry


def load_fixture(name: str) -> dict:
    return json.loads((Path(__file__).parent / "fixtures" / name).read_text(encoding="utf-8"))


@pytest.fixture(name="load_fixture")
def load_fixture_fixture():
    return load_fixture


@pytest.fixture
def pyeongtaek() -> Region:
    resolution = RegionRegistry.from_package_data().resolve("평택")
    assert resolution.region is not None
    return resolution.region


@pytest.fixture
def result_factory():
    def make_result(
        source: SourceGroup,
        *,
        uid: str | None = None,
        quality: MatchQuality = MatchQuality.EXACT,
        effective: str | None = "20260811",
        current: bool = True,
        title: str | None = None,
    ) -> SearchResult:
        effective_date = (
            date.fromisoformat(f"{effective[:4]}-{effective[4:6]}-{effective[6:]}")
            if effective
            else None
        )
        return SearchResult(
            uid=uid or source.value,
            source=source,
            quality=quality,
            title=title or source.value,
            category=source.value,
            authority=None,
            region_name=None,
            promulgation_date=None,
            effective_date=effective_date,
            is_current=current,
            official_url="https://www.law.go.kr/example",
            fetched_at=datetime(2026, 8, 11, tzinfo=UTC),
        )

    return make_result


class FakeApi:
    def __init__(self, fail=(), responses=None):
        self.calls: set[str] = set()
        self.requests: list[tuple[str, str]] = []
        self.fail = set(fail)
        self.responses = responses or {}
        self.detail_payload = {"body": "앞 문장. 주차 단속 근거 조문. 뒤 문장."}

    def _search(self, operation: str, query: str, fixture: str):
        self.calls.add(operation)
        self.requests.append((operation, query))
        if operation in self.fail or (operation, query) in self.fail:
            raise ApiError(f"{operation} failed safely")
        configured = self.responses.get((operation, query))
        if configured is not None:
            return deepcopy(configured)
        return load_fixture(fixture)

    async def search_laws(self, query: str, page: int = 1):
        return self._search("laws", query, "law-multiple.json")

    async def search_admin_rules(self, query: str, page: int = 1):
        return self._search("admin_rules", query, "admrul.json")

    async def search_ordinances(self, query, region, province_only, page=1):
        operation = "provincial" if province_only else "municipal"
        fixture = "ordin-provincial.json" if province_only else "ordin.json"
        return self._search(operation, query, fixture)

    async def suggest_terms(self, query: str):
        self.calls.add("terms")
        self.requests.append(("terms", query))
        if "terms" in self.fail:
            raise ApiError("terms failed safely")
        return ("주차장", "부설주차장")

    async def fetch_detail(self, result):
        self.calls.add("detail")
        self.requests.append(("detail", result.uid))
        if "detail" in self.fail:
            raise ApiError("detail failed safely")
        return deepcopy(self.detail_payload)


@pytest.fixture
def parsed_plain() -> ParsedQuery:
    return ParsedQuery("주차 단속")


@pytest.fixture
def parsed_pyeongtaek(pyeongtaek) -> ParsedQuery:
    return ParsedQuery("주차 단속", pyeongtaek)


@pytest.fixture
def service_factory(tmp_path):
    from lawsearch.service import SearchService

    now = datetime(2026, 8, 11, 12, tzinfo=UTC)

    def make_service(*, fail=(), stale=(), responses=None):
        api = FakeApi(fail, responses)
        cache = CacheStore(tmp_path / f"cache-{len(list(tmp_path.iterdir()))}.db")
        service = SearchService(api, cache, lambda: now)
        for source in stale:
            fixture = {
                "laws": "law-multiple.json",
                "admin_rules": "admrul.json",
                "municipal": "ordin.json",
                "provincial": "ordin-provincial.json",
            }[source]
            region_codes = {
                "municipal": ("6410000", "3910000"),
                "provincial": ("6410000",),
            }.get(source, ())
            cache.put(
                make_cache_key(source, "주차 단속", region_codes, 1),
                load_fixture(fixture),
                now.replace(day=9),
            )
        return service, api

    return make_service
