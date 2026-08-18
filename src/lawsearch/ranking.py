from collections.abc import Iterable
from datetime import date
import re

from lawsearch.models import Region, SearchResult, SearchScope, SourceGroup


_SOURCE_ORDER = {
    SourceGroup.MUNICIPAL: 0,
    SourceGroup.PROVINCIAL: 1,
    SourceGroup.LAW: 2,
    SourceGroup.DECREE: 3,
    SourceGroup.MINISTERIAL_RULE: 4,
    SourceGroup.ADMIN_RULE: 5,
    SourceGroup.OTHER: 6,
}

_NONREGIONAL_SOURCE_ORDER = {
    SourceGroup.LAW: 0,
    SourceGroup.DECREE: 1,
    SourceGroup.MINISTERIAL_RULE: 2,
    SourceGroup.ADMIN_RULE: 3,
    SourceGroup.OTHER: 4,
    SourceGroup.MUNICIPAL: 5,
    SourceGroup.PROVINCIAL: 6,
}


def rank_results(
    results: Iterable[SearchResult], region: Region | None, keyword: str = ""
) -> tuple[SearchResult, ...]:
    source_order = _SOURCE_ORDER if region is not None else _NONREGIONAL_SOURCE_ORDER

    def key(result: SearchResult) -> tuple[object, ...]:
        effective = result.effective_date or date.min
        return (
            source_order[result.source],
            0 if result.scope is SearchScope.TITLE else 1,
            _title_relevance(result.title, keyword),
            result.quality,
            not result.is_current,
            -effective.toordinal(),
            result.title.casefold(),
            result.uid,
        )

    return tuple(sorted(results, key=key))


def _title_relevance(title: str, keyword: str) -> int:
    normalized_title = _compact(title)
    normalized_keyword = _compact(keyword)
    if not normalized_keyword:
        return 0
    if normalized_title == normalized_keyword:
        return 0
    if normalized_title.startswith(normalized_keyword):
        return 1
    if normalized_keyword in normalized_title:
        return 2
    tokens = tuple(_compact(token) for token in keyword.split() if _compact(token))
    if tokens and all(token in normalized_title for token in tokens):
        return 3
    return 4


def _compact(value: str) -> str:
    return re.sub(r"[^\w]", "", value.casefold())
