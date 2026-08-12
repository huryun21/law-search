import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from typing import Any

from lawsearch.api import ApiError, LawApiClient
from lawsearch.cache import CacheStore, make_cache_key
from lawsearch.detail import extract_contexts
from lawsearch.models import (
    DetailResponse,
    MatchQuality,
    ParsedQuery,
    SearchResponse,
    SearchResult,
    SourceError,
    SourceGroup,
    SourceState,
)
from lawsearch.normalize import ResponseShapeError, normalize_results
from lawsearch.query import build_query_variants
from lawsearch.ranking import rank_results


SourceOutcome = tuple[
    tuple[SearchResult, ...], SourceState, bool, datetime | None
]


class SearchValidationError(ValueError):
    pass


class SearchService:
    def __init__(
        self,
        api: LawApiClient,
        cache: CacheStore,
        clock: Callable[[], datetime],
    ) -> None:
        self._api = api
        self._cache = cache
        self._clock = clock

    async def search(
        self, parsed: ParsedQuery, refresh: bool = False, page: int = 1
    ) -> SearchResponse:
        if parsed.candidates:
            raise SearchValidationError("지역 후보를 하나로 확정해야 검색할 수 있습니다.")

        sources = [
            ("laws", SourceGroup.LAW),
            ("admin_rules", SourceGroup.ADMIN_RULE),
        ]
        if parsed.region is not None:
            if parsed.region.sborg is not None:
                sources.append(("municipal", SourceGroup.MUNICIPAL))
            sources.append(("provincial", SourceGroup.PROVINCIAL))

        source_tasks = [
            self._search_source(name, group, parsed, refresh, page)
            for name, group in sources
        ]
        gathered = await asyncio.gather(
            *source_tasks,
            self._suggest(parsed.keyword, refresh),
            return_exceptions=True,
        )

        results: list[SearchResult] = []
        errors: list[SourceError] = []
        states: dict[str, SourceState] = {}
        fetched_at: dict[str, datetime] = {}
        for (name, _), outcome in zip(sources, gathered[:-1]):
            if isinstance(outcome, BaseException):
                states[name] = SourceState.ERROR
                errors.append(SourceError(name, f"{name} search failed"))
                continue
            source_results, state, source_error, source_fetched_at = outcome
            results.extend(source_results)
            states[name] = state
            if source_fetched_at is not None:
                fetched_at[name] = source_fetched_at
            if source_error is not None:
                errors.append(source_error)

        suggestion_outcome = gathered[-1]
        if isinstance(suggestion_outcome, BaseException):
            suggestions = ()
            errors.append(SourceError("terms", "terms search failed"))
        else:
            suggestions = suggestion_outcome

        return SearchResponse(
            results=rank_results(_deduplicate(results), parsed.region),
            suggestions=suggestions,
            errors=tuple(errors),
            source_states=states,
            source_fetched_at=fetched_at,
        )

    async def load_contexts(
        self,
        result: SearchResult,
        keyword: str,
        refresh: bool = False,
    ) -> DetailResponse:
        now = self._clock()
        key = make_cache_key(
            result.source.value, keyword, (), 1, detail_id=result.uid
        )
        cached = self._cache.get(key, now)
        if cached is not None and cached.is_fresh and not refresh:
            return DetailResponse(
                extract_contexts(cached.payload, keyword),
                SourceState.FRESH_CACHE,
                cached.fetched_at,
            )
        try:
            payload = await self._api.fetch_detail(result)
        except Exception:
            if cached is None:
                return DetailResponse((), SourceState.ERROR, now)
            return DetailResponse(
                extract_contexts(cached.payload, keyword),
                SourceState.STALE_FALLBACK,
                cached.fetched_at,
            )
        self._cache.put(key, payload, now)
        contexts = extract_contexts(payload, keyword)
        return DetailResponse(
            contexts,
            SourceState.LIVE if contexts else SourceState.EMPTY,
            now,
        )

    async def _search_source(
        self,
        name: str,
        group: SourceGroup,
        parsed: ParsedQuery,
        refresh: bool,
        page: int,
    ) -> tuple[
        tuple[SearchResult, ...], SourceState, SourceError | None, datetime | None
    ]:
        outcomes = []
        for variant in build_query_variants(parsed.keyword):
            outcomes.append(
                await self._search_variant(
                    name,
                    group,
                    variant.query,
                    variant.quality,
                    parsed,
                    refresh,
                    page,
                )
            )

        retained = _retain_best_results(outcomes)
        had_failure = any(outcome[2] for outcome in outcomes)
        if not retained and not had_failure:
            tokens = tuple(dict.fromkeys(parsed.keyword.split()))
            if len(tokens) >= 2:
                token_outcomes = []
                for token in tokens:
                    outcome = await self._search_variant(
                        name,
                        group,
                        token,
                        MatchQuality.ALL_TERMS,
                        parsed,
                        refresh,
                        page,
                    )
                    token_outcomes.append(outcome)
                    outcomes.append(outcome)
                retained = _intersect_token_outcomes(token_outcomes)

        state = _combine_state(outcomes, retained)
        error = SourceError(name, f"{name} search failed") if any(
            outcome[2] for outcome in outcomes
        ) else None
        source_fetched_at = (
            min(item.fetched_at for item, _ in retained)
            if retained
            else _outcome_fetched_at(outcomes, state)
        )
        return tuple(item[0] for item in retained), state, error, source_fetched_at

    async def _search_variant(
        self,
        name: str,
        group: SourceGroup,
        query: str,
        quality: MatchQuality,
        parsed: ParsedQuery,
        refresh: bool,
        page: int,
    ) -> SourceOutcome:
        now = self._clock()
        region_codes = _region_codes(parsed, name)
        key = make_cache_key(name, query, region_codes, page)
        cached = self._cache.get(key, now)
        if cached is not None and cached.is_fresh and not refresh:
            return (
                normalize_results(cached.payload, group, quality, cached.fetched_at),
                SourceState.FRESH_CACHE,
                False,
                cached.fetched_at,
            )
        try:
            payload = await self._call_source(name, query, parsed, page)
            fetched_at = self._clock()
            normalized = normalize_results(payload, group, quality, fetched_at)
        except (ApiError, ResponseShapeError):
            if cached is None:
                return (), SourceState.ERROR, True, None
            return (
                normalize_results(cached.payload, group, quality, cached.fetched_at),
                SourceState.STALE_FALLBACK,
                True,
                cached.fetched_at,
            )
        self._cache.put(key, payload, fetched_at)
        return (
            normalized,
            SourceState.LIVE if normalized else SourceState.EMPTY,
            False,
            fetched_at,
        )

    async def _call_source(
        self, name: str, query: str, parsed: ParsedQuery, page: int
    ) -> dict[str, Any]:
        if name == "laws":
            return await self._api.search_laws(query, page)
        if name == "admin_rules":
            return await self._api.search_admin_rules(query, page)
        if parsed.region is None:
            raise SearchValidationError("지역 없는 자치법규 검색은 허용되지 않습니다.")
        return await self._api.search_ordinances(
            query,
            parsed.region,
            province_only=name == "provincial",
            page=page,
        )

    async def _suggest(self, keyword: str, refresh: bool) -> tuple[str, ...]:
        now = self._clock()
        key = make_cache_key("terms", keyword, (), 1)
        cached = self._cache.get(key, now)
        if cached is not None and cached.is_fresh and not refresh:
            values = cached.payload.get("suggestions", [])
            return tuple(str(value) for value in values)
        suggestions = await self._api.suggest_terms(keyword)
        self._cache.put(key, {"suggestions": list(suggestions)}, now)
        return suggestions


def _region_codes(parsed: ParsedQuery, name: str) -> tuple[str, ...]:
    if parsed.region is None or name not in {"municipal", "provincial"}:
        return ()
    if name == "provincial":
        return (parsed.region.org,)
    return tuple(code for code in (parsed.region.org, parsed.region.sborg) if code)


def _deduplicate(results: list[SearchResult]) -> tuple[SearchResult, ...]:
    best: dict[tuple[SourceGroup, str], SearchResult] = {}
    for result in results:
        key = (result.source, result.uid)
        current = best.get(key)
        if current is None or result.quality < current.quality:
            best[key] = result
    return tuple(best.values())


def _retain_best_results(
    outcomes: list[SourceOutcome],
) -> tuple[tuple[SearchResult, SourceState], ...]:
    best: dict[tuple[SourceGroup, str], tuple[SearchResult, SourceState]] = {}
    for results, state, _, _ in outcomes:
        for result in results:
            key = (result.source, result.uid)
            retained = best.get(key)
            if retained is None or result.quality < retained[0].quality:
                best[key] = (result, state)
    return tuple(best.values())


def _intersect_token_outcomes(
    outcomes: list[SourceOutcome],
) -> tuple[tuple[SearchResult, SourceState], ...]:
    if not outcomes or any(not outcome[0] for outcome in outcomes):
        return ()
    common = {(item.source, item.uid) for item in outcomes[0][0]}
    for results, _, _, _ in outcomes[1:]:
        common &= {(item.source, item.uid) for item in results}

    retained = []
    for item in outcomes[0][0]:
        key = (item.source, item.uid)
        if key not in common:
            continue
        contributors = [
            (candidate, state)
            for results, state, _, _ in outcomes
            for candidate in results
            if (candidate.source, candidate.uid) == key
        ]
        retained.append(
            (
                replace(
                    item,
                    quality=MatchQuality.ALL_TERMS,
                    fetched_at=min(candidate.fetched_at for candidate, _ in contributors),
                ),
                _result_state([state for _, state in contributors]),
            )
        )
    return tuple(retained)


def _combine_state(
    outcomes: list[SourceOutcome],
    retained: tuple[tuple[SearchResult, SourceState], ...],
) -> SourceState:
    if retained:
        return _result_state([state for _, state in retained])

    states = {outcome[1] for outcome in outcomes}
    if SourceState.STALE_FALLBACK in states:
        return SourceState.STALE_FALLBACK
    if SourceState.ERROR in states:
        return SourceState.ERROR
    if SourceState.EMPTY in states:
        return SourceState.EMPTY
    if SourceState.FRESH_CACHE in states:
        return SourceState.FRESH_CACHE
    return SourceState.EMPTY


def _outcome_fetched_at(
    outcomes: list[SourceOutcome], state: SourceState
) -> datetime | None:
    timestamps = [
        fetched_at
        for _, outcome_state, _, fetched_at in outcomes
        if outcome_state is state and fetched_at is not None
    ]
    return min(timestamps) if timestamps else None


def _result_state(states: list[SourceState]) -> SourceState:
    if SourceState.STALE_FALLBACK in states:
        return SourceState.STALE_FALLBACK
    if SourceState.LIVE in states:
        return SourceState.LIVE
    return SourceState.FRESH_CACHE
