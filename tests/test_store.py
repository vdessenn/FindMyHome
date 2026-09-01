"""The core: identity, price history, removals, and the principle 6 guard rail.

Two properties matter more than the rest. A second identical run must report nothing — a moving
identity would announce the whole market as new. And a scraper that returns nothing must never be
able to look like a market that emptied.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from findmyhome.listing import Listing
from findmyhome.store import Store


@pytest.fixture
def database(tmp_path: Path) -> Path:
    return tmp_path / "findmyhome.db"


@pytest.fixture
def store(database: Path) -> Store:
    return Store(database)


def at(day: int) -> datetime:
    return datetime(2026, 9, day, 8, 0, tzinfo=UTC)


def make(ref: str, price: int | None = 300000, *, site: str = "orpi") -> Listing:
    return Listing(
        site=site,
        url=f"https://{site}.test/listing/{ref}",
        ref=ref,
        title=f"House {ref}",
        price=price,
        surface=95.0,
        rooms=5,
        city="Springfield",
        postcode="12345",
        agency="Springfield Estates",
        photo_url=f"https://{site}.test/photo/{ref}.jpg",
        transaction="sale",
        kind="house",
    )


def rows(database: Path, sql: str, *args: object) -> list[sqlite3.Row]:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        return list(connection.execute(sql, args))
    finally:
        connection.close()


def test_a_first_run_reports_everything_as_new(store: Store) -> None:
    changes = store.diff("orpi", [make("a"), make("b")], now=at(1))
    assert [listing.ref for listing in changes.new] == ["a", "b"]
    assert changes.removed == []
    assert changes.price_changes == []
    assert changes.anomaly is None


def test_an_identical_second_run_reports_nothing(store: Store) -> None:
    """The classic trap of this kind of system: an identity that moves between two runs."""
    store.diff("orpi", [make("a"), make("b")], now=at(1))
    changes = store.diff("orpi", [make("a"), make("b")], now=at(2))
    assert changes.new == []
    assert changes.removed == []
    assert changes.price_changes == []


def test_a_price_drop_is_reported_and_recorded(store: Store, database: Path) -> None:
    store.diff("orpi", [make("a", 300000)], now=at(1))
    changes = store.diff("orpi", [make("a", 280000)], now=at(2))

    assert len(changes.price_changes) == 1
    change = changes.price_changes[0]
    assert (change.old_price, change.new_price) == (300000, 280000)
    assert change.is_drop
    assert change.listing.ref == "a"

    history = rows(database, "SELECT * FROM price_change")
    assert [(row["old_price"], row["new_price"]) for row in history] == [(300000, 280000)]
    assert rows(database, "SELECT price FROM listing")[0]["price"] == 280000


def test_a_price_rise_is_reported_as_a_rise(store: Store) -> None:
    store.diff("orpi", [make("a", 300000)], now=at(1))
    changes = store.diff("orpi", [make("a", 320000)], now=at(2))
    assert not changes.price_changes[0].is_drop
    assert changes.new == []
    assert changes.removed == [], "a price rise is not a removal"


def test_price_history_accumulates(store: Store, database: Path) -> None:
    store.diff("orpi", [make("a", 300000)], now=at(1))
    store.diff("orpi", [make("a", 280000)], now=at(2))
    store.diff("orpi", [make("a", 260000)], now=at(3))
    assert len(rows(database, "SELECT * FROM price_change")) == 2


def test_a_price_that_becomes_unknown_is_not_a_change(store: Store) -> None:
    """A parser that stops finding the price must not invent a drop to zero."""
    store.diff("orpi", [make("a", 300000)], now=at(1))
    changes = store.diff("orpi", [make("a", None)], now=at(2))
    assert changes.price_changes == []


def test_a_listing_that_disappears_is_removed_and_deactivated(store: Store, database: Path) -> None:
    store.diff("orpi", [make("a"), make("b")], now=at(1))
    changes = store.diff("orpi", [make("a")], now=at(2))

    assert [listing.ref for listing in changes.removed] == ["b"]
    assert changes.removed[0].title == "House b", "a removed listing is still displayable"
    assert changes.removed[0].id == make("b").id
    assert rows(database, "SELECT active FROM listing WHERE id = ?", make("b").id)[0]["active"] == 0


def test_zero_listings_after_a_non_empty_run_is_an_anomaly_not_a_wipe(
    store: Store, database: Path
) -> None:
    """Principle 6: a broken scraper must never look like an empty market."""
    store.diff("orpi", [make("a"), make("b"), make("c")], now=at(1))
    changes = store.diff("orpi", [], now=at(2))

    assert changes.anomaly is not None
    assert changes.removed == []
    assert len(rows(database, "SELECT id FROM listing WHERE active = 1")) == 3


def test_a_failed_run_removes_nothing_but_keeps_what_it_saw(store: Store) -> None:
    """Half a run is not evidence of absence - but having seen a listing is never wrong."""
    store.diff("orpi", [make("a"), make("b")], now=at(1))
    changes = store.diff("orpi", [make("a")], error="HTTP 503 on the sitemap", now=at(2))

    assert changes.anomaly is not None
    assert "503" in changes.anomaly
    assert changes.removed == []


def test_a_failed_empty_run_does_not_disarm_the_guard_rail(store: Store) -> None:
    """A broken scraper stays broken: comparing against the last *successful* run is the point."""
    store.diff("orpi", [make("a"), make("b")], now=at(1))
    store.diff("orpi", [], error="network down", now=at(2))
    changes = store.diff("orpi", [], now=at(3))

    assert changes.anomaly is not None, "the failed run at 0 must not become the reference"
    assert changes.removed == []


def test_an_empty_first_run_is_not_an_anomaly(store: Store) -> None:
    """Nothing to compare against yet: a fresh database is not a broken scraper."""
    changes = store.diff("orpi", [], now=at(1))
    assert changes.anomaly is None


def test_a_listing_that_comes_back_is_new_again_and_keeps_its_first_seen(
    store: Store, database: Path
) -> None:
    store.diff("orpi", [make("a"), make("b")], now=at(1))
    store.diff("orpi", [make("a")], now=at(2))
    changes = store.diff("orpi", [make("a"), make("b")], now=at(3))

    assert [listing.ref for listing in changes.new] == ["b"]
    row = rows(database, "SELECT * FROM listing WHERE id = ?", make("b").id)[0]
    assert row["active"] == 1
    assert row["first_seen"] == at(1).isoformat(), "first_seen is when we first saw it, ever"
    assert row["last_seen"] == at(3).isoformat()


def test_removals_are_scoped_to_one_site(store: Store) -> None:
    """Orpi running does not mean La Forêt's listings vanished."""
    store.diff("orpi", [make("a")], now=at(1))
    store.diff("laforet", [make("z", site="laforet")], now=at(1))
    changes = store.diff("orpi", [make("a")], now=at(2))
    assert changes.removed == []


def test_an_anomaly_on_one_site_leaves_the_others_alone(store: Store) -> None:
    store.diff("orpi", [make("a")], now=at(1))
    store.diff("laforet", [make("z", site="laforet")], now=at(1))
    changes = store.diff("laforet", [], now=at(2))
    assert changes.anomaly is not None
    assert store.known_ids("orpi") == {make("a").id}


def test_known_ids_lists_the_active_listings_of_one_site(store: Store) -> None:
    """What arms decision A: a listing already known is tracked whatever the criteria say."""
    store.diff("orpi", [make("a"), make("b")], now=at(1))
    store.diff("orpi", [make("a")], now=at(2))
    assert store.known_ids("orpi") == {make("a").id}
    assert store.known_ids("laforet") == set()


def test_every_run_is_recorded(store: Store, database: Path) -> None:
    """site_run is what arms principle 6: without it there is nothing to compare against."""
    store.diff("orpi", [make("a")], now=at(1))
    store.diff("orpi", [], error="boom", now=at(2))
    recorded = rows(database, "SELECT * FROM site_run ORDER BY ran_at")
    assert [(row["found_count"], row["error"]) for row in recorded] == [(1, None), (0, "boom")]


def test_the_schema_is_created_and_versioned(store: Store, database: Path) -> None:
    tables = {row["name"] for row in rows(database, "SELECT name FROM sqlite_master")}
    assert {"listing", "price_change", "site_run"} <= tables
    assert rows(database, "PRAGMA user_version")[0][0] == Store.SCHEMA_VERSION


def test_a_database_from_a_newer_version_is_refused(database: Path) -> None:
    """Opening it read-write would silently write a shape the newer code does not expect."""
    Store(database).close()
    connection = sqlite3.connect(database)
    connection.execute(f"PRAGMA user_version = {Store.SCHEMA_VERSION + 1}")
    connection.close()
    with pytest.raises(RuntimeError, match="newer"):
        Store(database)


def test_reopening_the_store_keeps_the_state(database: Path) -> None:
    """Principle 5: SQLite is the backbone, not a cache. Restarting must change nothing."""
    with Store(database) as first:
        first.diff("orpi", [make("a")], now=at(1))
    with Store(database) as second:
        assert second.diff("orpi", [make("a")], now=at(2)).new == []


def test_the_same_listing_twice_in_one_run_is_stored_once(store: Store) -> None:
    """A sitemap can list one listing under two URLs; a duplicate insert would abort the run."""
    changes = store.diff("orpi", [make("a"), make("a", 290000)], now=at(1))
    assert [listing.ref for listing in changes.new] == ["a"]
    assert store.known_ids("orpi") == {make("a").id}
