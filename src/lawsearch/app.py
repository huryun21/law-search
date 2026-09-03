"""The local Streamlit application.

Rendering-independent logic lives in :mod:`lawsearch.viewmodels`.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, TypeVar

from lawsearch.api import LawApiClient
from lawsearch.cache import CacheStore
from lawsearch.config import ConfigError, Settings, load_api_key, load_settings
from lawsearch.models import (
    ParsedQuery,
    Region,
    SearchResponse,
    SearchResult,
    SourceState,
)
from lawsearch.query import QueryError, parse_query
from lawsearch.regions import RegionRegistry
from lawsearch.service import SearchService
from lawsearch.viewmodels import (
    CardView,
    CompareOption,
    build_error_messages,
    build_grouped_view,
    card_rows,
    compare_options,
    detail_session_key,
    format_timestamp,
    fully_qualified_region_name,
    is_official_url,
    sidebar_sections,
)

if TYPE_CHECKING:
    import streamlit as st


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_T = TypeVar("_T")

_VIEW_RESULTS = "results"
_VIEW_PREVIEW = "preview"
_VIEW_COMPARE = "compare"
_WORKSPACE_KEYS = (
    "view_mode",
    "selected_result_key",
    "compare_left_result_key",
    "compare_right_result_key",
    "compare_left_article",
    "compare_right_article",
)


def _view_mode(st: Any) -> str:
    return st.session_state.get("view_mode", _VIEW_RESULTS)


def _reset_workspace(st: Any) -> None:
    for key in _WORKSPACE_KEYS:
        st.session_state.pop(key, None)


def _clear_detail_state(st: Any) -> None:
    stale = [
        key
        for key in list(st.session_state)
        if isinstance(key, str) and key.startswith("detail-")
    ]
    for key in stale:
        st.session_state.pop(key, None)


def _open_preview(st: Any, key: str) -> None:
    st.session_state.view_mode = _VIEW_PREVIEW
    st.session_state.selected_result_key = key


def _open_results(st: Any) -> None:
    st.session_state.view_mode = _VIEW_RESULTS
    st.session_state.pop("selected_result_key", None)


def _open_compare(st: Any) -> None:
    st.session_state.view_mode = _VIEW_COMPARE


def _run(awaitable: Awaitable[_T]) -> _T:
    """Run one async operation from Streamlit's synchronous script thread."""
    return asyncio.run(awaitable)


async def _search(settings: Settings, parsed: ParsedQuery, refresh: bool) -> SearchResponse:
    async with LawApiClient(load_api_key(settings.api_key_file)) as api:
        service = SearchService(api, CacheStore(settings.cache_path), lambda: datetime.now(UTC))
        return await service.search(parsed, refresh=refresh)


async def _contexts(
    settings: Settings,
    result: SearchResult,
    keyword: str,
    *,
    refresh: bool = False,
    limit: int = 5,
):
    async with LawApiClient(load_api_key(settings.api_key_file)) as api:
        service = SearchService(
            api, CacheStore(settings.cache_path), lambda: datetime.now(UTC)
        )
        return await service.load_contexts(
            result, keyword, refresh=refresh, limit=limit
        )


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


_CONTENT_MAX_WIDTH_PX = 1100


def _inject_layout_css(st: Any) -> None:
    st.markdown(
        f"<style>.block-container{{max-width:{_CONTENT_MAX_WIDTH_PX}px;}}</style>",
        unsafe_allow_html=True,
    )


def _render_top_bar(st: Any) -> None:
    st.title("대한민국 법령 통합검색")
    st.caption("예: `주차장법`, `@평택 주차장`, `@경기/평택 주차장`")
    st.caption("출처: 국가법령정보센터 · 참고자료이며 최종 확인은 공식 원문 및 소관기관 기준")
    if "response" not in st.session_state:
        return
    mode = _view_mode(st)
    results_col, compare_col = st.columns(2)
    if results_col.button(
        "기본 보기", disabled=mode == _VIEW_RESULTS, width="stretch"
    ):
        _open_results(st)
        st.rerun()
    if compare_col.button(
        "비교하기", disabled=mode == _VIEW_COMPARE, width="stretch"
    ):
        _open_compare(st)
        st.rerun()


def main() -> None:
    import streamlit as st

    st.set_page_config(
        page_title="대한민국 법령 통합검색", page_icon="⚖️", layout="wide"
    )
    _inject_layout_css(st)
    _render_top_bar(st)

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
            _clear_response(st)
            st.rerun()

    raw, search_clicked = _render_search_form(st)
    refresh_clicked = (
        st.button("공식 API에서 새로고침") if "response" in st.session_state else False
    )

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
    if response is None:
        return
    parsed = st.session_state["parsed_query"]
    with st.sidebar:
        _render_sidebar(st, response, parsed)
    mode = _view_mode(st)
    if mode == _VIEW_PREVIEW:
        _render_preview(st, settings, response, parsed)
    elif mode == _VIEW_COMPARE:
        _render_compare(st, settings, response, parsed)
    else:
        _render_results(st, settings, response, parsed)


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
    _reset_workspace(st)
    _clear_detail_state(st)


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


def _render_results(
    st: Any, settings: Settings, response: SearchResponse, parsed: ParsedQuery
) -> None:
    if response.suggestions:
        st.caption("연관 검색어: " + ", ".join(response.suggestions))
    for message in build_error_messages(response):
        st.error(message)
    for group in build_grouped_view(response, parsed.region):
        st.subheader(f"{group.label} ({len(group.results)})")
        if group.state is SourceState.STALE_FALLBACK:
            st.warning(group.status_message)
        elif group.state is SourceState.ERROR:
            st.error(group.status_message)
            st.caption("위의 새로고침 버튼으로 이 출처를 다시 조회할 수 있습니다.")
        else:
            st.caption(group.status_message)
        for row in card_rows(group.results, columns=2):
            columns = st.columns(2)
            for column, card in zip(columns, row):
                with column:
                    _render_card(st, card, parsed.keyword)


def _render_card(st: Any, card: CardView, keyword: str) -> None:
    with st.container(border=True):
        st.markdown(f"**{card.title}**")
        st.caption(" · ".join(card.meta_fields))
        st.caption(card.match_kind)
        if card.match_line:
            st.markdown(f"> {card.match_line}")
        preview_col, official_col = st.columns(2)
        if preview_col.button("미리보기", key=f"preview-{card.key}", width="stretch"):
            _open_preview(st, card.key)
            st.rerun()
        if card.official_url:
            official_col.link_button("공식 원문", card.official_url, width="stretch")


def _render_sidebar(
    st: Any, response: SearchResponse, parsed: ParsedQuery
) -> None:
    for section in sidebar_sections(response, parsed.region):
        st.subheader(section.label)
        for group in section.groups:
            with st.expander(f"{group.label} ({group.count})"):
                for entry in group.entries:
                    if st.button(
                        entry.title, key=f"nav-{entry.key}", width="stretch"
                    ):
                        _open_preview(st, entry.key)
                        st.rerun()


_PREVIEW_CONTEXT_LIMIT = 20


def _find_result(response: SearchResponse, key: str | None) -> SearchResult | None:
    if key is None:
        return None
    for result in response.results:
        if f"{result.source.value}:{result.uid}" == key:
            return result
    return None


def _preview_detail(
    st: Any, settings: Settings, result: SearchResult, keyword: str
):
    session_key = detail_session_key(result.source, result.uid, keyword)
    cached = st.session_state.get(session_key)
    if cached is not None:
        return cached
    try:
        detail = _run(
            _contexts(settings, result, keyword, limit=_PREVIEW_CONTEXT_LIMIT)
        )
    except Exception:
        st.error("본문을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.")
        return None
    st.session_state[session_key] = detail
    return detail


def _render_preview(
    st: Any, settings: Settings, response: SearchResponse, parsed: ParsedQuery
) -> None:
    result = _find_result(response, st.session_state.get("selected_result_key"))
    if result is None:
        _open_results(st)
        st.rerun()
        return
    if st.button("← 검색 결과로 돌아가기", key="preview-back"):
        _open_results(st)
        st.rerun()
    st.markdown(f"### {result.title}")
    meta = [result.category]
    if result.authority:
        meta.append(result.authority)
    meta.append("현행" if result.is_current else "연혁")
    if result.effective_date:
        meta.append(f"시행 {result.effective_date.isoformat()}")
    st.caption(" · ".join(meta))
    if is_official_url(result.official_url):
        st.link_button("공식 원문 열기", result.official_url)

    detail = _preview_detail(st, settings, result, parsed.keyword)
    if detail is None:
        return
    if detail.state is SourceState.ERROR:
        st.error("본문을 불러오지 못했습니다.")
        return
    if not detail.contexts:
        st.caption("검색어와 정확히 일치하는 조문이 없습니다.")
        return
    if detail.state is SourceState.STALE_FALLBACK:
        st.warning(
            f"이전 본문 결과 · 조회 시각 {format_timestamp(detail.fetched_at)}"
        )
    st.caption(f"정확히 일치하는 조문 {len(detail.contexts)}건")
    if len(detail.contexts) > 1:
        labels = [context.split(" — ", 1)[0] for context in detail.contexts]
        index = st.radio(
            "조문 선택",
            range(len(detail.contexts)),
            format_func=lambda position: labels[position],
            key="preview-article",
        )
    else:
        index = 0
    st.markdown(f"> {detail.contexts[index]}")


def _render_compare(
    st: Any, settings: Settings, response: SearchResponse, parsed: ParsedQuery
) -> None:
    options = compare_options(response)
    if len(options) < 2:
        st.info("비교하려면 검색 결과가 2건 이상 필요합니다.")
        return
    st.caption(
        "키워드 일치 조문을 나란히 표시하며 법적 연계 관계를 자동 확정하지 않습니다."
    )
    left_col, right_col = st.columns(2)
    _render_compare_side(st, settings, response, parsed, options, left_col, "left")
    _render_compare_side(st, settings, response, parsed, options, right_col, "right")


def _render_compare_side(
    st: Any,
    settings: Settings,
    response: SearchResponse,
    parsed: ParsedQuery,
    options: tuple[CompareOption, ...],
    column: Any,
    side: str,
) -> None:
    labels = {option.label: option.key for option in options}
    with column:
        chosen_label = st.selectbox(
            "왼쪽 문서" if side == "left" else "오른쪽 문서",
            tuple(labels),
            key=f"compare-{side}",
        )
        key = labels[chosen_label]
        st.session_state[f"compare_{side}_result_key"] = key
        result = _find_result(response, key)
        if result is None:
            st.error("문서를 찾을 수 없습니다.")
            return
        meta = [result.category]
        if result.authority:
            meta.append(result.authority)
        meta.append("현행" if result.is_current else "연혁")
        st.caption(" · ".join(meta))
        if is_official_url(result.official_url):
            st.link_button("공식 원문 열기", result.official_url)
        detail = _preview_detail(st, settings, result, parsed.keyword)
        if detail is None or detail.state is SourceState.ERROR:
            st.error("본문을 불러오지 못했습니다.")
            return
        if not detail.contexts:
            st.caption("검색어와 정확히 일치하는 조문이 없습니다.")
            return
        if len(detail.contexts) > 1:
            article_labels = [c.split(" — ", 1)[0] for c in detail.contexts]
            index = st.radio(
                "조문 선택",
                range(len(detail.contexts)),
                format_func=lambda position: article_labels[position],
                key=f"compare-{side}-article",
            )
        else:
            index = 0
        st.markdown(f"> {detail.contexts[index]}")


if __name__ == "__main__":
    main()
