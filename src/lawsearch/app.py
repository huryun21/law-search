"""Pure view models and the local Streamlit application."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, TypeVar
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from lawsearch.api import LawApiClient
from lawsearch.cache import CacheStore
from lawsearch.config import ConfigError, Settings, load_api_key, load_settings
from lawsearch.models import (
    ParsedQuery,
    Region,
    SearchResponse,
    SearchResult,
    SearchScope,
    SourceGroup,
    SourceState,
)
from lawsearch.query import QueryError, parse_query
from lawsearch.regions import RegionRegistry
from lawsearch.service import SearchService

if TYPE_CHECKING:
    import streamlit as st


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
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
_T = TypeVar("_T")


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
            f"조회 시각: {_format_timestamp(fetched_at)}"
        )
    return _STATE_MESSAGES[state]


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(_SEOUL).strftime("%Y-%m-%d %H:%M:%S KST")


def _run(awaitable: Awaitable[_T]) -> _T:
    """Run one async operation from Streamlit's synchronous script thread."""
    return asyncio.run(awaitable)


async def _search(settings: Settings, parsed: ParsedQuery, refresh: bool) -> SearchResponse:
    async with LawApiClient(load_api_key(settings.api_key_file)) as api:
        service = SearchService(api, CacheStore(settings.cache_path), lambda: datetime.now(UTC))
        return await service.search(parsed, refresh=refresh)


async def _contexts(
    settings: Settings, result: SearchResult, keyword: str, refresh: bool = False
):
    async with LawApiClient(load_api_key(settings.api_key_file)) as api:
        service = SearchService(api, CacheStore(settings.cache_path), lambda: datetime.now(UTC))
        return await service.load_contexts(result, keyword, refresh=refresh)


def _load_resources(streamlit: Any) -> tuple[Settings, RegionRegistry]:
    @streamlit.cache_resource
    def resources() -> tuple[Settings, RegionRegistry]:
        return load_settings(_PROJECT_ROOT), RegionRegistry.from_package_data()

    return resources()


def _render_search_form(streamlit: Any) -> tuple[str, bool]:
    with streamlit.form(
        "search-form",
        clear_on_submit=False,
        enter_to_submit=True,
        border=False,
    ):
        query_col, button_col = streamlit.columns([5, 1])
        raw = query_col.text_input(
            "검색어", placeholder="법령명이나 주제를 입력하세요"
        )
        submitted = button_col.form_submit_button(
            "검색", type="primary", width="stretch"
        )
    return raw, submitted


def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="대한민국 법령 통합검색", page_icon="⚖️", layout="wide")
    st.title("대한민국 법령 통합검색")
    st.caption("예: `주차장법`, `@평택 주차장`, `@경기/평택 주차장`")
    st.info("출처: 국가법령정보센터")
    st.warning("참고자료이며 최종 확인은 공식 원문 및 소관기관 기준")

    try:
        settings, registry = _load_resources(st)
    except ConfigError:
        st.error("로컬 설정을 읽지 못했습니다. config.local.toml을 확인해 주세요.")
        return

    selected = st.session_state.get("selected_region")
    if selected is not None:
        chip, clear = st.columns([5, 1])
        chip.markdown(f"**선택 지역:** `{fully_qualified_region_name(selected)}`")
        if clear.button("지역 지우기"):
            st.session_state.pop("selected_region", None)
            st.session_state.pop("response", None)
            st.rerun()

    raw, search_clicked = _render_search_form(st)
    refresh_clicked = st.button("공식 API에서 새로고침") if "response" in st.session_state else False

    if search_clicked:
        _handle_search(st, raw, registry, settings, refresh=False)
    if refresh_clicked:
        saved = st.session_state.get("parsed_query")
        if saved is not None:
            _perform_search(st, settings, saved, refresh=True)

    candidates = st.session_state.get("region_candidates", ())
    if candidates:
        choices = {fully_qualified_region_name(item): item for item in candidates}
        choice = st.selectbox("지역을 정확히 선택하세요", tuple(choices))
        if st.button("선택 적용"):
            _apply_region_candidate(
                st, settings, st.session_state.pending_keyword, choices[choice]
            )

    response = st.session_state.get("response")
    if response is not None:
        _render_response(st, settings, response, st.session_state["parsed_query"])


def _handle_search(st: Any, raw: str, registry: RegionRegistry, settings: Settings, refresh: bool) -> None:
    _clear_response(st)
    try:
        parsed = parse_query(raw, registry)
    except QueryError:
        _clear_ambiguity(st)
        st.error("검색어와 지역 표기를 확인해 주세요. 지역은 @평택처럼 하나만 입력합니다.")
        return
    if parsed.candidates:
        st.session_state.region_candidates = parsed.candidates
        st.session_state.pending_keyword = parsed.keyword
        st.session_state.pop("response", None)
        st.session_state.pop("parsed_query", None)
        return
    _clear_ambiguity(st)
    if parsed.region is None:
        st.session_state.pop("selected_region", None)
    else:
        st.session_state.selected_region = parsed.region
    _perform_search(st, settings, parsed, refresh)


def _apply_region_candidate(
    st: Any, settings: Settings, keyword: str, region: Region
) -> None:
    st.session_state.selected_region = region
    _clear_ambiguity(st)
    _perform_search(st, settings, ParsedQuery(keyword, region), refresh=False)


def _clear_ambiguity(st: Any) -> None:
    st.session_state.pop("region_candidates", None)
    st.session_state.pop("pending_keyword", None)


def _clear_response(st: Any) -> None:
    st.session_state.pop("response", None)
    st.session_state.pop("parsed_query", None)


def _perform_search(st: Any, settings: Settings, parsed: ParsedQuery, refresh: bool) -> None:
    _clear_response(st)
    try:
        with st.spinner("공식 자료를 조회하는 중입니다…"):
            response = _run(_search(settings, parsed, refresh))
    except (ConfigError, OSError):
        st.error("설정 또는 저장소를 사용할 수 없습니다. 키 파일과 캐시 경로를 확인해 주세요.")
        return
    except Exception:
        st.error("검색을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.")
        return
    st.session_state.parsed_query = parsed
    st.session_state.response = response


def _render_response(
    st: Any, settings: Settings, response: SearchResponse, parsed: ParsedQuery
) -> None:
    if response.suggestions:
        st.caption("연관 검색어: " + ", ".join(response.suggestions))
    for message in build_error_messages(response):
        st.error(message)
    for group in build_grouped_view(response, parsed.region):
        with st.expander(
            f"{group.label} ({len(group.results)})", expanded=group.expanded
        ):
            if group.state is SourceState.STALE_FALLBACK:
                st.warning(group.status_message)
            elif group.state is SourceState.ERROR:
                st.error(group.status_message)
                st.caption("위의 새로고침 버튼으로 이 출처를 다시 조회할 수 있습니다.")
            else:
                st.caption(group.status_message)
            for result in group.results:
                _render_result(st, settings, result, parsed.keyword)


def _render_result(st: Any, settings: Settings, result: SearchResult, keyword: str) -> None:
    st.markdown(f"#### {result.title}")
    fields = [result.category]
    if result.authority:
        fields.append(result.authority)
    fields.append("현행" if result.is_current else "연혁")
    if result.promulgation_date:
        fields.append(f"공포 {result.promulgation_date.isoformat()}")
    if result.effective_date:
        fields.append(f"시행 {result.effective_date.isoformat()}")
    st.caption(" · ".join(fields))
    if is_official_url(result.official_url):
        st.link_button("공식 원문 열기", result.official_url)
    else:
        st.caption("공식 링크를 확인할 수 없습니다.")
    detail_key = detail_session_key(result.source, result.uid, keyword)
    if st.button("본문 일치 보기", key=f"load-{detail_key}"):
        try:
            st.session_state[detail_key] = _run(_contexts(settings, result, keyword))
        except Exception:
            st.error("본문을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.")
    detail = st.session_state.get(detail_key)
    if detail is not None:
        if detail.state is SourceState.STALE_FALLBACK:
            st.warning(f"이전 본문 결과 · 조회 시각 {_format_timestamp(detail.fetched_at)}")
        elif detail.state is SourceState.ERROR:
            st.error("본문을 불러오지 못했습니다.")
        elif not detail.contexts:
            st.caption("검색어와 일치하는 본문 구간이 없습니다.")
        for context in detail.contexts[:5]:
            st.markdown(f"> {context}")
    st.divider()


if __name__ == "__main__":
    main()
