from collections.abc import Mapping
from typing import Any

import httpx

from lawsearch.models import Region, SearchResult, SourceGroup


class ApiError(RuntimeError):
    pass


class LawApiClient:
    _BASE_URL = "https://www.law.go.kr/DRF/"

    def __init__(
        self,
        api_key: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=self._BASE_URL,
            transport=transport,
            timeout=10.0,
            follow_redirects=False,
        )

    async def __aenter__(self) -> "LawApiClient":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if not self._client.is_closed:
            await self._client.aclose()

    async def _request_json(
        self,
        path: str,
        safe_operation: str,
        params: Mapping[str, str],
    ) -> dict[str, Any]:
        request_params = {"OC": self._api_key, **params}
        error: ApiError | None = None
        try:
            response = await self._client.get(path, params=request_params)
            response.raise_for_status()
            payload = response.json()
        except Exception:
            error = ApiError(f"{safe_operation} 응답을 처리할 수 없습니다.")
            payload = None
        if error is not None:
            raise error
        if not isinstance(payload, dict):
            raise ApiError(f"{safe_operation} 응답을 처리할 수 없습니다.")
        return payload

    async def search_laws(self, query: str, page: int = 1) -> dict[str, Any]:
        return await self._request_json(
            "lawSearch.do",
            "현행 법령 검색",
            self._search_params("eflaw", query, page, nw="3"),
        )

    async def search_admin_rules(self, query: str, page: int = 1) -> dict[str, Any]:
        return await self._request_json(
            "lawSearch.do",
            "행정규칙 검색",
            self._search_params("admrul", query, page, nw="1"),
        )

    async def search_ordinances(
        self,
        query: str,
        region: Region,
        province_only: bool,
        page: int = 1,
    ) -> dict[str, Any]:
        params = self._search_params("ordin", query, page, nw="1")
        params["org"] = region.org
        if not province_only:
            if region.sborg is None:
                raise ValueError("기초자치단체 검색에는 기초 기관코드가 필요합니다.")
            params["sborg"] = region.sborg
        return await self._request_json("lawSearch.do", "자치법규 검색", params)

    async def suggest_terms(self, query: str) -> tuple[str, ...]:
        search_payload = await self._request_json(
            "lawSearch.do",
            "법령용어 검색",
            {
                "target": "lstrmAI",
                "type": "JSON",
                "query": query,
                "display": "20",
                "page": "1",
            },
        )
        related_payload = await self._request_json(
            "lawService.do",
            "일상용어 연계 검색",
            {"target": "dlytrmRlt", "type": "JSON", "query": query},
        )
        terms: list[str] = []
        self._collect_values(search_payload, "법령용어명", terms)
        self._collect_values(related_payload, "법령용어명", terms)
        return tuple(dict.fromkeys(term.strip() for term in terms if term.strip()))

    async def fetch_detail(self, result: SearchResult) -> dict[str, Any]:
        target_by_source = {
            SourceGroup.LAW: "eflaw",
            SourceGroup.DECREE: "eflaw",
            SourceGroup.MINISTERIAL_RULE: "eflaw",
            SourceGroup.OTHER: "eflaw",
            SourceGroup.ADMIN_RULE: "admrul",
            SourceGroup.MUNICIPAL: "ordin",
            SourceGroup.PROVINCIAL: "ordin",
        }
        target = target_by_source[result.source]
        identifier = "LID" if result.source is SourceGroup.ADMIN_RULE else "ID"
        return await self._request_json(
            "lawService.do",
            "본문 조회",
            {"target": target, "type": "JSON", identifier: result.uid},
        )

    @staticmethod
    def _search_params(target: str, query: str, page: int, *, nw: str) -> dict[str, str]:
        return {
            "target": target,
            "type": "JSON",
            "query": query,
            "display": "100",
            "page": str(page),
            "nw": nw,
            "search": "2",
        }

    @classmethod
    def _collect_values(cls, value: Any, key: str, output: list[str]) -> None:
        if isinstance(value, Mapping):
            for item_key, item_value in value.items():
                if item_key == key and isinstance(item_value, str):
                    output.append(item_value)
                else:
                    cls._collect_values(item_value, key, output)
        elif isinstance(value, list):
            for item in value:
                cls._collect_values(item, key, output)
