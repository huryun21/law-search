import pytest

from lawsearch.detail import extract_contexts


def test_law_context_ignores_appendix_and_keeps_article_paragraph_item_location():
    payload = {
        "법령": {
            "부칙": {
                "부칙단위": [
                    {"부칙내용": ["주차장법 일부를 다음과 같이 개정한다."]}
                ]
            },
            "조문": {
                "조문단위": [
                    {
                        "조문번호": "74",
                        "조문제목": "통합적용계획의 수립 및 시행",
                        "항": [
                            {
                                "항번호": "①",
                                "항내용": "① 다음 각 호의 규정을 통합하여 적용할 수 있다.",
                                "호": [
                                    {
                                        "호번호": "2.",
                                        "호내용": "2. 「주차장법」 제19조에 따른 부설주차장의 설치",
                                    }
                                ],
                            }
                        ],
                    }
                ]
            },
        }
    }

    assert extract_contexts(payload, "주차장") == (
        "제74조(통합적용계획의 수립 및 시행) > 제1항 > 제2호 — "
        "「주차장법」 제19조에 따른 부설주차장의 설치",
    )


def test_article_title_match_precedes_an_earlier_body_only_match():
    payload = {
        "법령": {
            "조문": {
                "조문단위": [
                    {
                        "조문번호": "3",
                        "조문제목": "정의",
                        "조문내용": "주차장은 자동차를 세우는 시설을 말한다.",
                    },
                    {
                        "조문번호": "19",
                        "조문제목": "부설주차장의 설치",
                        "조문내용": "시설물에는 기준에 맞는 공간을 설치하여야 한다.",
                    },
                ]
            }
        }
    }

    contexts = extract_contexts(payload, "주차장")

    assert contexts[0].startswith("제19조(부설주차장의 설치) —")
    assert contexts[1] == "제3조(정의) — 주차장은 자동차를 세우는 시설을 말한다."


def test_specific_short_item_precedes_a_long_incidental_paragraph():
    payload = {
        "법령": {
            "조문": {
                "조문단위": [
                    {
                        "조문번호": "1",
                        "조문제목": "계획서",
                        "항": {
                            "항번호": "①",
                            "항내용": "① " + "운영관리 계획의 일반사항 " * 12 + "부설주차장도 포함한다.",
                        },
                    },
                    {
                        "조문번호": "2",
                        "조문제목": "적용대상",
                        "항": {
                            "항번호": "①",
                            "항내용": "① 다음 각 호를 적용한다.",
                            "호": {
                                "호번호": "2.",
                                "호내용": "2. 부설주차장의 설치기준",
                            },
                        },
                    },
                ]
            }
        }
    }

    contexts = extract_contexts(payload, "주차장")

    assert contexts[0] == "제2조(적용대상) > 제1항 > 제2호 — 부설주차장의 설치기준"


def test_ordinance_law_service_shape_returns_article_heading():
    payload = {
        "LawService": {
            "조문": {
                "조": {
                    "조문번호": ["001500", "001500"],
                    "조제목": "부설주차장의 인근 설치",
                    "조내용": "제15조(부설주차장의 인근 설치) 주차대수가 300대 이하인 경우 설치할 수 있다.",
                }
            }
        }
    }

    assert extract_contexts(payload, "주차 대수") == (
        "제15조(부설주차장의 인근 설치) — "
        "주차대수가 300대 이하인 경우 설치할 수 있다.",
    )


def test_non_article_metadata_is_not_returned_as_a_context():
    payload = {
        "법령": {
            "기본정보": {"검색문구": "주차장"},
            "부칙": {"부칙내용": "주차장법 일부를 개정한다."},
            "조문": {"조문단위": []},
        }
    }

    assert extract_contexts(payload, "주차장") == ()


def test_long_article_context_is_bounded_and_deduplicated():
    payload = {
        "법령": {
            "조문": {
                "조문단위": [
                    {
                        "조문번호": "1",
                        "조문제목": "설치기준",
                        "조문내용": "앞" * 600 + " 주차 대수 " + "뒤" * 600,
                    },
                    {
                        "조문번호": "1",
                        "조문제목": "설치기준",
                        "조문내용": "앞" * 600 + " 주차 대수 " + "뒤" * 600,
                    },
                ]
            }
        }
    }

    contexts = extract_contexts(payload, "주차 대수")

    assert len(contexts) == 1
    assert len(contexts[0]) <= 400
    assert "주차 대수" in contexts[0]
    assert contexts[0].startswith("제1조(설치기준) — …")
    assert contexts[0].endswith("…")


@pytest.mark.parametrize("limit", [0, -1])
def test_non_positive_limit_returns_no_contexts(limit):
    assert extract_contexts({"조문": {"조문단위": []}}, "주차 대수", limit=limit) == ()
