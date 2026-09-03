from dataclasses import replace
from datetime import UTC, datetime

from lawsearch.viewmodels import (
    build_error_messages,
    build_grouped_view,
    detail_session_key,
    fully_qualified_region_name,
    is_official_url,
)
from lawsearch.models import (
    SearchResponse,
    SearchScope,
    SourceError,
    SourceGroup,
    SourceState,
)


def test_viewmodels_module_does_not_import_streamlit():
    import importlib
    import sys

    sys.modules.pop("lawsearch.viewmodels", None)
    sys.modules.pop("streamlit", None)
    importlib.import_module("lawsearch.viewmodels")
    assert "streamlit" not in sys.modules


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


def test_provincial_group_label_uses_selected_province_not_result_authority(
    result_factory, pyeongtaek
):
    provincial = replace(
        result_factory(SourceGroup.PROVINCIAL),
        authority="경기도 광명시",
        region_name="경기도 광명시",
    )
    fetched = datetime(2026, 8, 11, tzinfo=UTC)
    response = SearchResponse(
        results=(provincial,),
        suggestions=(),
        errors=(),
        source_states={"provincial": SourceState.LIVE},
        source_fetched_at={"provincial": fetched},
    )

    groups = build_grouped_view(response, pyeongtaek)

    assert [group.label for group in groups] == ["경기도 자치법규"]


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


def test_body_only_hits_are_kept_in_a_collapsed_additional_group(result_factory):
    title_hit = replace(
        result_factory(SourceGroup.LAW, uid="parking", title="주차장법"),
        scope=SearchScope.TITLE,
    )
    body_hit = replace(
        result_factory(SourceGroup.LAW, uid="building", title="건축법"),
        scope=SearchScope.BODY,
    )
    response = SearchResponse(
        results=(title_hit, body_hit),
        suggestions=(),
        errors=(),
        source_states={"laws": SourceState.LIVE},
        source_fetched_at={"laws": datetime(2026, 8, 11, tzinfo=UTC)},
    )

    groups = build_grouped_view(response)

    assert [(group.label, [item.uid for item in group.results]) for group in groups] == [
        ("법률", ["parking"]),
        ("법률 · 본문 관련 추가 결과", ["building"]),
    ]
    assert [group.expanded for group in groups] == [True, False]


def test_all_title_match_groups_precede_any_body_only_group(result_factory):
    title_law = replace(
        result_factory(SourceGroup.LAW, uid="law", title="주차장법"),
        scope=SearchScope.TITLE,
    )
    body_law = replace(
        result_factory(SourceGroup.LAW, uid="building", title="건축법"),
        scope=SearchScope.BODY,
    )
    title_decree = replace(
        result_factory(SourceGroup.DECREE, uid="decree", title="주차장법 시행령"),
        scope=SearchScope.TITLE,
    )
    fetched = datetime(2026, 8, 11, tzinfo=UTC)
    response = SearchResponse(
        results=(title_law, body_law, title_decree),
        suggestions=(),
        errors=(),
        source_states={"laws": SourceState.LIVE},
        source_fetched_at={"laws": fetched},
    )

    groups = build_grouped_view(response)

    assert [group.label for group in groups] == [
        "법률",
        "대통령령",
        "법률 · 본문 관련 추가 결과",
    ]


def test_regional_body_results_stay_above_national_title_results(
    result_factory, pyeongtaek
):
    municipal_body = replace(
        result_factory(
            SourceGroup.MUNICIPAL,
            uid="local",
            title="평택시 주차장 설치 및 관리 조례",
        ),
        scope=SearchScope.BODY,
    )
    national_title = replace(
        result_factory(SourceGroup.LAW, uid="law", title="주차장법"),
        scope=SearchScope.TITLE,
    )
    fetched = datetime(2026, 8, 11, tzinfo=UTC)
    response = SearchResponse(
        results=(national_title, municipal_body),
        suggestions=(),
        errors=(),
        source_states={
            "municipal": SourceState.LIVE,
            "laws": SourceState.LIVE,
        },
        source_fetched_at={"municipal": fetched, "laws": fetched},
    )

    groups = build_grouped_view(response, pyeongtaek)

    assert [group.label for group in groups] == ["평택시 자치법규", "법률"]
    assert groups[0].expanded is True


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
