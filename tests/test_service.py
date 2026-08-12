import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from lawsearch.cache import CacheStore, make_cache_key
from lawsearch.models import MatchQuality, ParsedQuery, Region, SourceGroup, SourceState
from lawsearch.service import SearchService, SearchValidationError


def run(awaitable):
    return asyncio.run(awaitable)


def empty_payload(source):
    wrapper = {"laws": "LawSearch", "admin_rules": "AdmRulSearch", "municipal": "OrdinSearch", "provincial": "OrdinSearch"}[source]
    return {wrapper: {"totalCnt": "0"}}


def test_nonregional_search_never_calls_ordinances(service_factory, parsed_plain):
    service, fake_api = service_factory()

    run(service.search(parsed_plain))

    assert fake_api.calls == {"laws", "admin_rules", "terms"}


def test_regional_search_calls_both_ordinance_levels_and_ranks_them_first(
    service_factory, parsed_pyeongtaek
):
    service, fake_api = service_factory()

    response = run(service.search(parsed_pyeongtaek))

    assert {"municipal", "provincial"} <= fake_api.calls
    assert [item.source for item in response.results[:2]] == [
        SourceGroup.MUNICIPAL,
        SourceGroup.PROVINCIAL,
    ]


def test_province_only_region_calls_no_municipal_source(service_factory):
    service, fake_api = service_factory()
    province = Region("경기도", None, "6410000")

    response = run(service.search(ParsedQuery("주차 단속", province)))

    assert "provincial" in fake_api.calls
    assert "municipal" not in fake_api.calls
    assert "provincial" in response.source_states
    assert "municipal" not in response.source_states
    assert not any(error.source == "municipal" for error in response.errors)


def test_ambiguous_candidates_fail_before_any_api_call(service_factory, pyeongtaek):
    service, fake_api = service_factory()

    with pytest.raises(SearchValidationError):
        run(service.search(ParsedQuery("주차", candidates=(pyeongtaek,))))

    assert fake_api.calls == set()


def test_fresh_cache_bypasses_api_but_refresh_forces_live_call(
    service_factory, parsed_plain
):
    service, fake_api = service_factory()
    first = run(service.search(parsed_plain))
    first_request_count = len(fake_api.requests)

    second = run(service.search(parsed_plain))
    assert len(fake_api.requests) == first_request_count
    assert second.source_states["laws"] is SourceState.FRESH_CACHE

    refreshed = run(service.search(parsed_plain, refresh=True))
    assert len(fake_api.requests) > first_request_count
    assert refreshed.source_states["laws"] is SourceState.LIVE
    assert first.results == refreshed.results


def test_partial_failure_returns_successes_and_source_error(
    service_factory, parsed_plain
):
    service, _ = service_factory(fail={"admin_rules"})

    response = run(service.search(parsed_plain))

    assert any(item.source is SourceGroup.LAW for item in response.results)
    assert response.source_states["admin_rules"] is SourceState.ERROR
    assert [(error.source, "failed" in error.message) for error in response.errors] == [
        ("admin_rules", True)
    ]


def test_api_failure_uses_only_matching_stale_cache(service_factory, parsed_plain):
    service, _ = service_factory(fail={"laws"}, stale={"laws"})

    response = run(service.search(parsed_plain))

    assert response.source_states["laws"] is SourceState.STALE_FALLBACK
    assert any(item.source is SourceGroup.LAW for item in response.results)
    assert response.errors[0].source == "laws"


def test_stale_retained_result_is_not_mislabeled_by_fresh_empty_variant(
    tmp_path, parsed_plain, load_fixture
):
    from conftest import FakeApi

    now = datetime(2026, 8, 11, tzinfo=UTC)
    stale_time = now - timedelta(days=2)
    cache = CacheStore(tmp_path / "mixed-fresh-stale.db")
    cache.put(
        make_cache_key("laws", "주차 단속", (), 1),
        empty_payload("laws"),
        now,
    )
    cache.put(
        make_cache_key("laws", "주차단속", (), 1),
        load_fixture("law-single.json"),
        stale_time,
    )
    api = FakeApi(fail={("laws", "주차단속")})
    service = SearchService(api, cache, lambda: now)

    response = run(service.search(parsed_plain))

    retained = next(item for item in response.results if item.uid == "001498")
    assert response.source_states["laws"] is SourceState.STALE_FALLBACK
    assert retained.fetched_at == stale_time


def test_stale_retained_result_is_not_mislabeled_by_live_empty_variant(
    tmp_path, parsed_plain, load_fixture
):
    from conftest import FakeApi

    now = datetime(2026, 8, 11, tzinfo=UTC)
    stale_time = now - timedelta(days=2)
    cache = CacheStore(tmp_path / "mixed-live-empty-stale.db")
    cache.put(
        make_cache_key("laws", "주차단속", (), 1),
        load_fixture("law-single.json"),
        stale_time,
    )
    api = FakeApi(
        fail={("laws", "주차단속")},
        responses={("laws", "주차 단속"): empty_payload("laws")},
    )
    service = SearchService(api, cache, lambda: now)

    response = run(service.search(parsed_plain))

    retained = next(item for item in response.results if item.uid == "001498")
    assert response.source_states["laws"] is SourceState.STALE_FALLBACK
    assert retained.fetched_at == stale_time


def test_stale_unique_result_is_not_mislabeled_by_live_duplicate(
    tmp_path, parsed_plain, load_fixture
):
    from conftest import FakeApi

    now = datetime(2026, 8, 11, tzinfo=UTC)
    stale_time = now - timedelta(days=2)
    cache = CacheStore(tmp_path / "mixed-live-stale.db")
    cache.put(
        make_cache_key("laws", "주차단속", (), 1),
        load_fixture("law-multiple.json"),
        stale_time,
    )
    api = FakeApi(
        fail={("laws", "주차단속")},
        responses={("laws", "주차 단속"): load_fixture("law-single.json")},
    )
    service = SearchService(api, cache, lambda: now)

    response = run(service.search(parsed_plain))

    decree = next(item for item in response.results if item.uid == "004743")
    assert response.source_states["laws"] is SourceState.STALE_FALLBACK
    assert decree.fetched_at == stale_time


def test_losing_stale_duplicate_does_not_taint_retained_fresh_result(
    tmp_path, parsed_plain, load_fixture
):
    from conftest import FakeApi

    now = datetime(2026, 8, 11, tzinfo=UTC)
    cache = CacheStore(tmp_path / "fresh-wins.db")
    cache.put(
        make_cache_key("laws", "주차 단속", (), 1),
        load_fixture("law-single.json"),
        now,
    )
    cache.put(
        make_cache_key("laws", "주차단속", (), 1),
        load_fixture("law-single.json"),
        now - timedelta(days=2),
    )
    service = SearchService(
        FakeApi(fail={("laws", "주차단속")}), cache, lambda: now
    )

    response = run(service.search(parsed_plain))

    assert response.source_states["laws"] is SourceState.FRESH_CACHE
    assert next(item for item in response.results if item.uid == "001498").fetched_at == now


def test_term_failure_is_independent_of_search_results(service_factory, parsed_plain):
    service, _ = service_factory(fail={"terms"})

    response = run(service.search(parsed_plain))

    assert response.results
    assert response.suggestions == ()
    assert any(error.source == "terms" for error in response.errors)


def test_live_sources_start_concurrently(tmp_path, parsed_plain):
    from conftest import FakeApi

    class ConcurrentApi(FakeApi):
        def __init__(self):
            super().__init__()
            self.started = 0
            self.ready = asyncio.Event()

        async def _wait_for_peer(self):
            self.started += 1
            if self.started == 2:
                self.ready.set()
            await asyncio.wait_for(self.ready.wait(), timeout=1)

        async def search_laws(self, query, page=1):
            if query == "주차 단속":
                await self._wait_for_peer()
            return await super().search_laws(query, page)

        async def search_admin_rules(self, query, page=1):
            if query == "주차 단속":
                await self._wait_for_peer()
            return await super().search_admin_rules(query, page)

    api = ConcurrentApi()
    service = SearchService(
        api,
        CacheStore(tmp_path / "concurrent.db"),
        lambda: datetime(2026, 8, 11, tzinfo=UTC),
    )

    response = run(service.search(parsed_plain))

    assert response.results
    assert api.started == 2


def test_unexpected_source_failure_is_isolated(tmp_path, parsed_plain):
    from conftest import FakeApi

    class BrokenAdminApi(FakeApi):
        async def search_admin_rules(self, query, page=1):
            raise RuntimeError("internal diagnostic must not escape")

    service = SearchService(
        BrokenAdminApi(),
        CacheStore(tmp_path / "isolated.db"),
        lambda: datetime(2026, 8, 11, tzinfo=UTC),
    )

    response = run(service.search(parsed_plain))

    assert any(item.source is SourceGroup.LAW for item in response.results)
    assert response.source_states["admin_rules"] is SourceState.ERROR
    assert response.errors[0].message == "admin_rules search failed"


def test_exact_and_compact_duplicates_keep_best_quality(
    service_factory, parsed_plain
):
    service, _ = service_factory()

    response = run(service.search(parsed_plain))

    law = next(item for item in response.results if item.uid == "001498")
    assert law.quality is MatchQuality.EXACT
    assert len([item for item in response.results if (item.source, item.uid) == (law.source, law.uid)]) == 1


def test_token_intersection_runs_only_after_both_variants_are_empty(
    service_factory, parsed_plain, load_fixture
):
    responses = {}
    for operation in ("laws", "admin_rules"):
        responses[(operation, "주차 단속")] = empty_payload(operation)
        responses[(operation, "주차단속")] = empty_payload(operation)
    responses[("laws", "주차")] = load_fixture("law-multiple.json")
    responses[("laws", "단속")] = load_fixture("law-single.json")
    responses[("admin_rules", "주차")] = empty_payload("admin_rules")
    responses[("admin_rules", "단속")] = empty_payload("admin_rules")
    service, fake_api = service_factory(responses=responses)

    response = run(service.search(parsed_plain))

    assert ("laws", "주차") in fake_api.requests
    assert ("laws", "단속") in fake_api.requests
    assert [(item.uid, item.quality) for item in response.results] == [
        ("001498", MatchQuality.ALL_TERMS)
    ]


def test_token_calls_are_skipped_when_exact_or_compact_has_a_hit(
    service_factory, parsed_plain
):
    service, fake_api = service_factory()

    run(service.search(parsed_plain))

    assert not any(query in {"주차", "단속"} for _, query in fake_api.requests)


def test_detail_is_lazy_cached_refreshable_and_returns_bounded_contexts(
    tmp_path, result_factory
):
    from conftest import FakeApi

    now = datetime(2026, 8, 11, tzinfo=UTC)
    current = [now]
    api = FakeApi()
    service = SearchService(api, CacheStore(tmp_path / "detail.db"), lambda: current[0])
    result = result_factory(SourceGroup.LAW, uid="detail-law")

    first = run(service.load_contexts(result, "주차 단속"))
    second = run(service.load_contexts(result, "주차 단속"))
    assert first.contexts == ("앞 문장. 주차 단속 근거 조문. 뒤 문장.",)
    assert second.state is SourceState.FRESH_CACHE
    assert [operation for operation, _ in api.requests].count("detail") == 1

    current[0] += timedelta(days=2)
    run(service.load_contexts(result, "주차 단속"))
    assert [operation for operation, _ in api.requests].count("detail") == 2

    run(service.load_contexts(result, "주차 단속", refresh=True))
    assert [operation for operation, _ in api.requests].count("detail") == 3


def test_detail_uses_stale_only_after_api_failure(tmp_path, result_factory):
    from conftest import FakeApi

    now = datetime(2026, 8, 11, tzinfo=UTC)
    current = [now]
    api = FakeApi()
    service = SearchService(api, CacheStore(tmp_path / "detail-stale.db"), lambda: current[0])
    result = result_factory(SourceGroup.LAW, uid="detail-stale")
    run(service.load_contexts(result, "주차 단속"))
    current[0] += timedelta(days=2)
    api.fail.add("detail")

    response = run(service.load_contexts(result, "주차 단속"))

    assert response.state is SourceState.STALE_FALLBACK
    assert response.fetched_at == now


def test_unexpected_detail_failure_without_cache_returns_safe_error(
    tmp_path, result_factory
):
    from conftest import FakeApi

    class BrokenDetailApi(FakeApi):
        async def fetch_detail(self, result):
            raise RuntimeError("private adapter diagnostic")

    now = datetime(2026, 8, 11, tzinfo=UTC)
    service = SearchService(
        BrokenDetailApi(), CacheStore(tmp_path / "detail-error.db"), lambda: now
    )

    response = run(
        service.load_contexts(result_factory(SourceGroup.LAW), "주차 단속")
    )

    assert response.contexts == ()
    assert response.state is SourceState.ERROR
    assert response.fetched_at == now


def test_unexpected_detail_failure_uses_stale_cache(tmp_path, result_factory):
    from conftest import FakeApi

    class BrokenDetailApi(FakeApi):
        async def fetch_detail(self, result):
            raise RuntimeError("private adapter diagnostic")

    now = datetime(2026, 8, 11, tzinfo=UTC)
    current = [now]
    api = FakeApi()
    cache = CacheStore(tmp_path / "detail-runtime-stale.db")
    service = SearchService(api, cache, lambda: current[0])
    result = result_factory(SourceGroup.LAW, uid="detail-runtime-stale")
    run(service.load_contexts(result, "주차 단속"))
    current[0] += timedelta(days=2)
    service = SearchService(BrokenDetailApi(), cache, lambda: current[0])

    response = run(service.load_contexts(result, "주차 단속"))

    assert response.state is SourceState.STALE_FALLBACK
    assert response.fetched_at == now


def test_fresh_detail_bypasses_failure_but_refresh_falls_back_safely(
    tmp_path, result_factory
):
    from conftest import FakeApi

    class BrokenDetailApi(FakeApi):
        def __init__(self):
            super().__init__()
            self.detail_attempts = 0

        async def fetch_detail(self, result):
            self.detail_attempts += 1
            raise RuntimeError("private adapter diagnostic")

    now = datetime(2026, 8, 11, tzinfo=UTC)
    cache = CacheStore(tmp_path / "detail-refresh-failure.db")
    result = result_factory(SourceGroup.LAW, uid="detail-refresh-failure")
    seeded = SearchService(FakeApi(), cache, lambda: now)
    run(seeded.load_contexts(result, "주차 단속"))
    broken = BrokenDetailApi()
    service = SearchService(broken, cache, lambda: now)

    fresh = run(service.load_contexts(result, "주차 단속"))
    refreshed = run(service.load_contexts(result, "주차 단속", refresh=True))

    assert fresh.state is SourceState.FRESH_CACHE
    assert refreshed.state is SourceState.STALE_FALLBACK
    assert refreshed.fetched_at == now
    assert broken.detail_attempts == 1
