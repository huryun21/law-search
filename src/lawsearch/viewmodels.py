"""Streamlit-independent presentation logic for the search workspace.

This module must never import ``streamlit``. It turns a ``SearchResponse``
into the groups, cards, sidebar tree, and compare options the UI renders.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from lawsearch.models import (
    Region,
    SearchResponse,
    SearchResult,
    SearchScope,
    SourceGroup,
    SourceState,
)

_SEOUL = ZoneInfo("Asia/Seoul")
_SOURCE_ORDER = (
    SourceGroup.MUNICIPAL,
    SourceGroup.PROVINCIAL,
    SourceGroup.LAW,
    SourceGroup.DECREE,
    SourceGroup.MINISTERIAL_RULE,
    SourceGroup.ADMIN_RULE,
    SourceGroup.OTHER,
)
_SOURCE_KEYS = {
    SourceGroup.MUNICIPAL: "municipal",
    SourceGroup.PROVINCIAL: "provincial",
    SourceGroup.LAW: "laws",
    SourceGroup.DECREE: "laws",
    SourceGroup.MINISTERIAL_RULE: "laws",
    SourceGroup.ADMIN_RULE: "admin_rules",
    SourceGroup.OTHER: "laws",
}
_DEFAULT_LABELS = {
    SourceGroup.MUNICIPAL: "기초지자체 자치법규",
    SourceGroup.PROVINCIAL: "광역지자체 자치법규",
    SourceGroup.LAW: "법률",
    SourceGroup.DECREE: "대통령령",
    SourceGroup.MINISTERIAL_RULE: "부령",
    SourceGroup.ADMIN_RULE: "행정규칙",
    SourceGroup.OTHER: "기타 법령",
}
_SOURCE_LABELS = {
    "laws": "법령",
    "admin_rules": "행정규칙",
    "municipal": "기초지자체 자치법규",
    "provincial": "광역지자체 자치법규",
    "terms": "법령용어",
}
_STATE_MESSAGES = {
    SourceState.LIVE: "공식 API에서 방금 조회한 결과",
    SourceState.FRESH_CACHE: "24시간 이내 저장된 결과",
    SourceState.EMPTY: "검색 결과 없음",
    SourceState.ERROR: "이 출처를 조회하지 못했습니다. 다시 시도해 주세요.",
}


@dataclass(frozen=True)
class ResultGroupView:
    label: str
    results: tuple[SearchResult, ...]
    state: SourceState
    status_message: str
    fetched_at: datetime | None
    expanded: bool


def build_grouped_view(
    response: SearchResponse, region: Region | None = None
) -> tuple[ResultGroupView, ...]:
    """Build source groups without depending on Streamlit state."""
    grouped: list[tuple[int, ResultGroupView]] = []
    represented_sources: set[str] = set()
    regional_sources = {SourceGroup.MUNICIPAL, SourceGroup.PROVINCIAL}
    has_national_title_results = any(
        item.scope is SearchScope.TITLE and item.source not in regional_sources
        for item in response.results
    )
    for priority, source in enumerate(_SOURCE_ORDER):
        source_results = tuple(
            item for item in response.results if item.source is source
        )
        if not source_results:
            continue
        source_key = _SOURCE_KEYS[source]
        state = response.source_states.get(source_key, SourceState.EMPTY)
        fetched_at = response.source_fetched_at.get(
            source_key, min(item.fetched_at for item in source_results)
        )
        label = _group_label(source, source_results, region)
        title_results = tuple(
            item for item in source_results if item.scope is SearchScope.TITLE
        )
        body_results = tuple(
            item for item in source_results if item.scope is SearchScope.BODY
        )
        is_regional_source = region is not None and source in regional_sources
        if region is not None:
            title_priority = (
                priority * 2
                if is_regional_source
                else 4 + priority - len(regional_sources)
            )
        else:
            title_priority = priority
        if title_results:
            grouped.append(
                (
                    title_priority,
                    ResultGroupView(
                        label=label,
                        results=title_results,
                        state=state,
                        status_message=_status_message(state, fetched_at),
                        fetched_at=fetched_at,
                        expanded=True,
                    ),
                )
            )
        if body_results:
            is_additional = (
                bool(title_results)
                if is_regional_source
                else has_national_title_results
            )
            if is_regional_source:
                body_priority = title_priority + 1
            elif region is not None and is_additional:
                national_source_count = len(_SOURCE_ORDER) - len(regional_sources)
                body_priority = title_priority + national_source_count
            else:
                body_priority = (
                    len(_SOURCE_ORDER) + priority
                    if is_additional
                    else title_priority
                )
            grouped.append(
                (
                    body_priority,
                    ResultGroupView(
                        label=(
                            f"{label} · 본문 관련 추가 결과"
                            if is_additional
                            else label
                        ),
                        results=body_results,
                        state=state,
                        status_message=_status_message(state, fetched_at),
                        fetched_at=fetched_at,
                        expanded=not is_additional,
                    ),
                )
            )
        represented_sources.add(source_key)
    source_priority = {
        "municipal": 0,
        "provincial": 2,
        "laws": 4,
        "admin_rules": 10,
    }
    for source_key in ("municipal", "provincial", "laws", "admin_rules"):
        if source_key not in response.source_states or source_key in represented_sources:
            continue
        state = response.source_states[source_key]
        fetched_at = response.source_fetched_at.get(source_key)
        grouped.append(
            (
                source_priority[source_key],
                ResultGroupView(
                    label=_empty_source_label(source_key, region),
                    results=(),
                    state=state,
                    status_message=_status_message(state, fetched_at),
                    fetched_at=fetched_at,
                    expanded=False,
                ),
            )
        )
    return tuple(view for _, view in sorted(grouped, key=lambda item: item[0]))


def build_error_messages(response: SearchResponse) -> tuple[str, ...]:
    return tuple(
        f"{_SOURCE_LABELS.get(error.source, '공식 자료')}: "
        "조회하지 못했습니다. 새로고침으로 다시 시도해 주세요."
        for error in response.errors
    )


def detail_session_key(source: SourceGroup, uid: str, keyword: str) -> str:
    normalized = " ".join(keyword.split()).casefold()
    query_id = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"detail-{source.value}-{uid}-{query_id}"


def fully_qualified_region_name(region: Region) -> str:
    if region.municipality_name is None:
        return region.province_name
    return f"{region.province_name} / {region.municipality_name}"


def is_official_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    host = (parsed.hostname or "").casefold().rstrip(".")
    return (
        parsed.scheme == "https"
        and parsed.username is None
        and parsed.password is None
        and port in {None, 443}
        and (host == "law.go.kr" or host.endswith(".law.go.kr"))
    )


def format_timestamp(value: datetime) -> str:
    return value.astimezone(_SEOUL).strftime("%Y-%m-%d %H:%M:%S KST")


def _group_label(
    source: SourceGroup, results: tuple[SearchResult, ...], region: Region | None
) -> str:
    if source not in {SourceGroup.MUNICIPAL, SourceGroup.PROVINCIAL}:
        return _DEFAULT_LABELS[source]
    if region is not None:
        if source is SourceGroup.MUNICIPAL and region.municipality_name:
            return f"{region.municipality_name} 자치법규"
        if source is SourceGroup.PROVINCIAL:
            return f"{region.province_name} 자치법규"
    region_name = next((item.region_name for item in results if item.region_name), None)
    if region_name:
        return f"{region_name} 자치법규"
    return _empty_source_label(_SOURCE_KEYS[source], region)


def _empty_source_label(source_key: str, region: Region | None) -> str:
    if region is not None and source_key == "municipal" and region.municipality_name:
        return f"{region.municipality_name} 자치법규"
    if region is not None and source_key == "provincial":
        return f"{region.province_name} 자치법규"
    return _SOURCE_LABELS[source_key]


def _status_message(state: SourceState, fetched_at: datetime | None) -> str:
    if state is SourceState.STALE_FALLBACK:
        if fetched_at is None:
            raise ValueError("stale fallback requires a retrieval timestamp")
        return (
            "공식 API 오류로 이전 결과를 표시합니다. "
            f"조회 시각: {format_timestamp(fetched_at)}"
        )
    return _STATE_MESSAGES[state]


def result_key(result: SearchResult) -> str:
    return f"{result.source.value}:{result.uid}"


@dataclass(frozen=True)
class CardView:
    key: str
    title: str
    match_kind: str
    match_line: str | None
    official_url: str | None
    meta_fields: tuple[str, ...]


def card_view(result: SearchResult) -> CardView:
    fields = [result.category]
    if result.authority:
        fields.append(result.authority)
    fields.append("현행" if result.is_current else "연혁")
    if result.promulgation_date:
        fields.append(f"공포 {result.promulgation_date.isoformat()}")
    if result.effective_date:
        fields.append(f"시행 {result.effective_date.isoformat()}")
    return CardView(
        key=result_key(result),
        title=result.title,
        match_kind="제목 일치" if result.scope is SearchScope.TITLE else "본문 일치",
        match_line=result.match_context,
        official_url=result.official_url if is_official_url(result.official_url) else None,
        meta_fields=tuple(fields),
    )


def card_rows(
    results: Iterable[SearchResult], columns: int = 2
) -> tuple[tuple[CardView, ...], ...]:
    cards = [card_view(result) for result in results]
    return tuple(
        tuple(cards[start : start + columns])
        for start in range(0, len(cards), columns)
    )


_SIDEBAR_LOCAL_LABEL = "자치법규"
_SIDEBAR_NATIONAL_LABEL = "상위법령"
_LOCAL_SOURCES = (SourceGroup.MUNICIPAL, SourceGroup.PROVINCIAL)
_SIDEBAR_GROUP_LABELS = {
    SourceGroup.LAW: "법률",
    SourceGroup.DECREE: "대통령령(시행령)",
    SourceGroup.MINISTERIAL_RULE: "총리령·부령(시행규칙)",
    SourceGroup.ADMIN_RULE: "행정규칙",
    SourceGroup.OTHER: "기타 법령",
}


@dataclass(frozen=True)
class SidebarEntry:
    key: str
    title: str


@dataclass(frozen=True)
class SidebarGroup:
    label: str
    count: int
    entries: tuple[SidebarEntry, ...]


@dataclass(frozen=True)
class SidebarSection:
    label: str
    groups: tuple[SidebarGroup, ...]


def sidebar_sections(
    response: SearchResponse, region: Region | None = None
) -> tuple[SidebarSection, ...]:
    """Navigation tree over the ranked results. Never hides a result."""
    section_order: list[str] = []
    grouped: dict[str, dict[SourceGroup, list[SearchResult]]] = {}
    for result in response.results:
        section_label = (
            _SIDEBAR_LOCAL_LABEL
            if result.source in _LOCAL_SOURCES
            else _SIDEBAR_NATIONAL_LABEL
        )
        if section_label not in grouped:
            grouped[section_label] = {}
            section_order.append(section_label)
        grouped[section_label].setdefault(result.source, []).append(result)

    sections: list[SidebarSection] = []
    for section_label in section_order:
        groups = tuple(
            SidebarGroup(
                label=_sidebar_group_label(source, items, region),
                count=len(items),
                entries=tuple(
                    SidebarEntry(result_key(item), item.title) for item in items
                ),
            )
            for source, items in grouped[section_label].items()
        )
        sections.append(SidebarSection(section_label, groups))
    return tuple(sections)


def _sidebar_group_label(
    source: SourceGroup, items: list[SearchResult], region: Region | None
) -> str:
    if source in _LOCAL_SOURCES:
        return _group_label(source, tuple(items), region)
    return _SIDEBAR_GROUP_LABELS[source]


@dataclass(frozen=True)
class CompareOption:
    key: str
    label: str


def compare_options(response: SearchResponse) -> tuple[CompareOption, ...]:
    return tuple(
        CompareOption(
            key=result_key(result),
            label=f"{_DEFAULT_LABELS[result.source]} · {result.title}",
        )
        for result in response.results
    )
