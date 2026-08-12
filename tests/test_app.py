import asyncio
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path

import lawsearch.app as app

from lawsearch.app import (
    build_error_messages,
    build_grouped_view,
    detail_session_key,
    fully_qualified_region_name,
    is_official_url,
)
from lawsearch.models import (
    ParsedQuery,
    SearchResponse,
    SourceError,
    SourceGroup,
    SourceState,
)


class SessionState(dict):
    def __getattr__(self, name):
        return self[name]

    def __setattr__(self, name, value):
        self[name] = value


class ControllerStub:
    def __init__(self, state=None):
        self.session_state = SessionState(state or {})
        self.errors = []

    def error(self, message):
        self.errors.append(message)


def make_response(result_factory, *, stale=(), error=()):
    results = tuple(
        result_factory(source, title=f"{source.value} title")
        for source in (
            SourceGroup.MUNICIPAL,
            SourceGroup.PROVINCIAL,
            SourceGroup.LAW,
            SourceGroup.ADMIN_RULE,
        )
    )
    states = {
        "municipal": SourceState.STALE_FALLBACK
        if "municipal" in stale
        else SourceState.LIVE,
        "provincial": SourceState.LIVE,
        "laws": SourceState.ERROR if "laws" in error else SourceState.LIVE,
        "admin_rules": SourceState.LIVE,
    }
    return SearchResponse(
        results=results,
        suggestions=(),
        errors=tuple(SourceError(name, "private diagnostic") for name in error),
        source_states=states,
        source_fetched_at={
            name: datetime(2026, 8, 11, tzinfo=UTC) for name in states
        },
    )


def test_view_groups_keep_ranked_source_order(result_factory, pyeongtaek):
    groups = build_grouped_view(make_response(result_factory), pyeongtaek)

    assert [group.label for group in groups[:3]] == [
        "평택시 자치법규",
        "경기도 자치법규",
        "법률",
    ]


def test_stale_source_has_visible_retrieval_warning(result_factory):
    groups = build_grouped_view(make_response(result_factory, stale={"municipal"}))

    assert "이전 결과" in groups[0].status_message
    assert "2026-08-11 09:00:00 KST" in groups[0].status_message
    assert groups[0].fetched_at == datetime(2026, 8, 11, tzinfo=UTC)


def test_error_group_is_retained_without_raw_error_text(result_factory):
    response = make_response(result_factory, error={"laws"})
    groups = build_grouped_view(response)
    laws = next(group for group in groups if group.label == "법률")

    assert laws.state is SourceState.ERROR
    assert "다시 시도" in laws.status_message
    assert "private diagnostic" not in laws.status_message


def test_empty_law_subgroups_are_not_rendered(result_factory):
    response = SearchResponse(
        results=(result_factory(SourceGroup.LAW),),
        suggestions=(),
        errors=(),
        source_states={"laws": SourceState.LIVE},
        source_fetched_at={"laws": datetime(2026, 8, 11, tzinfo=UTC)},
    )

    assert [group.label for group in build_grouped_view(response)] == ["법률"]


def test_decree_only_response_does_not_invent_empty_law_group(result_factory):
    response = SearchResponse(
        results=(result_factory(SourceGroup.DECREE),),
        suggestions=(),
        errors=(),
        source_states={"laws": SourceState.LIVE},
        source_fetched_at={"laws": datetime(2026, 8, 11, tzinfo=UTC)},
    )

    assert [group.label for group in build_grouped_view(response)] == ["대통령령"]


def test_empty_ordinance_labels_come_from_selected_region(pyeongtaek):
    response = SearchResponse(
        results=(),
        suggestions=(),
        errors=(),
        source_states={
            "municipal": SourceState.EMPTY,
            "provincial": SourceState.ERROR,
        },
        source_fetched_at={"municipal": datetime(2026, 8, 11, tzinfo=UTC)},
    )

    groups = build_grouped_view(response, pyeongtaek)

    assert [group.label for group in groups] == [
        "평택시 자치법규",
        "경기도 자치법규",
    ]


def test_empty_ordinance_groups_keep_priority_before_national_results(
    result_factory, pyeongtaek
):
    fetched = datetime(2026, 8, 11, tzinfo=UTC)
    response = SearchResponse(
        results=(result_factory(SourceGroup.DECREE),),
        suggestions=(),
        errors=(),
        source_states={
            "municipal": SourceState.EMPTY,
            "provincial": SourceState.EMPTY,
            "laws": SourceState.LIVE,
        },
        source_fetched_at={
            "municipal": fetched,
            "provincial": fetched,
            "laws": fetched,
        },
    )

    assert [group.label for group in build_grouped_view(response, pyeongtaek)] == [
        "평택시 자치법규",
        "경기도 자치법규",
        "대통령령",
    ]


def test_zero_result_stale_group_uses_source_retrieval_timestamp():
    fetched = datetime(2026, 8, 9, 3, 4, 5, tzinfo=UTC)
    response = SearchResponse(
        results=(),
        suggestions=(),
        errors=(SourceError("laws", "private diagnostic"),),
        source_states={"laws": SourceState.STALE_FALLBACK},
        source_fetched_at={"laws": fetched},
    )

    group = build_grouped_view(response)[0]

    assert group.fetched_at == fetched
    assert "2026-08-09 12:04:05 KST" in group.status_message


def test_official_link_allows_only_https_law_go_kr_hosts():
    assert is_official_url("https://www.law.go.kr/법령/주차장법")
    assert is_official_url("https://law.go.kr/example")
    assert not is_official_url("http://law.go.kr/example")
    assert not is_official_url("https://law.go.kr.evil.example/path")
    assert not is_official_url("https://user:password@law.go.kr/path")
    assert not is_official_url("https://law.go.kr:444/path")
    assert not is_official_url("javascript:alert(1)")


def test_region_label_is_fully_qualified(pyeongtaek):
    assert fully_qualified_region_name(pyeongtaek) == "경기도 / 평택시"


def test_plain_query_does_not_inherit_previous_region(monkeypatch, pyeongtaek):
    streamlit = ControllerStub(
        {
            "selected_region": pyeongtaek,
            "region_candidates": (pyeongtaek,),
            "pending_keyword": "이전 검색",
        }
    )
    searches = []
    monkeypatch.setattr(app, "parse_query", lambda raw, registry: ParsedQuery("주차장"))
    monkeypatch.setattr(
        app,
        "_perform_search",
        lambda st, settings, parsed, refresh: searches.append((parsed, refresh)),
    )

    app._handle_search(streamlit, "주차장", object(), object(), refresh=False)

    assert searches == [(ParsedQuery("주차장"), False)]
    assert "selected_region" not in streamlit.session_state
    assert "region_candidates" not in streamlit.session_state
    assert "pending_keyword" not in streamlit.session_state


def test_invalid_query_clears_old_ambiguity(monkeypatch, pyeongtaek):
    streamlit = ControllerStub(
        {
            "region_candidates": (pyeongtaek,),
            "pending_keyword": "이전 검색",
            "response": object(),
            "parsed_query": ParsedQuery("이전 검색"),
        }
    )

    def invalid(raw, registry):
        raise app.QueryError("private parser diagnostic")

    monkeypatch.setattr(app, "parse_query", invalid)

    app._handle_search(streamlit, "@@잘못", object(), object(), refresh=False)

    assert "region_candidates" not in streamlit.session_state
    assert "pending_keyword" not in streamlit.session_state
    assert "response" not in streamlit.session_state
    assert "parsed_query" not in streamlit.session_state


def test_ambiguous_query_preserves_keyword_until_candidate_selection(
    monkeypatch, pyeongtaek
):
    another = type(pyeongtaek)("서울특별시", "중구", "6110000", "3010000")
    streamlit = ControllerStub({"response": object()})
    ambiguous = ParsedQuery("주차 대수", candidates=(pyeongtaek, another))
    monkeypatch.setattr(app, "parse_query", lambda raw, registry: ambiguous)
    monkeypatch.setattr(
        app,
        "_perform_search",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("searched early")),
    )

    app._handle_search(streamlit, "@중구 주차 대수", object(), object(), refresh=False)

    assert streamlit.session_state["pending_keyword"] == "주차 대수"
    assert streamlit.session_state["region_candidates"] == (pyeongtaek, another)
    assert "response" not in streamlit.session_state


def test_candidate_selection_resolves_preserved_keyword(monkeypatch, pyeongtaek):
    streamlit = ControllerStub(
        {"region_candidates": (pyeongtaek,), "pending_keyword": "주차 대수"}
    )
    searches = []
    monkeypatch.setattr(
        app,
        "_perform_search",
        lambda st, settings, parsed, refresh: searches.append((parsed, refresh)),
    )

    app._apply_region_candidate(streamlit, object(), "주차 대수", pyeongtaek)

    assert searches == [(ParsedQuery("주차 대수", pyeongtaek), False)]
    assert streamlit.session_state["selected_region"] == pyeongtaek
    assert "region_candidates" not in streamlit.session_state
    assert "pending_keyword" not in streamlit.session_state


def test_refresh_forwards_saved_query_and_refresh_flag(monkeypatch, pyeongtaek):
    parsed = ParsedQuery("주차 대수", pyeongtaek)
    streamlit = ControllerStub()
    streamlit.spinner = lambda message: nullcontext()
    response = object()

    async def search(settings, actual, refresh):
        assert actual == parsed
        assert refresh is True
        return response

    monkeypatch.setattr(app, "_search", search)

    app._perform_search(streamlit, object(), parsed, refresh=True)

    assert streamlit.session_state["parsed_query"] == parsed
    assert streamlit.session_state["response"] is response


def test_ui_error_never_exposes_exception_text(monkeypatch):
    old_response = object()
    streamlit = ControllerStub(
        {"response": old_response, "parsed_query": ParsedQuery("이전 검색")}
    )
    streamlit.spinner = lambda message: nullcontext()

    async def fail(settings, parsed, refresh):
        raise RuntimeError("private adapter diagnostic 9382")

    monkeypatch.setattr(app, "_search", fail)

    app._perform_search(streamlit, object(), ParsedQuery("주차장"), refresh=False)

    assert streamlit.errors == ["검색을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요."]
    assert "diagnostic 9382" not in streamlit.errors[0]
    assert "response" not in streamlit.session_state
    assert "parsed_query" not in streamlit.session_state


def test_detail_state_is_scoped_to_normalized_query_identity():
    first = detail_session_key(SourceGroup.LAW, "same-id", "주차 대수")
    equivalent = detail_session_key(SourceGroup.LAW, "same-id", "  주차   대수 ")
    different = detail_session_key(SourceGroup.LAW, "same-id", "주차장")

    assert first == equivalent
    assert first != different


def test_source_errors_are_named_and_diagnostics_are_redacted():
    response = SearchResponse(
        results=(),
        suggestions=(),
        errors=(
            SourceError("admin_rules", "private adapter diagnostic 7194"),
            SourceError("terms", "private term failure"),
        ),
        source_states={"admin_rules": SourceState.ERROR},
        source_fetched_at={},
    )

    messages = build_error_messages(response)

    assert messages == (
        "행정규칙: 조회하지 못했습니다. 새로고침으로 다시 시도해 주세요.",
        "법령용어: 조회하지 못했습니다. 새로고침으로 다시 시도해 주세요.",
    )
    assert all("diagnostic" not in message for message in messages)


def test_search_client_is_closed_in_the_same_event_loop(monkeypatch, tmp_path):
    events = []

    class Client:
        def __init__(self, api_key):
            events.append(("created", api_key, id(asyncio.get_running_loop())))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            events.append(("closed", id(asyncio.get_running_loop())))

    class Service:
        def __init__(self, api, cache, clock):
            self.api = api

        async def search(self, parsed, refresh=False):
            events.append(("searched", refresh, id(asyncio.get_running_loop())))
            return "response"

    settings = app.Settings(tmp_path / "key.txt", tmp_path / "cache.db")
    monkeypatch.setattr(app, "load_api_key", lambda path: "test-key")
    monkeypatch.setattr(app, "LawApiClient", Client)
    monkeypatch.setattr(app, "SearchService", Service)
    monkeypatch.setattr(app, "CacheStore", lambda path: object())

    assert asyncio.run(app._search(settings, ParsedQuery("주차장"), True)) == "response"
    assert [event[0] for event in events] == ["created", "searched", "closed"]
    assert len({event[-1] for event in events}) == 1


def test_launcher_contract_is_loopback_and_conditional_install():
    launcher = (Path(__file__).parents[1] / "run.bat").read_text(encoding="utf-8")
    folded = launcher.casefold()

    assert 'cd /d "%~dp0"' in folded
    assert "py -3.12 -m venv .venv" in folded
    assert "import lawsearch, streamlit, httpx" in folded
    assert "-m pip install -e ." in folded
    assert "--server.address 127.0.0.1" in folded
    assert "--server.headless false" in folded
    assert "config.local.toml" in folded
    assert "pause" in folded
