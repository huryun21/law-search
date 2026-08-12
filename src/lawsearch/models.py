from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum, IntEnum
from typing import Mapping


class SourceGroup(str, Enum):
    MUNICIPAL = "municipal"
    PROVINCIAL = "provincial"
    LAW = "law"
    DECREE = "decree"
    MINISTERIAL_RULE = "ministerial_rule"
    ADMIN_RULE = "admin_rule"
    OTHER = "other"


class MatchQuality(IntEnum):
    EXACT = 0
    COMPACT = 1
    ALL_TERMS = 2


@dataclass(frozen=True)
class Region:
    province_name: str
    municipality_name: str | None
    org: str
    sborg: str | None = None
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedQuery:
    keyword: str
    region: Region | None = None
    candidates: tuple[Region, ...] = ()


@dataclass(frozen=True)
class RegionResolution:
    region: Region | None
    candidates: tuple[Region, ...] = ()

    @property
    def is_unique(self) -> bool:
        return self.region is not None


@dataclass(frozen=True)
class QueryVariant:
    query: str
    quality: MatchQuality


@dataclass(frozen=True)
class SearchResult:
    uid: str
    source: SourceGroup
    quality: MatchQuality
    title: str
    category: str
    authority: str | None
    region_name: str | None
    promulgation_date: date | None
    effective_date: date | None
    is_current: bool
    official_url: str
    fetched_at: datetime


class SourceState(str, Enum):
    LIVE = "live"
    FRESH_CACHE = "fresh_cache"
    STALE_FALLBACK = "stale_fallback"
    EMPTY = "empty"
    ERROR = "error"


@dataclass(frozen=True)
class SourceError:
    source: str
    message: str


@dataclass(frozen=True)
class SearchResponse:
    results: tuple[SearchResult, ...]
    suggestions: tuple[str, ...]
    errors: tuple[SourceError, ...]
    source_states: Mapping[str, SourceState]
    source_fetched_at: Mapping[str, datetime]

    def __post_init__(self) -> None:
        if any(
            value.tzinfo is None or value.utcoffset() is None
            for value in self.source_fetched_at.values()
        ):
            raise ValueError("source retrieval timestamps must be timezone-aware")


@dataclass(frozen=True)
class DetailResponse:
    contexts: tuple[str, ...]
    state: SourceState
    fetched_at: datetime
