from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any


@dataclass(frozen=True)
class CacheEntry:
    payload: dict[str, Any]
    fetched_at: datetime
    is_fresh: bool


class CacheStore:
    def __init__(
        self,
        path: Path,
        ttl: timedelta = timedelta(hours=24),
    ) -> None:
        self._path = path
        self._ttl = ttl
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cache_entries (
                    key TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    accessed_at TEXT NOT NULL
                )
                """
            )
            connection.commit()

    def get(self, key: str, now: datetime | None = None) -> CacheEntry | None:
        accessed_at = _as_utc(now or datetime.now(UTC))
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT payload, fetched_at FROM cache_entries WHERE key = ?",
                (key,),
            ).fetchone()
            if row is None:
                return None
            try:
                payload = json.loads(row[0])
                fetched_at = _as_utc(datetime.fromisoformat(row[1]))
                if not isinstance(payload, dict):
                    raise TypeError("cache payload is not a JSON object")
            except (json.JSONDecodeError, TypeError, ValueError):
                connection.execute("DELETE FROM cache_entries WHERE key = ?", (key,))
                return None
            connection.execute(
                "UPDATE cache_entries SET accessed_at = ? WHERE key = ?",
                (accessed_at.isoformat(), key),
            )
        return CacheEntry(
            payload=payload,
            fetched_at=fetched_at,
            is_fresh=accessed_at - fetched_at < self._ttl,
        )

    def put(
        self,
        key: str,
        payload: Mapping[str, Any],
        fetched_at: datetime | None = None,
    ) -> None:
        if not isinstance(payload, Mapping):
            raise TypeError("cache payload must be a mapping")
        timestamp = _as_utc(fetched_at or datetime.now(UTC)).isoformat()
        serialized = json.dumps(
            dict(payload),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO cache_entries (key, payload, fetched_at, accessed_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    payload = excluded.payload,
                    fetched_at = excluded.fetched_at,
                    accessed_at = excluded.accessed_at
                """,
                (key, serialized, timestamp, timestamp),
            )

    def purge_unused(self, before: datetime) -> int:
        cutoff = _as_utc(before).isoformat()
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "DELETE FROM cache_entries WHERE accessed_at < ?",
                (cutoff,),
            )
            return cursor.rowcount

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, timeout=5.0)


def make_cache_key(
    source: str,
    keyword: str,
    region_codes: tuple[str, ...],
    page: int,
    detail_id: str | None = None,
) -> str:
    semantic_input = {
        "source": source.strip().casefold(),
        "keyword": " ".join(keyword.split()).casefold(),
        "region_codes": tuple(code.strip() for code in region_codes),
        "page": page,
        "detail_id": detail_id,
    }
    encoded = json.dumps(
        semantic_input,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("cache timestamps must be timezone-aware")
    return value.astimezone(UTC)
