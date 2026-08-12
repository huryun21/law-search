from copy import deepcopy
from datetime import UTC, datetime

import pytest

from lawsearch.models import MatchQuality, SourceGroup
from lawsearch.normalize import ResponseShapeError, normalize_results


FETCHED_AT = datetime(2026, 8, 11, tzinfo=UTC)


def test_single_law_object_is_normalized_without_mutating_fixture(load_fixture):
    payload = load_fixture("law-single.json")
    original = deepcopy(payload)

    results = normalize_results(payload, SourceGroup.LAW, MatchQuality.EXACT, FETCHED_AT)

    assert payload == original
    assert len(results) == 1
    assert results[0].uid == "001498"
    assert results[0].title == "주차장법"
    assert results[0].source is SourceGroup.LAW
    assert results[0].official_url == "https://www.law.go.kr/법령/주차장법"
    assert results[0].promulgation_date.isoformat() == "2025-01-31"
    assert results[0].effective_date.isoformat() == "2025-08-01"
    assert results[0].is_current is True


def test_multiple_laws_are_normalized_and_classified(load_fixture):
    results = normalize_results(load_fixture("law-multiple.json"), SourceGroup.LAW, MatchQuality.COMPACT, FETCHED_AT)

    assert [(item.title, item.source, item.quality) for item in results] == [
        ("주차장법", SourceGroup.LAW, MatchQuality.COMPACT),
        ("주차장법 시행령", SourceGroup.DECREE, MatchQuality.COMPACT),
    ]


def test_admin_rule_optional_dates_and_authority_are_normalized(load_fixture):
    result = normalize_results(load_fixture("admrul.json"), SourceGroup.ADMIN_RULE, MatchQuality.EXACT, FETCHED_AT)[0]

    assert result.authority == "국토교통부"
    assert result.promulgation_date.isoformat() == "2025-07-01"
    assert result.region_name is None


def test_ordinance_has_authority_region_and_effective_date(load_fixture):
    result = normalize_results(load_fixture("ordin.json"), SourceGroup.MUNICIPAL, MatchQuality.EXACT, FETCHED_AT)[0]

    assert result.authority == "평택시"
    assert result.region_name == "평택시"
    assert result.effective_date.isoformat() == "2025-07-01"


@pytest.mark.parametrize(
    "payload",
    [
        {"Unknown": {"law": []}},
        {"LawSearch": {"law": {"법령ID": "1", "법령상세링크": "/법령/가"}}},
        {"LawSearch": {"law": {"법령ID": "1", "법령명한글": "가", "법령상세링크": "https://example.com/가"}}},
    ],
)
def test_unrecognized_or_unsafe_response_raises_source_only_error(payload):
    with pytest.raises(ResponseShapeError) as caught:
        normalize_results(payload, SourceGroup.LAW, MatchQuality.EXACT, FETCHED_AT)

    assert str(caught.value) == "law 응답 형식을 처리할 수 없습니다."
