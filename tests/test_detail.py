import pytest

from lawsearch.detail import extract_contexts


def test_context_extraction_strips_html_and_finds_compact_spacing():
    payload = {"조문": [{"내용": "<p>부설주차장의 주차대수는 별표와 같다.</p>"}]}

    assert extract_contexts(payload, "주차 대수") == ("부설주차장의 주차대수는 별표와 같다.",)


def test_context_extraction_recurses_in_stable_order_and_decodes_entities():
    payload = {
        "first": {"text": "<div>주차 대수 &amp; 설치기준</div>"},
        "second": ["무관", {"text": "  주차\n대수 예외  "}],
    }

    assert extract_contexts(payload, "주차 대수") == ("주차 대수 & 설치기준", "주차 대수 예외")


def test_context_extraction_is_limited_and_deduplicated():
    payload = {"a": ["주차 대수 기준", "주차 대수 기준", "주차 대수 예외"]}

    assert extract_contexts(payload, "주차 대수", limit=1) == ("주차 대수 기준",)


def test_long_body_returns_a_bounded_excerpt_around_match():
    payload = {"본문": "앞" * 600 + " 주차 대수 " + "뒤" * 600}

    context = extract_contexts(payload, "주차 대수")[0]

    assert len(context) <= 400
    assert "주차 대수" in context
    assert context.startswith("…")
    assert context.endswith("…")


@pytest.mark.parametrize("limit", [0, -1])
def test_non_positive_limit_returns_no_contexts(limit):
    assert extract_contexts({"text": "주차 대수"}, "주차 대수", limit=limit) == ()
