import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from lawsearch.cache import CacheStore, make_cache_key
from lawsearch.models import (
    MatchQuality,
    ParsedQuery,
    Region,
    SearchScope,
    SourceGroup,
    SourceState,
)
from lawsearch.service import SearchService, SearchValidationError


def run(awaitable):
    return asyncio.run(awaitable)


def empty_payload(source):
    wrapper = {"laws": "LawSearch", "admin_rules": "AdmRulSearch", "municipal": "OrdinSearch", "provincial": "OrdinSearch"}[source]
    return {wrapper: {"totalCnt": "0"}}


def ordinance_payload(*authorities):
    records = [
        {
            "자치법규일련번호": str(1_900_000 + index),
            "자치법규명": f"{authority} 주차 조례",
            "자치법규ID": str(2_040_000 + index),
            "공포일자": "20250701",
            "공포번호": str(index),
            "지자체기관명": authority,
            "자치법규종류": "조례",
            "시행일자": "20250701",
            "자치법규상세링크": f"/자치법규/{2_040_000 + index}",
        }
        for index, authority in enumerate(authorities, 1)
    ]
    return {
        "OrdinSearch": {
            "target": "ordin",
            "키워드": "주차 대수",
            "section": "bdyText",
            "totalCnt": str(len(records)),
            "page": "1",
            "law": records,
        }
    }


def test_nonregional_search_never_calls_ordinances(service_factory, parsed_plain):
    service, fake_api = service_factory()

    run(service.search(parsed_plain))

    assert {
        "laws_titles",
        "laws",
        "admin_rules_titles",
        "admin_rules",
        "terms",
    } <= fake_api.calls
    assert not {"municipal", "municipal_titles", "provincial", "provincial_titles"} & fake_api.calls


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


def test_provincial_results_exclude_subordinate_municipalities(
    service_factory, parsed_pyeongtaek
):
    mixed = ordinance_payload("경기도", "경기도 광명시", "경기도 평택시")
    service, _ = service_factory(
        responses={
            ("provincial", "주차 대수"): mixed,
            ("provincial", "주차대수"): mixed,
        }
    )

    response = run(
        service.search(ParsedQuery("주차 대수", parsed_pyeongtaek.region))
    )

    authorities = {
        item.authority
        for item in response.results
        if item.source is SourceGroup.PROVINCIAL
    }
    assert authorities == {"경기도"}


def test_provincial_filter_applies_to_fresh_cached_payload(
    tmp_path, parsed_pyeongtaek
):
    from conftest import FakeApi

    now = datetime(2026, 8, 11, tzinfo=UTC)
    mixed = ordinance_payload("경기도", "경기도 광명시", "경기도 평택시")
    cache = CacheStore(tmp_path / "provincial-fresh.db")
    for query in ("주차 대수", "주차대수"):
        cache.put(
            make_cache_key("provincial", query, ("6410000",), 1),
            mixed,
            now,
        )
    service = SearchService(FakeApi(), cache, lambda: now)

    response = run(
        service.search(ParsedQuery("주차 대수", parsed_pyeongtaek.region))
    )

    authorities = {
        item.authority
        for item in response.results
        if item.source is SourceGroup.PROVINCIAL
    }
    assert authorities == {"경기도"}
    assert response.source_states["provincial"] is SourceState.FRESH_CACHE


def test_provincial_filter_applies_to_stale_fallback_payload(
    tmp_path, parsed_pyeongtaek
):
    from conftest import FakeApi

    now = datetime(2026, 8, 11, tzinfo=UTC)
    stale_time = now - timedelta(days=2)
    mixed = ordinance_payload("경기도", "경기도 광명시", "경기도 평택시")
    cache = CacheStore(tmp_path / "provincial-stale.db")
    queries = ("주차 대수", "주차대수")
    for query in queries:
        cache.put(
            make_cache_key("provincial", query, ("6410000",), 1),
            mixed,
            stale_time,
        )
    service = SearchService(
        FakeApi(fail={("provincial", query) for query in queries}),
        cache,
        lambda: now,
    )

    response = run(
        service.search(ParsedQuery("주차 대수", parsed_pyeongtaek.region))
    )

    authorities = {
        item.authority
        for item in response.results
        if item.source is SourceGroup.PROVINCIAL
    }
    assert authorities == {"경기도"}
    assert response.source_states["provincial"] is SourceState.STALE_FALLBACK


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


def test_zero_result_stale_source_preserves_cache_retrieval_timestamp(tmp_path):
    from conftest import FakeApi

    now = datetime(2026, 8, 11, tzinfo=UTC)
    stale_time = now - timedelta(days=2)
    cache = CacheStore(tmp_path / "zero-result-stale.db")
    cache.put(make_cache_key("laws", "미검색", (), 1), empty_payload("laws"), stale_time)
    service = SearchService(FakeApi(fail={"laws"}), cache, lambda: now)

    response = run(service.search(ParsedQuery("미검색")))

    assert response.source_states["laws"] is SourceState.STALE_FALLBACK
    assert response.source_fetched_at["laws"] == stale_time


def test_zero_result_live_source_records_response_clock(service_factory):
    now = datetime(2026, 8, 11, 12, tzinfo=UTC)
    responses = {
        (source, query): empty_payload(source)
        for source in ("laws", "admin_rules")
        for query in ("미검색",)
    }
    service, _ = service_factory(responses=responses)

    response = run(service.search(ParsedQuery("미검색")))

    assert response.source_states["laws"] is SourceState.EMPTY
    assert response.source_fetched_at["laws"] == now


def test_live_source_timestamp_is_captured_after_api_response(tmp_path):
    from conftest import FakeApi

    before = datetime(2026, 8, 11, 11, 59, tzinfo=UTC)
    received = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    readings = iter((before, received))

    def clock():
        return next(readings, received)

    service = SearchService(
        FakeApi(), CacheStore(tmp_path / "response-clock.db"), clock
    )

    response = run(service.search(ParsedQuery("주차")))

    assert response.source_fetched_at["laws"] == received


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

        async def search_laws(self, query, page=1, *, title_only=False):
            if query == "주차 단속" and title_only:
                await self._wait_for_peer()
            return await super().search_laws(query, page, title_only=title_only)

        async def search_admin_rules(self, query, page=1, *, title_only=False):
            if query == "주차 단속" and title_only:
                await self._wait_for_peer()
            return await super().search_admin_rules(
                query, page, title_only=title_only
            )

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
        async def search_admin_rules(self, query, page=1, *, title_only=False):
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


def test_title_search_is_separate_and_wins_duplicate_body_result(
    service_factory, parsed_plain, load_fixture
):
    title_payload = load_fixture("law-single.json")
    title_payload["LawSearch"]["law"]["법령명한글"] = "주차 단속법"
    service, fake_api = service_factory(
        responses={
            ("laws_titles", "주차 단속"): title_payload,
        }
    )

    response = run(service.search(parsed_plain))

    law = next(item for item in response.results if item.uid == "001498")
    assert ("laws_titles", "주차 단속") in fake_api.requests
    assert ("laws", "주차 단속") in fake_api.requests
    assert law.scope is SearchScope.TITLE


def test_body_search_keeps_only_results_with_a_matching_article(
    tmp_path, load_fixture
):
    from conftest import FakeApi

    false_hit = dict(
        load_fixture("law-single.json")["LawSearch"]["law"],
        법령일련번호="273401",
        법령명한글="자연공원법",
        법령ID="001837",
        법령상세링크="/법령/자연공원법",
    )
    true_hit = dict(
        false_hit,
        법령일련번호="273399",
        법령명한글="건축법 시행령",
        법령ID="004743",
        법령구분명="대통령령",
        법령상세링크="/법령/건축법시행령",
    )
    body_payload = {
        "LawSearch": {
            "target": "eflaw",
            "키워드": "방화구획",
            "section": "bdyText",
            "totalCnt": "2",
            "page": "1",
            "law": [false_hit, true_hit],
        }
    }
    loose_title_payload = {
        "LawSearch": {
            "target": "eflaw",
            "키워드": "방화구획",
            "section": "lawNm",
            "totalCnt": "1",
            "page": "1",
            "law": false_hit,
        }
    }
    detail_payloads = {
        "001837": {
            "법령": {
                "조문": {
                    "조문단위": {
                        "조문번호": "18",
                        "조문제목": "용도지구",
                        "조문내용": "제18조(용도지구)",
                        "항": {
                            "항번호": "②",
                            "항내용": "② 공원자연보존지구에서 허용되는 행위",
                            "호": {
                                "호번호": "2.",
                                "호내용": "2. 공원시설의 설치",
                                "목": {
                                    "목번호": "사.",
                                    "목내용": "사. 사방ㆍ호안ㆍ방화ㆍ방책 시설의 설치",
                                },
                            },
                        },
                    }
                }
            }
        },
        "004743": {
            "법령": {
                "조문": {
                    "조문단위": {
                        "조문번호": "46",
                        "조문제목": "방화구획 등의 설치",
                        "조문내용": "제46조(방화구획 등의 설치) 주요구조부를 방화구획으로 구획하여야 한다.",
                    }
                }
            }
        },
    }

    class ArticleApi(FakeApi):
        async def fetch_detail(self, result):
            self.calls.add("detail")
            self.requests.append(("detail", result.uid))
            return detail_payloads[result.uid]

    responses = {
        ("laws_titles", "방화구획"): loose_title_payload,
        ("laws", "방화구획"): body_payload,
        ("admin_rules", "방화구획"): empty_payload("admin_rules"),
    }
    api = ArticleApi(responses=responses)
    service = SearchService(
        api,
        CacheStore(tmp_path / "verified-body.db"),
        lambda: datetime(2026, 8, 18, tzinfo=UTC),
    )

    response = run(service.search(ParsedQuery("방화구획")))

    assert "자연공원법" not in {item.title for item in response.results}
    assert "건축법 시행령" in {item.title for item in response.results}


def test_body_verification_failure_never_exposes_unverified_results(
    service_factory, parsed_plain
):
    service, _ = service_factory(fail={"detail"})

    response = run(service.search(parsed_plain))

    assert response.results == ()
    assert response.source_states == {
        "laws": SourceState.ERROR,
        "admin_rules": SourceState.ERROR,
    }
    assert {error.source for error in response.errors} == {"laws", "admin_rules"}


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
        r
        for r in response.results
        if r.uid == "001498" and r.scope is SearchScope.TITLE
    )
    assert law.match_context is None


def test_load_contexts_limit_is_forwarded(service_factory, result_factory):
    service, _ = service_factory()
    result = result_factory(SourceGroup.LAW, uid="001498")

    one = run(service.load_contexts(result, "주차", limit=1))

    assert len(one.contexts) <= 1


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


@pytest.mark.parametrize(
    ("keyword", "fresh_token", "stale_token"),
    [
        ("주차 단속", "주차", "단속"),
        ("단속 주차", "주차", "단속"),
    ],
    ids=("fresh-contributor-first", "stale-contributor-first"),
)
def test_token_intersection_uses_oldest_contributor_timestamp_per_result(
    tmp_path,
    load_fixture,
    keyword,
    fresh_token,
    stale_token,
):
    from conftest import FakeApi

    now = datetime(2026, 8, 11, tzinfo=UTC)
    stale_time = now - timedelta(days=2)
    cache = CacheStore(tmp_path / f"token-times-{keyword.replace(' ', '-')}.db")
    cache.put(
        make_cache_key("laws", fresh_token, (), 1),
        load_fixture("law-multiple.json"),
        now,
    )
    cache.put(
        make_cache_key("laws", stale_token, (), 1),
        load_fixture("law-multiple.json"),
        stale_time,
    )
    responses = {
        ("laws", keyword): empty_payload("laws"),
        ("laws", keyword.replace(" ", "")): empty_payload("laws"),
    }
    service = SearchService(
        FakeApi(fail={("laws", stale_token)}, responses=responses),
        cache,
        lambda: now,
    )

    response = run(service.search(ParsedQuery(keyword)))

    intersected = {
        item.uid: item for item in response.results if item.quality is MatchQuality.ALL_TERMS
    }
    assert response.source_states["laws"] is SourceState.STALE_FALLBACK
    assert set(intersected) == {"001498", "004743"}
    assert {item.fetched_at for item in intersected.values()} == {stale_time}
    assert intersected["001498"].title == "주차장법"
    assert intersected["004743"].source is SourceGroup.DECREE


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
    assert first.contexts == (
        "제1조(단속 근거) — 앞 문장. 주차 단속 근거 조문. 뒤 문장.",
    )
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
