from lawsearch.models import SearchResult, SourceState


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


def classify_candidates(
    candidates: tuple[tuple[SearchResult, SourceState], ...],
    keywords: tuple[str, ...] = PRIORITY_KEYWORDS,
) -> tuple[
    tuple[tuple[SearchResult, SourceState], ...],
    tuple[tuple[SearchResult, SourceState], ...],
]:
    """Split candidates into (priority, rest) by whether their title contains
    any of ``keywords``. This only affects verification *order* — it never
    decides whether a result is ultimately accepted."""
    if not keywords:
        return tuple(candidates), ()
    priority = []
    rest = []
    for item in candidates:
        result, _ = item
        if any(keyword in result.title for keyword in keywords):
            priority.append(item)
        else:
            rest.append(item)
    return tuple(priority), tuple(rest)
