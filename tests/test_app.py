import asyncio
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
import subprocess

import pytest

import lawsearch.app as app

from lawsearch.models import (
    DetailResponse,
    ParsedQuery,
    SearchResponse,
    SearchScope,
    SourceGroup,
    SourceState,
)
from streamlit_stub import FakeStreamlit, Rerun


def _fetched():
    return datetime(2026, 8, 11, tzinfo=UTC)


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


def test_search_form_submits_entered_query():
    form_state = {"active": False, "enter_to_submit": None}

    class FormContext:
        def __enter__(self):
            form_state["active"] = True

        def __exit__(self, *args):
            form_state["active"] = False

    class InputColumn:
        def text_input(self, *args, **kwargs):
            return "방화구획"

    class SubmitColumn:
        def form_submit_button(self, *args, **kwargs):
            assert form_state["active"]
            return True

    class StreamlitStub:
        def form(self, key, *, enter_to_submit, **kwargs):
            form_state["enter_to_submit"] = enter_to_submit
            return FormContext()

        def columns(self, widths):
            assert form_state["active"]
            return InputColumn(), SubmitColumn()

    assert hasattr(app, "_render_search_form"), "검색 입력이 아직 Enter 제출 form이 아닙니다"

    raw, submitted = app._render_search_form(StreamlitStub())

    assert (raw, submitted) == ("방화구획", True)
    assert form_state == {"active": False, "enter_to_submit": True}


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


def test_open_preview_sets_mode_and_selection():
    streamlit = ControllerStub()

    app._open_preview(streamlit, "law:001498")

    assert streamlit.session_state["view_mode"] == "preview"
    assert streamlit.session_state["selected_result_key"] == "law:001498"


def test_open_results_clears_selection():
    streamlit = ControllerStub(
        {"view_mode": "preview", "selected_result_key": "law:1"}
    )

    app._open_results(streamlit)

    assert streamlit.session_state["view_mode"] == "results"
    assert "selected_result_key" not in streamlit.session_state


def test_view_mode_defaults_to_results():
    assert app._view_mode(ControllerStub()) == "results"


def test_new_search_resets_workspace_and_detail_state(monkeypatch):
    streamlit = ControllerStub(
        {
            "view_mode": "compare",
            "selected_result_key": "law:1",
            "compare_left_result_key": "law:2",
            "detail-law-1-0123456789abcdef": object(),
        }
    )
    streamlit.spinner = lambda message: nullcontext()

    async def fake_search(settings, parsed, refresh):
        return object()

    monkeypatch.setattr(app, "_search", fake_search)

    app._perform_search(streamlit, object(), ParsedQuery("주차장"), refresh=False)

    for key in ("view_mode", "selected_result_key", "compare_left_result_key"):
        assert key not in streamlit.session_state
    assert not any(
        isinstance(key, str) and key.startswith("detail-")
        for key in streamlit.session_state
    )


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
    launcher_path = Path(__file__).parents[1] / "run.bat"
    launcher_bytes = launcher_path.read_bytes()
    launcher = launcher_bytes.decode("utf-8")
    folded = launcher.casefold()

    assert b"\n" not in launcher_bytes.replace(b"\r\n", b"")
    assert 'cd /d "%~dp0"' in folded
    assert "chcp 65001 >nul" in folded
    assert "py -3.12 -m venv .venv" in folded
    assert "import lawsearch, streamlit, httpx" in folded
    assert "-m pip install -e ." in folded
    assert "--server.address 127.0.0.1" in folded
    assert "--server.headless false" in folded
    assert "--server.filewatchertype none" in folded
    assert "앱을 시작하는 중입니다" in launcher
    assert "config.local.toml" in folded
    assert "pause" in folded


def test_launcher_git_attribute_forces_windows_line_endings():
    project_root = Path(__file__).parents[1]

    result = subprocess.run(
        ["git", "check-attr", "eol", "--", "run.bat"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip().endswith("eol: crlf")


def _card_response(result_factory):
    results = tuple(
        replace(
            result_factory(source, uid=f"{source.value}-1", title=f"{source.value} 규정"),
            scope=SearchScope.BODY,
            match_context=f"제1조 — {source.value}",
        )
        for source in (SourceGroup.LAW, SourceGroup.DECREE, SourceGroup.ADMIN_RULE)
    )
    return SearchResponse(
        results=results,
        suggestions=(),
        errors=(),
        source_states={"laws": SourceState.LIVE, "admin_rules": SourceState.LIVE},
        source_fetched_at={"laws": _fetched(), "admin_rules": _fetched()},
    )


def test_results_view_lays_out_cards_two_per_row(result_factory):
    streamlit = FakeStreamlit()

    app._render_results(streamlit, object(), _card_response(result_factory), ParsedQuery("주차장"))

    assert any(args == (2,) for name, args, _ in streamlit.calls if name == "columns")


def test_results_card_preview_button_opens_preview(result_factory):
    response = _card_response(result_factory)
    first = response.results[0]
    key = f"{first.source.value}:{first.uid}"
    streamlit = FakeStreamlit(buttons={f"preview-{key}": True})

    with pytest.raises(Rerun):
        app._render_results(streamlit, object(), response, ParsedQuery("주차장"))

    assert streamlit.session_state["view_mode"] == "preview"
    assert streamlit.session_state["selected_result_key"] == key


def test_results_card_hides_button_for_non_official_url(result_factory):
    bad = replace(
        result_factory(SourceGroup.LAW, uid="l1", title="주차장법"),
        scope=SearchScope.BODY,
        official_url="http://law.go.kr/x",
        match_context="제1조 — x",
    )
    response = SearchResponse(
        results=(bad,),
        suggestions=(),
        errors=(),
        source_states={"laws": SourceState.LIVE},
        source_fetched_at={"laws": _fetched()},
    )
    streamlit = FakeStreamlit()

    app._render_results(streamlit, object(), response, ParsedQuery("주차장"))

    assert "link_button" not in streamlit.names()


def test_sidebar_lists_every_result_as_a_nav_button(result_factory):
    response = _card_response(result_factory)
    streamlit = FakeStreamlit(session_state={"response": response})

    app._render_sidebar(streamlit, response, ParsedQuery("주차장"))

    nav_keys = [
        kwargs.get("key")
        for name, args, kwargs in streamlit.calls
        if name == "button" and str(kwargs.get("key", "")).startswith("nav-")
    ]
    assert len(nav_keys) == len(response.results)


def test_sidebar_click_opens_preview_without_search(monkeypatch, result_factory):
    response = _card_response(result_factory)
    target = response.results[1]
    key = f"{target.source.value}:{target.uid}"
    streamlit = FakeStreamlit(buttons={f"nav-{key}": True})

    def forbidden(*a, **k):
        raise AssertionError("sidebar navigation must not call an API")

    monkeypatch.setattr(app, "_run", forbidden)

    with pytest.raises(Rerun):
        app._render_sidebar(streamlit, response, ParsedQuery("주차장"))

    assert streamlit.session_state["view_mode"] == "preview"
    assert streamlit.session_state["selected_result_key"] == key
