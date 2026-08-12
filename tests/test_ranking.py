from lawsearch.models import MatchQuality, SourceGroup
from lawsearch.ranking import rank_results


def test_regional_group_order(result_factory, pyeongtaek):
    unordered = [
        result_factory(SourceGroup.OTHER),
        result_factory(SourceGroup.ADMIN_RULE),
        result_factory(SourceGroup.LAW),
        result_factory(SourceGroup.PROVINCIAL),
        result_factory(SourceGroup.MUNICIPAL),
        result_factory(SourceGroup.DECREE),
        result_factory(SourceGroup.MINISTERIAL_RULE),
    ]

    ranked = rank_results(unordered, pyeongtaek)

    assert [item.source for item in ranked] == [
        SourceGroup.MUNICIPAL,
        SourceGroup.PROVINCIAL,
        SourceGroup.LAW,
        SourceGroup.DECREE,
        SourceGroup.MINISTERIAL_RULE,
        SourceGroup.ADMIN_RULE,
        SourceGroup.OTHER,
    ]


def test_nonregional_group_order_excludes_no_group(result_factory):
    unordered = [
        result_factory(SourceGroup.PROVINCIAL, title="a"),
        result_factory(SourceGroup.MUNICIPAL, title="a"),
        result_factory(SourceGroup.OTHER),
        result_factory(SourceGroup.ADMIN_RULE),
        result_factory(SourceGroup.MINISTERIAL_RULE),
        result_factory(SourceGroup.DECREE),
        result_factory(SourceGroup.LAW),
    ]

    assert [item.source for item in rank_results(unordered, None)] == [
        SourceGroup.LAW,
        SourceGroup.DECREE,
        SourceGroup.MINISTERIAL_RULE,
        SourceGroup.ADMIN_RULE,
        SourceGroup.OTHER,
        SourceGroup.MUNICIPAL,
        SourceGroup.PROVINCIAL,
    ]


def test_match_quality_precedes_effective_date(result_factory):
    compact = result_factory(
        SourceGroup.LAW, quality=MatchQuality.COMPACT, effective="20260811"
    )
    exact = result_factory(
        SourceGroup.LAW, quality=MatchQuality.EXACT, effective="20200101"
    )

    assert rank_results([compact, exact], None) == (exact, compact)


def test_current_then_effective_date_descending_then_title_are_deterministic(
    result_factory,
):
    old = result_factory(SourceGroup.LAW, uid="old", effective="20200101", title="z")
    new_b = result_factory(SourceGroup.LAW, uid="b", effective="20250101", title="b")
    new_a = result_factory(SourceGroup.LAW, uid="a", effective="20250101", title="a")
    repealed = result_factory(
        SourceGroup.LAW, uid="repealed", effective="20260101", current=False
    )

    assert rank_results([repealed, new_b, old, new_a], None) == (
        new_a,
        new_b,
        old,
        repealed,
    )
