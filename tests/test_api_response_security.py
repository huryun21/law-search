import asyncio

import httpx

from lawsearch.api import LawApiClient
from lawsearch.cache import CacheStore


def test_response_detail_links_are_stripped_of_echoed_credentials_before_cache(tmp_path):
    secret = "response-secret"
    payload = {
        "LawSearch": {
            "law": {
                "법령상세링크": "/법령/예시?query=주차&OC=" + secret + "&target=eflaw"
            }
        }
    }
    client = LawApiClient(
        secret, httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    )

    returned = asyncio.run(client.search_laws("주차"))
    link = returned["LawSearch"]["law"]["법령상세링크"]
    CacheStore(tmp_path / "cache.db").put("safe", returned)

    assert "OC=" not in link
    assert secret not in link
    assert "query=" in link
    assert "target=eflaw" in link
    assert secret.encode() not in (tmp_path / "cache.db").read_bytes()
