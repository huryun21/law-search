"""The local Streamlit application.

Rendering-independent logic lives in :mod:`lawsearch.viewmodels`.
"""

from __future__ import annotations

import asyncio
import html
import logging
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Mapping, TypeVar

from lawsearch.api import LawApiClient
from lawsearch.cache import CacheStore
from lawsearch.config import ConfigError, Settings, load_settings, resolve_api_key
from lawsearch.models import (
    ParsedQuery,
    Region,
    SearchResponse,
    SearchResult,
    SourceState,
)
from lawsearch.prioritization import PRIORITY_KEYWORDS
from lawsearch.query import QueryError, parse_query
from lawsearch.ranking import rank_results
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
    source_state_key,
)

if TYPE_CHECKING:
    import streamlit as st


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_T = TypeVar("_T")
_logger = logging.getLogger(__name__)

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


def _app_secrets() -> Mapping[str, str]:
    """The Cloud-provided secrets the app cares about, or {} when there are none."""
    try:
        import streamlit as st

        return {
            key: str(st.secrets[key]) for key in ("LAW_API_KEY",) if key in st.secrets
        }
    except Exception:
        return {}


async def _search(settings: Settings, parsed: ParsedQuery, refresh: bool) -> SearchResponse:
    async with LawApiClient(resolve_api_key(settings, _app_secrets())) as api:
        service = SearchService(api, CacheStore(settings.cache_path), lambda: datetime.now(UTC))
        return await service.search(parsed, refresh=refresh, priority_keywords=PRIORITY_KEYWORDS)


async def _verify_pending(
    settings: Settings, pending: tuple[SearchResult, ...], keyword: str
) -> tuple[tuple[SearchResult, ...], int]:
    async with LawApiClient(resolve_api_key(settings, _app_secrets())) as api:
        service = SearchService(api, CacheStore(settings.cache_path), lambda: datetime.now(UTC))
        return await service.verify_pending(pending, keyword)


async def _contexts(
    settings: Settings,
    result: SearchResult,
    keyword: str,
    *,
    refresh: bool = False,
    limit: int = 5,
):
    async with LawApiClient(resolve_api_key(settings, _app_secrets())) as api:
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
        "<style>"
        f".block-container{{max-width:{_CONTENT_MAX_WIDTH_PX}px;}}"
        ".match-line{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;"
        "overflow:hidden;font-size:0.85rem;line-height:1.4;opacity:0.75;"
        "border-left:3px solid rgba(128,128,128,0.35);padding-left:0.6rem;margin:0.2rem 0;}"
        "</style>",
        unsafe_allow_html=True,
    )


def _render_top_bar(st: Any) -> None:
    st.title("대한민국 법령 통합검색")
    st.caption("예: `주차장법`, `@평택 주차장`, `@경기/평택 주차장`")
    st.caption("출처: 국가법령정보센터 · 참고자료이며 최종 확인은 공식 원문 및 소관기관 기준")


def _render_workspace_controls(
    st: Any, settings: Settings, parsed: ParsedQuery
) -> None:
    """Refresh + view-mode toggle. Rendered only once a response exists."""
    if st.button("공식 API에서 새로고침"):
        _perform_search(st, settings, parsed, refresh=True)
        st.rerun()
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

    if search_clicked:
        _handle_search(st, raw, registry, settings, refresh=False)

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
    _render_workspace_controls(st, settings, parsed)
    with st.sidebar:
        _render_sidebar(st, response, parsed)
    mode = _view_mode(st)
    if mode == _VIEW_PREVIEW:
        _render_preview(st, settings, response, parsed)
    elif mode == _VIEW_COMPARE:
        _render_compare(st, settings, response, parsed)
    else:
        _render_results(st, settings, response, parsed)
        _render_pending_status(st, settings, parsed)


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
    st.session_state.pop("pending_queue", None)
    st.session_state.pop("pending_total", None)
    st.session_state.pop("pending_checked", None)
    st.session_state.pop("pending_found", None)
    st.session_state.pop("pending_failed", None)
    _reset_workspace(st)
    _clear_detail_state(st)


def _perform_search(st: Any, settings: Settings, parsed: ParsedQuery, refresh: bool) -> None:
    _clear_response(st)
    try:
        with st.spinner("공식 자료를 조회하는 중입니다…"):
            response = _run(_search(settings, parsed, refresh))
    except (ConfigError, OSError) as error:
        _logger.warning("검색 설정/저장소 오류: %s", type(error).__name__)
        st.error("설정 또는 저장소를 사용할 수 없습니다. 키 파일과 캐시 경로를 확인해 주세요.")
        return
    except Exception as error:
        _logger.warning("검색 처리 실패: %s", type(error).__name__)
        st.error("검색을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.")
        return
    st.session_state.parsed_query = parsed
    st.session_state.response = response
    st.session_state.pending_queue = list(response.pending)
    st.session_state.pending_total = len(response.pending)
    st.session_state.pending_checked = 0
    st.session_state.pending_found = 0
    st.session_state.pending_failed = 0


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


_PENDING_CHUNK_SIZE = 20


def _states_with_confirmed(
    response: SearchResponse, confirmed: tuple[SearchResult, ...]
) -> Mapping[str, SourceState]:
    """``response.source_states`` with every source that just gained a confirmed
    background match lifted out of EMPTY.

    A source whose priority pass retained nothing is EMPTY, so its group keeps
    rendering "검색 결과 없음" even once background verification appends real
    confirmed matches for it. Only EMPTY is lifted -- never a downgrade -- and a
    source with no state at all is left alone, since SearchResponse requires a
    retrieval timestamp for every non-ERROR state and this has none to offer.
    An EMPTY source already carries one, so the upgrade adds no timestamp.
    """
    states = dict(response.source_states)
    for result in confirmed:
        key = source_state_key(result.source)
        if states.get(key) is SourceState.EMPTY:
            states[key] = SourceState.LIVE
    return states


def _render_pending_status(st: Any, settings: Settings, parsed: ParsedQuery) -> None:
    """Keep background verification on its timer only while work remains.

    The schedule is gated on ``pending_queue`` rather than ``pending_total``:
    the total is set once per search and never cleared as verification
    proceeds, so gating on it left the 2-second fragment re-running for the
    rest of the session after the queue had drained. The completion caption
    lives here, outside the fragment, so reporting the outcome does not depend
    on the fragment still ticking.
    """
    if st.session_state.get("pending_queue"):
        st.fragment(run_every="2s")(_render_pending_progress)(st, settings, parsed)
        return
    if st.session_state.get("pending_total", 0):
        found = st.session_state.get("pending_found", 0)
        st.caption(
            f"전체 확인 완료 (추가로 {found}건 발견)" if found else "전체 확인 완료"
        )
        _render_pending_failures(st)


def _render_pending_failures(st: Any) -> None:
    """Say how many deferred candidates could never be checked.

    A candidate whose detail fetch fails is dropped, and one of those drops may
    have been a genuine exact match. Refreshing re-runs the search against the
    live API, so the user has a way to act on this; saying nothing would make a
    confirmed match disappear with no trace outside the log.
    """
    failed = st.session_state.get("pending_failed", 0)
    if failed:
        st.caption(
            f"{failed}건은 확인하지 못했습니다 — 새로고침으로 다시 시도하세요"
        )


def _render_pending_progress(st: Any, settings: Settings, parsed: ParsedQuery) -> None:
    queue = st.session_state.get("pending_queue")
    if not queue:
        # Nothing left to verify. The completion caption is _render_pending_status's
        # job, so this tick renders nothing rather than duplicating it.
        return
    chunk = tuple(queue[:_PENDING_CHUNK_SIZE])
    remaining = queue[_PENDING_CHUNK_SIZE:]
    try:
        confirmed, failed = _run(_verify_pending(settings, chunk, parsed.keyword))
    except Exception as error:
        # Still never a hard crash -- but the whole chunk went unchecked, so
        # count it as failed rather than letting it vanish behind a log line.
        _logger.warning("나머지 결과 확인 실패: %s", type(error).__name__)
        confirmed, failed = (), len(chunk)
    st.session_state.pending_queue = remaining
    st.session_state.pending_checked = st.session_state.get("pending_checked", 0) + len(chunk)
    st.session_state.pending_failed = st.session_state.get("pending_failed", 0) + failed
    if confirmed:
        st.session_state.pending_found = st.session_state.get("pending_found", 0) + len(confirmed)
        response = st.session_state.response
        combined = rank_results(response.results + confirmed, parsed.region, parsed.keyword)
        st.session_state.response = replace(
            response,
            results=combined,
            source_states=_states_with_confirmed(response, confirmed),
        )
        # All state this tick needs to persist (queue/counters/response) is already
        # written above. Force a full-page rerun so main()'s outer _render_results/
        # _render_sidebar calls (which run outside this fragment) pick up the new
        # results immediately, instead of staying frozen until an unrelated rerun.
        # Ticks with no new matches must NOT rerun — that would defeat the point of
        # using a fragment in the first place.
        st.rerun()
    if remaining:
        total = st.session_state.get("pending_total", 0)
        checked = st.session_state.get("pending_checked", 0)
        st.caption(f"나머지 확인 중… ({checked} / {total})")
        _render_pending_failures(st)


def _render_card(st: Any, card: CardView, keyword: str) -> None:
    with st.container(border=True):
        st.markdown(f"**{card.title}**")
        st.caption(" · ".join(card.meta_fields))
        st.caption(card.match_kind)
        if card.match_line:
            st.markdown(
                f"<div class='match-line'>{html.escape(card.match_line)}</div>",
                unsafe_allow_html=True,
            )
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
