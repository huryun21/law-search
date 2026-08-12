import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from lawsearch.cache import CacheStore, make_cache_key


FETCHED = datetime(2026, 8, 11, tzinfo=UTC)


def test_entry_is_fresh_strictly_before_24_hours(tmp_path):
    store = CacheStore(tmp_path / "cache.db")
    store.put("k", {"value": 1}, FETCHED)

    hit = store.get("k", FETCHED + timedelta(hours=23, minutes=59, seconds=59))

    assert hit is not None
    assert hit.is_fresh
    assert hit.payload == {"value": 1}
    assert hit.fetched_at == FETCHED


def test_entry_is_stale_at_24_hour_boundary(tmp_path):
    store = CacheStore(tmp_path / "cache.db")
    store.put("k", {"value": 1}, FETCHED)

    hit = store.get("k", FETCHED + timedelta(hours=24))

    assert hit is not None
    assert not hit.is_fresh


def test_entry_remains_stale_after_24_hours(tmp_path):
    store = CacheStore(tmp_path / "cache.db")
    store.put("k", {"value": 1}, FETCHED)

    hit = store.get("k", FETCHED + timedelta(days=2))

    assert hit is not None
    assert not hit.is_fresh


def test_missing_key_returns_none(tmp_path):
    store = CacheStore(tmp_path / "cache.db")

    assert store.get("missing", FETCHED) is None


def test_put_overwrites_payload_and_timestamp(tmp_path):
    store = CacheStore(tmp_path / "cache.db")
    replacement_time = FETCHED + timedelta(hours=2)
    store.put("k", {"version": 1}, FETCHED)
    store.put("k", {"version": 2}, replacement_time)

    hit = store.get("k", replacement_time)

    assert hit is not None
    assert hit.payload == {"version": 2}
    assert hit.fetched_at == replacement_time


def test_cache_persists_across_store_restart(tmp_path):
    path = tmp_path / "nested" / "cache.db"
    CacheStore(path).put("k", {"nested": {"items": [1, 2]}}, FETCHED)

    hit = CacheStore(path).get("k", FETCHED + timedelta(hours=1))

    assert hit is not None
    assert hit.payload == {"nested": {"items": [1, 2]}}


def test_read_updates_access_time_so_recent_entry_is_not_purged(tmp_path):
    store = CacheStore(tmp_path / "cache.db")
    store.put("recently-read", {"value": 1}, FETCHED)
    store.put("unused", {"value": 2}, FETCHED)
    store.get("recently-read", FETCHED + timedelta(days=29))

    removed = store.purge_unused(FETCHED + timedelta(days=1))

    assert removed == 1
    assert store.get("recently-read", FETCHED + timedelta(days=31)) is not None
    assert store.get("unused", FETCHED + timedelta(days=31)) is None


def test_purge_keeps_entry_accessed_exactly_at_boundary(tmp_path):
    store = CacheStore(tmp_path / "cache.db")
    store.put("boundary", {"value": 1}, FETCHED)

    assert store.purge_unused(FETCHED) == 0
    assert store.get("boundary", FETCHED) is not None


def test_corrupt_json_row_is_a_recoverable_cache_miss(tmp_path):
    path = tmp_path / "cache.db"
    store = CacheStore(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO cache_entries (key, payload, fetched_at, accessed_at) VALUES (?, ?, ?, ?)",
            ("broken", "not-json", FETCHED.isoformat(), FETCHED.isoformat()),
        )

    assert store.get("broken", FETCHED) is None
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM cache_entries WHERE key = ?", ("broken",)
        ).fetchone()[0] == 0


def test_naive_datetimes_are_rejected(tmp_path):
    store = CacheStore(tmp_path / "cache.db")
    naive = datetime(2026, 8, 11)

    with pytest.raises(ValueError, match="timezone-aware"):
        store.put("k", {"value": 1}, naive)
    with pytest.raises(ValueError, match="timezone-aware"):
        store.get("k", naive)
    with pytest.raises(ValueError, match="timezone-aware"):
        store.purge_unused(naive)


def test_cache_key_is_stable_and_covers_semantic_dimensions():
    baseline = make_cache_key("law", "  주차   대수  ", ("6410000", "3910000"), 1)

    assert baseline == make_cache_key(" LAW ", "주차 대수", ("6410000", "3910000"), 1)
    assert len(baseline) == 64
    assert set(baseline) <= set("0123456789abcdef")
    assert baseline != make_cache_key("admrul", "주차 대수", ("6410000", "3910000"), 1)
    assert baseline != make_cache_key("law", "주차 대수", ("6410000",), 1)
    assert baseline != make_cache_key("law", "주차 대수", ("6410000", "3910000"), 2)
    assert baseline != make_cache_key(
        "law", "주차 대수", ("6410000", "3910000"), 1, detail_id="001498"
    )


def test_raw_keyword_and_credential_like_text_never_reach_key_or_database_bytes(tmp_path):
    path = tmp_path / "cache.db"
    raw_keyword = "주차 대수"
    secret = "top-secret"
    key = make_cache_key("law", f"{raw_keyword} OC={secret}", (), 1)
    CacheStore(path).put(key, {"marker": "safe-cache-payload"}, FETCHED)

    assert raw_keyword not in key
    assert "OC=" not in key
    assert secret not in key
    database_bytes = b"".join(
        candidate.read_bytes() for candidate in tmp_path.glob("cache.db*") if candidate.is_file()
    )
    assert b"safe-cache-payload" in database_bytes
    assert raw_keyword.encode() not in database_bytes
    assert b"OC=" not in database_bytes
    assert secret.encode() not in database_bytes


def test_non_json_payload_does_not_leave_partial_entry(tmp_path):
    path = tmp_path / "cache.db"
    store = CacheStore(path)

    with pytest.raises(TypeError):
        store.put("k", {"unsupported": object()}, FETCHED)

    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM cache_entries WHERE key = ?", ("k",)
        ).fetchone()[0] == 0
