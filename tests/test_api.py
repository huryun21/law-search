import asyncio
from datetime import UTC, datetime

import httpx
import pytest

from lawsearch.api import ApiError, LawApiClient
from lawsearch.models import MatchQuality, Region, SearchResult, SourceGroup


def run(awaitable):
    return asyncio.run(awaitable)


def test_search_requests_use_documented_current_body_search_parameters(pyeongtaek):
    seen = []

    def handler(request: httpx.Request):
        seen.append((request.url.path, dict(request.url.params)))
        return httpx.Response(200, json={"LawSearch": {"totalCnt": "0"}})

    client = LawApiClient("top-secret", httpx.MockTransport(handler))
    run(client.search_laws("주차 대수"))
    run(client.search_admin_rules("주차 대수", page=2))
    run(client.search_ordinances("주차 대수", pyeongtaek, province_only=False))
    run(client.search_ordinances("주차 대수", pyeongtaek, province_only=True))

    assert seen == [
        (
            "/DRF/lawSearch.do",
            {"OC": "top-secret", "target": "eflaw", "type": "JSON", "query": "주차 대수", "display": "100", "page": "1", "nw": "3", "search": "2"},
        ),
        (
            "/DRF/lawSearch.do",
            {"OC": "top-secret", "target": "admrul", "type": "JSON", "query": "주차 대수", "display": "100", "page": "2", "nw": "1", "search": "2"},
        ),
        (
            "/DRF/lawSearch.do",
            {"OC": "top-secret", "target": "ordin", "type": "JSON", "query": "주차 대수", "display": "100", "page": "1", "nw": "1", "search": "2", "org": pyeongtaek.org, "sborg": pyeongtaek.sborg},
        ),
        (
            "/DRF/lawSearch.do",
            {"OC": "top-secret", "target": "ordin", "type": "JSON", "query": "주차 대수", "display": "100", "page": "1", "nw": "1", "search": "2", "org": pyeongtaek.org},
        ),
    ]


def test_municipal_search_requires_a_municipality_code():
    region = Region("경기도", None, "6410000")
    client = LawApiClient("top-secret", httpx.MockTransport(lambda request: None))

    with pytest.raises(ValueError, match="기초"):
        run(client.search_ordinances("주차", region, province_only=False))


def test_term_suggestions_use_only_official_response_terms(load_fixture):
    seen = []

    def handler(request: httpx.Request):
        seen.append((request.url.path, dict(request.url.params)))
        if request.url.params["target"] == "lstrmAI":
            return httpx.Response(200, json=load_fixture("terms.json"))
        return httpx.Response(
            200,
            json={
                "DlytrmRlt": {
                    "target": "dlytrmRlt",
                    "검색결과개수": "2",
                    "연계용어": [
                        {"법령용어명": "부설주차장"},
                        {"법령용어명": "노외주차장"},
                    ],
                }
            },
        )

    client = LawApiClient("top-secret", httpx.MockTransport(handler))

    assert run(client.suggest_terms("주차")) == ("주차장", "부설주차장", "노외주차장")
    assert seen == [
        (
            "/DRF/lawSearch.do",
            {"OC": "top-secret", "target": "lstrmAI", "type": "JSON", "query": "주차", "display": "20", "page": "1"},
        ),
        (
            "/DRF/lawService.do",
            {"OC": "top-secret", "target": "dlytrmRlt", "type": "JSON", "query": "주차"},
        ),
    ]


@pytest.mark.parametrize(
    ("source", "uid", "target"),
    [
        (SourceGroup.LAW, "001498", "eflaw"),
        (SourceGroup.DECREE, "004743", "eflaw"),
        (SourceGroup.ADMIN_RULE, "2100000264373", "admrul"),
        (SourceGroup.MUNICIPAL, "2047729", "ordin"),
    ],
)
def test_detail_request_uses_source_target_and_result_id(source, uid, target):
    seen = {}

    def handler(request: httpx.Request):
        seen.update(dict(request.url.params))
        return httpx.Response(200, json={"detail": {}})

    result = SearchResult(
        uid=uid, source=source, quality=MatchQuality.EXACT, title="title", category="category",
        authority=None, region_name=None, promulgation_date=None, effective_date=None,
        is_current=True, official_url="https://www.law.go.kr/example", fetched_at=datetime.now(UTC),
    )
    client = LawApiClient("top-secret", httpx.MockTransport(handler))

    assert run(client.fetch_detail(result)) == {"detail": {}}
    assert seen == {"OC": "top-secret", "target": target, "type": "JSON", "ID": uid}


def test_error_messages_never_contain_key_or_request_url():
    def handler(request: httpx.Request):
        return httpx.Response(500, text="failure", request=request)

    client = LawApiClient("top-secret", httpx.MockTransport(handler))
    with pytest.raises(ApiError) as caught:
        run(client.search_laws("주차"))

    message = str(caught.value)
    assert "top-secret" not in message
    assert "OC=" not in message
    assert "http" not in message


@pytest.mark.parametrize(
    "response",
    [httpx.Response(200, json=[{"unexpected": "array"}]), httpx.Response(200, content=b"not-json")],
)
def test_non_object_or_invalid_json_is_a_sanitized_api_error(response):
    client = LawApiClient("top-secret", httpx.MockTransport(lambda request: response))

    with pytest.raises(ApiError) as caught:
        run(client.search_laws("주차"))
    assert str(caught.value) == "현행 법령 검색 응답을 처리할 수 없습니다."
