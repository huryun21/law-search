from collections.abc import Iterable
from datetime import date

from lawsearch.models import Region, SearchResult, SourceGroup


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
    results: Iterable[SearchResult], region: Region | None
) -> tuple[SearchResult, ...]:
    source_order = _SOURCE_ORDER if region is not None else _NONREGIONAL_SOURCE_ORDER

    def key(result: SearchResult) -> tuple[object, ...]:
        effective = result.effective_date or date.min
        return (
            source_order[result.source],
            result.quality,
            not result.is_current,
            -effective.toordinal(),
            result.title.casefold(),
            result.uid,
        )

    return tuple(sorted(results, key=key))
