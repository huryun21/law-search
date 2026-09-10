from lawsearch.models import SearchScope, SourceState
from lawsearch.prioritization import (
    PRIORITY_KEYWORDS,
    classify_candidates,
    split_by_relevance,
)


def test_classify_candidates_splits_by_title_keyword(result_factory):
    from lawsearch.models import SourceGroup

    matching = result_factory(SourceGroup.LAW, uid="1", title="도시 및 주거환경정비법")
    other = result_factory(
        SourceGroup.LAW, uid="2", title="관세법", scope=SearchScope.BODY
    )
    candidates = (
        (matching, SourceState.LIVE),
        (other, SourceState.LIVE),
    )

    priority, rest = classify_candidates(candidates, ("도시",))

    assert priority == ((matching, SourceState.LIVE),)
    assert rest == ((other, SourceState.LIVE),)


def test_classify_candidates_always_treats_a_title_scope_match_as_priority(
    result_factory,
):
    """A TITLE-scope result means the user's own search term appears in the
    document's title -- the app's highest-priority match regardless of domain
    (CLAUDE.md: 정확 문구 우선). Deferring it to the background queue just
    because its title has no domain keyword would both delay it and wrongly
    mark it "새로 확인된 결과" once confirmed, even though it was there from
    the very first search."""
    from lawsearch.models import SourceGroup

    title_match = result_factory(
        SourceGroup.LAW, uid="1", title="관세법", scope=SearchScope.TITLE
    )
    candidates = ((title_match, SourceState.LIVE),)

    priority, rest = classify_candidates(candidates, ("도시",))

    assert priority == ((title_match, SourceState.LIVE),)
    assert rest == ()


def test_classify_candidates_caps_title_scope_matches_to_bound_first_render_latency(
    result_factory,
):
    """A generic keyword (e.g. "심의") can be an exact TITLE match for
    hundreds of documents nationwide -- always verifying every one of them
    synchronously (so none is wrongly badged "새로 확인된 결과") would block
    the very first page render for minutes. Past the cap, the overflow still
    goes through the background queue -- verified soon, just not blocking."""
    from lawsearch.models import SourceGroup

    title_matches = tuple(
        result_factory(
            SourceGroup.LAW, uid=str(i), title=f"제목{i} 심의", scope=SearchScope.TITLE
        )
        for i in range(3)
    )
    candidates = tuple((r, SourceState.LIVE) for r in title_matches)

    priority, rest = classify_candidates(candidates, ("도시",), max_title_priority=2)

    assert priority == candidates[:2]
    assert rest == candidates[2:]


def test_classify_candidates_treats_all_as_priority_when_no_keywords(result_factory):
    from lawsearch.models import SourceGroup

    a = result_factory(SourceGroup.LAW, uid="1", title="관세법")
    candidates = ((a, SourceState.LIVE),)

    priority, rest = classify_candidates(candidates, ())

    assert priority == candidates
    assert rest == ()


def test_priority_keywords_constant_is_nonempty():
    assert len(PRIORITY_KEYWORDS) > 0
    assert "도시" in PRIORITY_KEYWORDS
    assert "소방" in PRIORITY_KEYWORDS


def test_split_by_relevance_separates_results_by_title_keyword(result_factory):
    from lawsearch.models import SourceGroup

    relevant = result_factory(SourceGroup.LAW, uid="1", title="도시 및 주거환경정비법")
    less_relevant = result_factory(SourceGroup.LAW, uid="2", title="관세법")

    kept, hidden = split_by_relevance((relevant, less_relevant), ("도시",))

    assert kept == (relevant,)
    assert hidden == (less_relevant,)


def test_split_by_relevance_treats_all_as_relevant_when_no_keywords(result_factory):
    from lawsearch.models import SourceGroup

    a = result_factory(SourceGroup.LAW, uid="1", title="관세법")

    kept, hidden = split_by_relevance((a,), ())

    assert kept == (a,)
    assert hidden == ()
