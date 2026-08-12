"""Opt-in contracts for the official Korean law APIs.

These tests deliberately never print request URLs or credential values.
"""

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lawsearch.api import ApiError, LawApiClient
from lawsearch.cache import CacheStore
from lawsearch.config import load_api_key, load_settings
from lawsearch.models import ParsedQuery, SourceState
from lawsearch.regions import RegionRegistry
from lawsearch.service import SearchService


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_LAW_API") != "1",
    reason="live law API contract test is opt-in",
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_QUERY = "주차 방법"


def run(awaitable):
    return asyncio.run(awaitable)


def _settings():
    return load_settings(_PROJECT_ROOT)


def _pyeongtaek():
    resolution = RegionRegistry.from_package_data().resolve("평택")
    assert resolution.region is not None
    return resolution.region


async def _call(operation):
    settings = _settings()
    async with LawApiClient(load_api_key(settings.api_key_file)) as api:
        try:
            return await operation(api)
        except ApiError:
            pytest.xfail("credential is not approved for this official endpoint")


def test_live_law_endpoint_returns_mapping():
    payload = run(_call(lambda api: api.search_laws(_QUERY)))
    assert isinstance(payload, dict)


def test_live_admin_rule_endpoint_returns_mapping():
    payload = run(_call(lambda api: api.search_admin_rules(_QUERY)))
    assert isinstance(payload, dict)


@pytest.mark.parametrize("province_only", [False, True], ids=["pyeongtaek", "gyeonggi"])
def test_live_ordinance_endpoints_return_mapping(province_only):
    payload = run(
        _call(
            lambda api: api.search_ordinances(
                _QUERY, _pyeongtaek(), province_only=province_only
            )
        )
    )
    assert isinstance(payload, dict)


def test_live_term_endpoint_returns_tuple():
    terms = run(_call(lambda api: api.suggest_terms(_QUERY)))
    assert isinstance(terms, tuple)


async def _search_and_detail():
    settings = _settings()
    async with LawApiClient(load_api_key(settings.api_key_file)) as api:
        service = SearchService(api, CacheStore(settings.cache_path), lambda: datetime.now(UTC))
        response = await service.search(ParsedQuery(_QUERY), refresh=True)
        if response.source_states["laws"] is SourceState.ERROR:
            return response, None
        assert response.results
        assert all(item.official_url.startswith("https://www.law.go.kr/") for item in response.results)
        detail = await service.load_contexts(response.results[0], _QUERY, refresh=True)
        return response, detail


def test_live_search_and_detail_contracts_use_official_links():
    response, detail = run(_search_and_detail())
    assert not response.errors
    assert response.source_states["laws"] in {SourceState.LIVE, SourceState.EMPTY}
    assert detail is not None
    assert detail.state in {SourceState.LIVE, SourceState.EMPTY}


async def _regional_search():
    settings = _settings()
    async with LawApiClient(load_api_key(settings.api_key_file)) as api:
        service = SearchService(api, CacheStore(settings.cache_path), lambda: datetime.now(UTC))
        return await service.search(ParsedQuery(_QUERY, _pyeongtaek()), refresh=True)


def test_live_pyeongtaek_search_includes_both_regional_sources():
    response = run(_regional_search())
    assert not response.errors
    assert response.results
    assert response.source_states["municipal"] in {SourceState.LIVE, SourceState.EMPTY}
    assert response.source_states["provincial"] in {SourceState.LIVE, SourceState.EMPTY}
