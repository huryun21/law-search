from datetime import UTC, datetime

import pytest

from lawsearch.models import SearchResponse, SourceState


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
