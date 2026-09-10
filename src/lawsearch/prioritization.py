from lawsearch.models import SearchResult, SearchScope, SourceState


PRIORITY_KEYWORDS: tuple[str, ...] = (
    # 정비사업 핵심
    "도시", "주택", "주거", "정비", "재건축", "재개발", "도심",
    # 인허가·계획
    "국토", "개발", "건축", "택지", "혁신도시", "공업지역", "부동산",
    # 기반시설·설비
    "도로", "하천", "수도", "하수도", "공원", "녹지", "교통", "주차장",
    "설비", "전력", "에너지",
    # 안전·재난
    "소방", "화재", "재난", "위험물", "안전관리", "승강기", "다중이용업소",
    # 환경·자연
    "환경", "산지", "산림", "농지",
    # 행정·재무
    "조세", "감정평가", "건설산업",
    # 기타
    "문화재", "장애인",
)


def _title_matches(title: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in title for keyword in keywords)


_MAX_TITLE_SCOPE_PRIORITY = 50
# A generic keyword (e.g. "심의") can be an exact TITLE match for hundreds of
# documents nationwide, since it's a component of countless committee/review
# clause titles. Verifying every one of them synchronously, before the page
# ever renders, turned a fast search into a multi-minute block for exactly
# such keywords. Past this many, the overflow still goes through the normal
# background queue -- verified soon after render, just not blocking it.


def classify_candidates(
    candidates: tuple[tuple[SearchResult, SourceState], ...],
    keywords: tuple[str, ...] = PRIORITY_KEYWORDS,
    *,
    max_title_priority: int | None = _MAX_TITLE_SCOPE_PRIORITY,
) -> tuple[
    tuple[tuple[SearchResult, SourceState], ...],
    tuple[tuple[SearchResult, SourceState], ...],
]:
    """Split candidates into (priority, rest) by whether their title contains
    any of ``keywords``. This only affects verification *order* — it never
    decides whether a result is ultimately accepted.

    A TITLE-scope result is priority regardless of keywords: it means the
    user's own search term is in the document's title, the app's highest
    priority match (정확 문구 우선), not merely one that happens to fall in a
    domain this list was tuned for. That's uncapped for domain-keyword body
    matches (unchanged, existing behavior) but bounded for TITLE-scope by
    ``max_title_priority``, for the reason above."""
    if not keywords:
        return tuple(candidates), ()
    priority = []
    overflow = []
    rest = []
    title_priority_count = 0
    for item in candidates:
        result, _ = item
        is_title = result.scope is SearchScope.TITLE
        if is_title or _title_matches(result.title, keywords):
            if (
                is_title
                and max_title_priority is not None
                and title_priority_count >= max_title_priority
            ):
                overflow.append(item)
            else:
                priority.append(item)
                if is_title:
                    title_priority_count += 1
        else:
            rest.append(item)
    return tuple(priority), tuple(overflow) + tuple(rest)


def split_by_relevance(
    results: tuple[SearchResult, ...],
    keywords: tuple[str, ...] = PRIORITY_KEYWORDS,
) -> tuple[tuple[SearchResult, ...], tuple[SearchResult, ...]]:
    """Split already-verified body-match results into (relevant, less_relevant)
    by whether their title contains any of ``keywords``. This is a display
    grouping only — it never decides whether a result is an exact match, and
    it must never be applied to title-scope results (the user asked for that
    law by name, so it is always relevant regardless of domain keywords)."""
    if not keywords:
        return tuple(results), ()
    relevant = []
    less_relevant = []
    for result in results:
        if _title_matches(result.title, keywords):
            relevant.append(result)
        else:
            less_relevant.append(result)
    return tuple(relevant), tuple(less_relevant)
