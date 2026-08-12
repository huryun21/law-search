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


@pytest.mark.parametrize("token", ["전남광주", "제물포", "영종", "검단"])
def test_current_2026_region_tokens_are_searchable(token):
    parsed = parse_query(f"@{token} 주차 대수", RegionRegistry.from_package_data())
    assert parsed.keyword == "주차 대수"
    assert parsed.region is not None


def test_legacy_split_region_stops_search_and_returns_candidates():
    parsed = parse_query("@인천/중구 주차 대수", RegionRegistry.from_package_data())
    assert parsed.region is None
    assert {item.municipality_name for item in parsed.candidates} == {"영종구", "제물포구"}


def test_multiple_region_tokens_are_rejected():
    with pytest.raises(QueryError, match="하나"):
        parse_query("@평택 @수원 주차", RegionRegistry.from_package_data())


def test_spaced_keyword_builds_exact_and_compact_variants():
    variants = build_query_variants("주차 대수")
    assert [(item.query, item.quality.name) for item in variants[:2]] == [
        ("주차 대수", "EXACT"),
        ("주차대수", "COMPACT"),
    ]
