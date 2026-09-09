import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
import re
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
    SearchScope,
    SourceError,
    SourceGroup,
    SourceState,
)
from lawsearch.normalize import ResponseShapeError, extract_total_count, normalize_results
from lawsearch.prioritization import classify_candidates
from lawsearch.query import build_query_variants
from lawsearch.ranking import rank_results


SourceOutcome = tuple[
    tuple[SearchResult, ...], SourceState, bool, datetime | None
]
# Raised from 4 after confirming against the live API that 16 concurrent
# requests complete with no errors and no visible slowdown per request
# (2026-09-09). Detail-verification throughput was the main bottleneck behind
# slow searches once pagination started fetching every page of candidates.
_DETAIL_VERIFICATION_CONCURRENCY = 8


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
        self,
        parsed: ParsedQuery,
        refresh: bool = False,
        page: int = 1,
        priority_keywords: tuple[str, ...] = (),
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

        detail_semaphore = asyncio.Semaphore(_DETAIL_VERIFICATION_CONCURRENCY)
        source_tasks = [
            self._search_source(
                name, group, parsed, refresh, page, detail_semaphore, priority_keywords
            )
            for name, group in sources
        ]
        gathered = await asyncio.gather(
            *source_tasks,
            self._suggest(parsed.keyword, refresh),
            return_exceptions=True,
        )

        results: list[SearchResult] = []
        pending: list[SearchResult] = []
        errors: list[SourceError] = []
        states: dict[str, SourceState] = {}
        fetched_at: dict[str, datetime] = {}
        for (name, _), outcome in zip(sources, gathered[:-1]):
            if isinstance(outcome, BaseException):
                states[name] = SourceState.ERROR
                errors.append(SourceError(name, f"{name} search failed"))
                continue
            source_results, state, source_error, source_fetched_at, source_pending = outcome
            results.extend(source_results)
            pending.extend(source_pending)
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
            results=rank_results(_deduplicate(results), parsed.region, parsed.keyword),
            pending=tuple(pending),
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
        *,
        limit: int = 5,
    ) -> DetailResponse:
        now = self._clock()
        key = make_cache_key(
            result.source.value, keyword, (), 1, detail_id=result.uid
        )
        cached = self._cache.get(key, now)
        if cached is not None and cached.is_fresh and not refresh:
            return DetailResponse(
                extract_contexts(cached.payload, keyword, limit),
                SourceState.FRESH_CACHE,
                cached.fetched_at,
            )
        try:
            payload = await self._api.fetch_detail(result)
        except Exception:
            if cached is None:
                return DetailResponse((), SourceState.ERROR, now)
            return DetailResponse(
                extract_contexts(cached.payload, keyword, limit),
                SourceState.STALE_FALLBACK,
                cached.fetched_at,
            )
        self._cache.put(key, payload, now)
        contexts = extract_contexts(payload, keyword, limit)
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
        detail_semaphore: asyncio.Semaphore,
        priority_keywords: tuple[str, ...] = (),
    ) -> tuple[
        tuple[SearchResult, ...],
        SourceState,
        SourceError | None,
        datetime | None,
        tuple[SearchResult, ...],
    ]:
        variants = build_query_variants(parsed.keyword)
        outcomes = [
            await self._search_variant(
                name,
                group,
                variants[0].query,
                variants[0].quality,
                parsed,
                refresh,
                page,
                SearchScope.TITLE,
            )
        ]
        for variant in variants:
            outcomes.append(
                await self._search_variant(
                    name,
                    group,
                    variant.query,
                    variant.quality,
                    parsed,
                    refresh,
                    page,
                    SearchScope.BODY,
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
                        SearchScope.BODY,
                    )
                    token_outcomes.append(outcome)
                    outcomes.append(outcome)
                retained = _intersect_token_outcomes(token_outcomes)

        priority, rest = classify_candidates(retained, priority_keywords)

        retained, validation_failed = await self._verify_body_results(
            priority,
            parsed.keyword,
            refresh,
            detail_semaphore,
        )
        state = (
            SourceState.ERROR
            if validation_failed and not retained
            else _combine_state(outcomes, retained)
        )
        error = (
            SourceError(name, f"{name} search failed")
            if validation_failed or any(outcome[2] for outcome in outcomes)
            else None
        )
        source_fetched_at = (
            min(item.fetched_at for item, _ in retained)
            if retained
            else _outcome_fetched_at(outcomes, state)
        )
        pending = tuple(result for result, _ in rest)
        return (
            tuple(item[0] for item in retained),
            state,
            error,
            source_fetched_at,
            pending,
        )

    async def _verify_one(
        self,
        result: SearchResult,
        keyword: str,
        refresh: bool,
        semaphore: asyncio.Semaphore,
    ) -> tuple[SearchResult | None, bool]:
        if result.scope is SearchScope.TITLE and _title_matches_query(
            result.title, keyword
        ):
            return result, False
        async with semaphore:
            detail = await self.load_contexts(result, keyword, refresh)
        if detail.state is SourceState.ERROR:
            return None, True
        if not detail.contexts:
            return None, False
        context = detail.contexts[0]
        if result.scope is SearchScope.TITLE:
            return replace(result, scope=SearchScope.BODY, match_context=context), False
        return replace(result, match_context=context), False

    async def _verify_body_results(
        self,
        retained: tuple[tuple[SearchResult, SourceState], ...],
        keyword: str,
        refresh: bool,
        semaphore: asyncio.Semaphore,
    ) -> tuple[tuple[tuple[SearchResult, SourceState], ...], bool]:
        async def verify(
            item: tuple[SearchResult, SourceState],
        ) -> tuple[tuple[SearchResult, SourceState] | None, bool]:
            result, state = item
            verified, failed = await self._verify_one(result, keyword, refresh, semaphore)
            if verified is None:
                return None, failed
            return (verified, state), failed

        verified = await asyncio.gather(*(verify(item) for item in retained))
        return (
            tuple(item for item, _ in verified if item is not None),
            any(failed for _, failed in verified),
        )

    async def verify_pending(
        self,
        pending: tuple[SearchResult, ...],
        keyword: str,
        refresh: bool = False,
    ) -> tuple[tuple[SearchResult, ...], int]:
        """Verify a batch of previously-deferred candidates.

        Returns the confirmed exact matches and how many candidates could not
        be checked at all (their detail fetch failed). A candidate that was
        checked and simply has no exact match is not a failure -- it is a
        correct rejection, and counting it would be indistinguishable from a
        real match this search never got to see. This stays best-effort
        background work rather than a source of user-facing errors, but the
        caller needs the failure count to tell the user something went
        unchecked instead of dropping it in silence.
        """
        semaphore = asyncio.Semaphore(_DETAIL_VERIFICATION_CONCURRENCY)
        verified = await asyncio.gather(
            *(self._verify_one(result, keyword, refresh, semaphore) for result in pending)
        )
        return (
            tuple(result for result, _ in verified if result is not None),
            sum(1 for _, failed in verified if failed),
        )

    async def _fetch_page(
        self,
        name: str,
        group: SourceGroup,
        query: str,
        quality: MatchQuality,
        parsed: ParsedQuery,
        refresh: bool,
        page: int,
        scope: SearchScope,
    ) -> tuple[tuple[SearchResult, ...], SourceState, bool, datetime | None, int | None]:
        now = self._clock()
        region_codes = _region_codes(parsed, name)
        cache_source = f"{name}_titles" if scope is SearchScope.TITLE else name
        key = make_cache_key(cache_source, query, region_codes, page)
        cached = self._cache.get(key, now)
        if cached is not None and cached.is_fresh and not refresh:
            normalized = normalize_results(
                cached.payload,
                group,
                quality,
                cached.fetched_at,
                scope=scope,
            )
            return (
                normalized,
                SourceState.FRESH_CACHE,
                False,
                cached.fetched_at,
                extract_total_count(cached.payload, group),
            )
        try:
            payload = await self._call_source(
                name, query, parsed, page, title_only=scope is SearchScope.TITLE
            )
            fetched_at = self._clock()
            normalized = normalize_results(
                payload, group, quality, fetched_at, scope=scope
            )
        except (ApiError, ResponseShapeError):
            if cached is None:
                return (), SourceState.ERROR, True, None, None
            normalized = normalize_results(
                cached.payload,
                group,
                quality,
                cached.fetched_at,
                scope=scope,
            )
            return (
                normalized,
                SourceState.STALE_FALLBACK,
                True,
                cached.fetched_at,
                extract_total_count(cached.payload, group),
            )
        self._cache.put(key, payload, fetched_at)
        return (
            normalized,
            SourceState.LIVE if normalized else SourceState.EMPTY,
            False,
            fetched_at,
            extract_total_count(payload, group),
        )

    async def _search_variant(
        self,
        name: str,
        group: SourceGroup,
        query: str,
        quality: MatchQuality,
        parsed: ParsedQuery,
        refresh: bool,
        page: int,
        scope: SearchScope,
    ) -> SourceOutcome:
        results, state, error, fetched_at, total = await self._fetch_page(
            name, group, query, quality, parsed, refresh, page, scope
        )
        accumulated = list(results)
        if not error:
            current_page = page
            while total is not None and len(accumulated) < total and results:
                current_page += 1
                results, page_state, page_error, page_fetched_at, page_total = (
                    await self._fetch_page(
                        name, group, query, quality, parsed, refresh, current_page, scope
                    )
                )
                if page_total is not None:
                    # Keep page 1's count whenever a later page reports none.
                    # Overwriting `total` unconditionally meant a single payload
                    # missing totalCnt set it to None, which made this loop's own
                    # `total is not None` guard false on the next iteration and
                    # silently stopped pagination while real pages remained.
                    total = page_total
                if page_error:
                    # A later page failed. Keep the pages already accumulated --
                    # partial candidates are still useful -- but report the
                    # failure through this source's existing error flag, the same
                    # path a page-1 failure uses. Without this the source would
                    # present a truncated candidate set as a complete, healthy
                    # LIVE result and silently drop every real match that lived
                    # on the pages after the one that failed.
                    error = True
                    break
                if not results:
                    break
                accumulated.extend(results)
                state = _result_state([state, page_state])
                if page_fetched_at is not None:
                    fetched_at = (
                        page_fetched_at
                        if fetched_at is None
                        else min(fetched_at, page_fetched_at)
                    )
        filtered = _filter_provincial_results(name, parsed, tuple(accumulated))
        if not filtered and state is SourceState.LIVE:
            # The raw payload had records, so _fetch_page reported LIVE, but the
            # province-name filter stripped every one of them. Only LIVE is
            # downgraded: STALE_FALLBACK/ERROR/FRESH_CACHE/EMPTY each carry
            # information this outcome must keep reporting. Leaving LIVE here
            # would make _combine_state resolve to EMPTY for a source whose
            # outcomes hold no EMPTY state, so _outcome_fetched_at would find no
            # timestamp and SearchResponse would reject the whole response.
            state = SourceState.EMPTY
        return (
            filtered,
            state,
            error,
            fetched_at,
        )

    async def _call_source(
        self,
        name: str,
        query: str,
        parsed: ParsedQuery,
        page: int,
        *,
        title_only: bool,
    ) -> dict[str, Any]:
        if name == "laws":
            return await self._api.search_laws(query, page, title_only=title_only)
        if name == "admin_rules":
            return await self._api.search_admin_rules(
                query, page, title_only=title_only
            )
        if parsed.region is None:
            raise SearchValidationError("지역 없는 자치법규 검색은 허용되지 않습니다.")
        return await self._api.search_ordinances(
            query,
            parsed.region,
            province_only=name == "provincial",
            page=page,
            title_only=title_only,
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


def _filter_provincial_results(
    name: str,
    parsed: ParsedQuery,
    results: tuple[SearchResult, ...],
) -> tuple[SearchResult, ...]:
    if name != "provincial" or parsed.region is None:
        return results
    expected = " ".join(parsed.region.province_name.split()).casefold()
    return tuple(
        item
        for item in results
        if item.authority is not None
        and " ".join(item.authority.split()).casefold() == expected
    )


def _deduplicate(results: list[SearchResult]) -> tuple[SearchResult, ...]:
    best: dict[tuple[SourceGroup, str], SearchResult] = {}
    for result in results:
        key = (result.source, result.uid)
        current = best.get(key)
        if current is None or _result_preference(result) < _result_preference(current):
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
            if retained is None or _result_preference(result) < _result_preference(
                retained[0]
            ):
                best[key] = (result, state)
    return tuple(best.values())


def _result_preference(result: SearchResult) -> tuple[int, MatchQuality]:
    return (
        0 if result.scope is SearchScope.TITLE else 1,
        result.quality,
    )


def _title_matches_query(title: str, keyword: str) -> bool:
    compact_title = re.sub(r"[^\w]", "", title.casefold())
    compact_keyword = re.sub(r"[^\w]", "", keyword.casefold())
    if compact_keyword and compact_keyword in compact_title:
        return True
    tokens = tuple(
        re.sub(r"[^\w]", "", token.casefold())
        for token in keyword.split()
    )
    return len(tokens) >= 2 and all(token and token in compact_title for token in tokens)


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
    matching = [
        fetched_at
        for _, outcome_state, _, fetched_at in outcomes
        if outcome_state is state and fetched_at is not None
    ]
    if matching:
        return min(matching)
    if state is SourceState.ERROR:
        return None
    # No outcome's own state matches the resolved state -- this happens
    # whenever something downstream of the raw fetch (the exact-match body
    # verification, a post-fetch content filter, ...) discards every
    # candidate an outcome reported as LIVE, so _combine_state falls back to
    # EMPTY without any outcome literally carrying EMPTY. The fetch still
    # happened and produced a real timestamp, so a resolved non-error state
    # must not be reported without one -- fall back to any outcome's
    # timestamp instead of leaving it unresolved.
    any_timestamps = [
        fetched_at for _, _, _, fetched_at in outcomes if fetched_at is not None
    ]
    return min(any_timestamps) if any_timestamps else None


def _result_state(states: list[SourceState]) -> SourceState:
    if SourceState.STALE_FALLBACK in states:
        return SourceState.STALE_FALLBACK
    if SourceState.LIVE in states:
        return SourceState.LIVE
    return SourceState.FRESH_CACHE
