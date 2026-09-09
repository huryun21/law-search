from lawsearch.models import SourceState
from lawsearch.prioritization import (
    PRIORITY_KEYWORDS,
    classify_candidates,
    split_by_relevance,
)


def test_classify_candidates_splits_by_title_keyword(result_factory):
    from lawsearch.models import SourceGroup

    matching = result_factory(SourceGroup.LAW, uid="1", title="도시 및 주거환경정비법")
    other = result_factory(SourceGroup.LAW, uid="2", title="관세법")
    candidates = (
        (matching, SourceState.LIVE),
        (other, SourceState.LIVE),
    )

    priority, rest = classify_candidates(candidates, ("도시",))

    assert priority == ((matching, SourceState.LIVE),)
    assert rest == ((other, SourceState.LIVE),)


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
