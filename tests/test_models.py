from datetime import UTC, datetime

import pytest

from lawsearch.models import (
    MatchQuality,
    SearchResponse,
    SearchResult,
    SourceGroup,
    SourceState,
)


def make_response(states, fetched_at):
    return SearchResponse(
        results=(),
        suggestions=(),
        errors=(),
        source_states=states,
        source_fetched_at=fetched_at,
    )


@pytest.mark.parametrize(
    "state",
    (
        SourceState.LIVE,
        SourceState.EMPTY,
        SourceState.FRESH_CACHE,
        SourceState.STALE_FALLBACK,
    ),
)
def test_non_error_source_requires_retrieval_timestamp(state):
    with pytest.raises(ValueError, match="retrieval timestamp"):
        make_response({"laws": state}, {})


def test_error_source_permits_missing_retrieval_timestamp():
    response = make_response({"laws": SourceState.ERROR}, {})

    assert response.source_fetched_at == {}


def test_retrieval_timestamp_key_must_have_source_state():
    with pytest.raises(ValueError, match="source state"):
        make_response(
            {},
            {"laws": datetime(2026, 8, 11, tzinfo=UTC)},
        )


def test_retrieval_timestamp_must_be_timezone_aware():
    with pytest.raises(ValueError, match="timezone-aware"):
        make_response(
            {"laws": SourceState.LIVE},
            {"laws": datetime(2026, 8, 11)},
        )


def test_search_result_defaults_match_context_to_none():
    result = SearchResult(
        uid="001498",
        source=SourceGroup.LAW,
        quality=MatchQuality.EXACT,
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
