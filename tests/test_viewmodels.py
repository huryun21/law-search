from dataclasses import replace
from datetime import UTC, date, datetime

from lawsearch.viewmodels import (
    CardView,
    CompareOption,
    SidebarEntry,
    build_error_messages,
    build_grouped_view,
    card_rows,
    card_view,
    compare_options,
    detail_session_key,
    fully_qualified_region_name,
    is_official_url,
    result_key,
    sidebar_sections,
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


def test_each_sources_body_only_group_follows_its_own_title_group(result_factory):
    # A body-only ("추가 결과") group used to sort behind every source's title
    # group, so a source with only a title match (e.g. 행정규칙) could render
    # above a source that sorts earlier in _SOURCE_ORDER but only has a body
    # match (e.g. 법률) -- putting the main content out of step with the
    # sidebar, which always lists sources in _SOURCE_ORDER. Each source's own
    # body-only group now follows immediately after that same source's title
    # group, so the whole page follows one consistent per-source order.
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
        "법률 · 본문 관련 추가 결과",
        "대통령령",
    ]


def test_a_later_sources_title_match_does_not_jump_ahead_of_an_earlier_sources_body_group(
    result_factory,
):
    # The exact scenario reported live: a search where only 행정규칙 (which
    # sorts last in _SOURCE_ORDER) has a title match, and 법률 (which sorts
    # first) only has body matches. 행정규칙 must not render above 법률.
    body_law = replace(
        result_factory(SourceGroup.LAW, uid="building", title="건축법"),
        scope=SearchScope.BODY,
    )
    title_admin_rule = replace(
        result_factory(SourceGroup.ADMIN_RULE, uid="rule", title="통합심의위원회 운영세칙"),
        scope=SearchScope.TITLE,
    )
    fetched = datetime(2026, 8, 11, tzinfo=UTC)
    response = SearchResponse(
        results=(body_law, title_admin_rule),
        suggestions=(),
        errors=(),
        source_states={"laws": SourceState.LIVE, "admin_rules": SourceState.LIVE},
        source_fetched_at={"laws": fetched, "admin_rules": fetched},
    )

    groups = build_grouped_view(response)

    assert [group.label for group in groups] == [
        "법률 · 본문 관련 추가 결과",
        "행정규칙",
    ]


def test_a_later_national_sources_title_match_does_not_jump_ahead_of_an_earlier_national_sources_body_group_with_region(
    result_factory, pyeongtaek
):
    # Same bug as test_a_later_sources_title_match_does_not_jump_ahead_of_an_earlier_sources_body_group,
    # but reported live specifically for a region-scoped search
    # ("@평택 통합심의"): among the NATIONAL sources, 행정규칙 (last in
    # _SOURCE_ORDER) had a title match while 법률 (first) only had a body
    # match, and 행정규칙 still rendered above 법률 -- the region branch was
    # never fixed alongside the non-region branch and kept the old "every
    # additional group sorts behind every national title group" scheme.
    municipal_title = replace(
        result_factory(
            SourceGroup.MUNICIPAL, uid="local", title="평택시 통합심의위원회 설치 조례"
        ),
        scope=SearchScope.TITLE,
    )
    body_law = replace(
        result_factory(SourceGroup.LAW, uid="building", title="건축법"),
        scope=SearchScope.BODY,
    )
    title_admin_rule = replace(
        result_factory(SourceGroup.ADMIN_RULE, uid="rule", title="통합심의위원회 운영세칙"),
        scope=SearchScope.TITLE,
    )
    fetched = datetime(2026, 8, 11, tzinfo=UTC)
    response = SearchResponse(
        results=(municipal_title, body_law, title_admin_rule),
        suggestions=(),
        errors=(),
        source_states={
            "municipal": SourceState.LIVE,
            "laws": SourceState.LIVE,
            "admin_rules": SourceState.LIVE,
        },
        source_fetched_at={"municipal": fetched, "laws": fetched, "admin_rules": fetched},
    )

    groups = build_grouped_view(response, pyeongtaek)

    assert [group.label for group in groups] == [
        "평택시 자치법규",
        "법률 · 본문 관련 추가 결과",
        "행정규칙",
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


def test_body_group_splits_off_titles_matching_no_domain_keyword(result_factory):
    # "건축법" contains "건축" (a domain keyword) and stays immediately visible;
    # "관세법" matches none, so it's real but deprioritized -- available, not lost.
    relevant = replace(
        result_factory(SourceGroup.LAW, uid="building", title="건축법"),
        scope=SearchScope.BODY,
    )
    less_relevant = replace(
        result_factory(SourceGroup.LAW, uid="customs", title="관세법"),
        scope=SearchScope.BODY,
    )
    response = SearchResponse(
        results=(relevant, less_relevant),
        suggestions=(),
        errors=(),
        source_states={"laws": SourceState.LIVE},
        source_fetched_at={"laws": datetime(2026, 8, 11, tzinfo=UTC)},
    )

    group = build_grouped_view(response)[0]

    assert [item.uid for item in group.results] == ["building"]
    assert [item.uid for item in group.less_relevant_results] == ["customs"]


def test_body_group_survives_when_every_result_is_less_relevant(result_factory):
    # None of these titles match a domain keyword. The group must still
    # render (with an empty relevant list) rather than vanish -- silently
    # dropping every result for a source would defeat the point of keeping
    # them available behind "더보기".
    only_less_relevant = replace(
        result_factory(SourceGroup.LAW, uid="customs", title="관세법"),
        scope=SearchScope.BODY,
    )
    response = SearchResponse(
        results=(only_less_relevant,),
        suggestions=(),
        errors=(),
        source_states={"laws": SourceState.LIVE},
        source_fetched_at={"laws": datetime(2026, 8, 11, tzinfo=UTC)},
    )

    group = build_grouped_view(response)[0]

    assert group.results == ()
    assert [item.uid for item in group.less_relevant_results] == ["customs"]


def test_title_group_is_never_split_by_relevance(result_factory):
    # A title match is the law the user searched for by name -- it must
    # always show, regardless of whether its title happens to contain a
    # construction-domain keyword.
    title_hit = replace(
        result_factory(SourceGroup.LAW, uid="customs", title="관세법"),
        scope=SearchScope.TITLE,
    )
    response = SearchResponse(
        results=(title_hit,),
        suggestions=(),
        errors=(),
        source_states={"laws": SourceState.LIVE},
        source_fetched_at={"laws": datetime(2026, 8, 11, tzinfo=UTC)},
    )

    group = build_grouped_view(response)[0]

    assert [item.uid for item in group.results] == ["customs"]
    assert group.less_relevant_results == ()


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


def test_result_key_combines_source_and_uid(result_factory):
    assert result_key(result_factory(SourceGroup.LAW, uid="001498")) == "law:001498"


def test_card_view_exposes_verified_match_line(result_factory):
    result = replace(
        result_factory(SourceGroup.LAW, uid="004743", title="건축법 시행령"),
        scope=SearchScope.BODY,
        match_context="제46조(방화구획 등의 설치) — 주요구조부를 방화구획으로 구획한다",
    )

    card = card_view(result)

    assert card.key == "law:004743"
    assert card.match_kind == "본문 일치"
    assert card.match_line == "제46조(방화구획 등의 설치) — 주요구조부를 방화구획으로 구획한다"


def test_card_view_for_title_match_has_no_match_line(result_factory):
    card = card_view(replace(result_factory(SourceGroup.LAW), scope=SearchScope.TITLE))

    assert card.match_kind == "제목 일치"
    assert card.match_line is None


def test_card_view_meta_fields_include_currency_and_dates(result_factory):
    result = replace(
        result_factory(SourceGroup.DECREE, title="주차장법 시행령", current=False),
        promulgation_date=date(2025, 1, 2),
        effective_date=date(2025, 7, 1),
        authority="국토교통부",
    )

    card = card_view(result)

    assert card.meta_fields == (
        "decree",
        "국토교통부",
        "연혁",
        "공포 2025-01-02",
        "시행 2025-07-01",
    )


def test_card_view_drops_non_official_url(result_factory):
    result = replace(result_factory(SourceGroup.LAW), official_url="http://law.go.kr/x")

    assert card_view(result).official_url is None


def test_card_rows_batch_two_per_row_in_result_order(result_factory):
    results = tuple(result_factory(SourceGroup.LAW, uid=str(index)) for index in range(5))

    rows = card_rows(results, columns=2)

    assert [len(row) for row in rows] == [2, 2, 1]
    assert [[card.key for card in row] for row in rows] == [
        ["law:0", "law:1"],
        ["law:2", "law:3"],
        ["law:4"],
    ]


_FETCHED = datetime(2026, 8, 11, tzinfo=UTC)


def _response(results, states):
    return SearchResponse(
        results=results,
        suggestions=(),
        errors=(),
        source_states=states,
        source_fetched_at={name: _FETCHED for name in states},
    )


def test_sidebar_sections_lead_with_local_law_when_region_selected(
    result_factory, pyeongtaek
):
    results = (
        replace(
            result_factory(SourceGroup.MUNICIPAL, uid="m1", title="평택시 주차장 조례"),
            scope=SearchScope.BODY,
        ),
        replace(
            result_factory(SourceGroup.LAW, uid="l1", title="주차장법"),
            scope=SearchScope.TITLE,
        ),
        replace(
            result_factory(SourceGroup.DECREE, uid="d1", title="주차장법 시행령"),
            scope=SearchScope.TITLE,
        ),
    )
    sections = sidebar_sections(
        _response(results, {"municipal": SourceState.LIVE, "laws": SourceState.LIVE}),
        pyeongtaek,
    )

    assert [section.label for section in sections] == ["자치법규", "상위법령"]
    national = sections[1]
    assert [(group.label, group.count) for group in national.groups] == [
        ("법률", 1),
        ("대통령령(시행령)", 1),
    ]
    assert national.groups[0].entries == (SidebarEntry("law:l1", "주차장법"),)


def test_sidebar_sections_lead_with_national_without_region(result_factory):
    results = (
        replace(
            result_factory(SourceGroup.LAW, uid="l1", title="주차장법"),
            scope=SearchScope.TITLE,
        ),
    )
    sections = sidebar_sections(_response(results, {"laws": SourceState.LIVE}))

    assert [section.label for section in sections] == ["상위법령"]


def test_sidebar_entry_count_equals_result_count(result_factory, pyeongtaek):
    results = (
        replace(result_factory(SourceGroup.MUNICIPAL, uid="m1"), scope=SearchScope.BODY),
        replace(result_factory(SourceGroup.PROVINCIAL, uid="p1"), scope=SearchScope.BODY),
        replace(result_factory(SourceGroup.LAW, uid="l1"), scope=SearchScope.TITLE),
        replace(result_factory(SourceGroup.LAW, uid="l2"), scope=SearchScope.BODY),
        replace(result_factory(SourceGroup.ADMIN_RULE, uid="a1"), scope=SearchScope.BODY),
    )
    sections = sidebar_sections(
        _response(
            results,
            {
                "municipal": SourceState.LIVE,
                "provincial": SourceState.LIVE,
                "laws": SourceState.LIVE,
                "admin_rules": SourceState.LIVE,
            },
        ),
        pyeongtaek,
    )

    total = sum(len(group.entries) for section in sections for group in section.groups)
    assert total == len(results)


def test_compare_options_cover_every_result_in_ranked_order(result_factory):
    results = (
        replace(
            result_factory(SourceGroup.LAW, uid="l1", title="주차장법"),
            scope=SearchScope.TITLE,
        ),
        replace(
            result_factory(SourceGroup.MUNICIPAL, uid="m1", title="평택시 주차장 조례"),
            scope=SearchScope.BODY,
        ),
    )
    options = compare_options(
        _response(results, {"laws": SourceState.LIVE, "municipal": SourceState.LIVE})
    )

    assert options == (
        CompareOption("law:l1", "법률 · 주차장법"),
        CompareOption("municipal:m1", "기초지자체 자치법규 · 평택시 주차장 조례"),
    )


def test_compare_options_allow_the_same_source_on_both_sides(result_factory):
    results = tuple(
        replace(
            result_factory(SourceGroup.LAW, uid=f"l{index}", title=f"법령 {index}"),
            scope=SearchScope.TITLE,
        )
        for index in range(2)
    )
    options = compare_options(_response(results, {"laws": SourceState.LIVE}))

    assert {option.key for option in options} == {"law:l0", "law:l1"}
