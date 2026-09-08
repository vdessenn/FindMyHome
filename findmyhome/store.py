# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Victor DESSENNE
"""SQLite: upserts, price history, removals — and the principle 6 guard rail.

The database is the backbone of the system, not a cache: "new" means "absent from here"
(principle 5). Everything a run does to one site happens in a single transaction, so a failure
half-way writes nothing rather than leaving a state that reports phantom removals next time.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import cast

from findmyhome.listing import Listing, Transaction

# "transaction" is a SQL keyword, hence quoted everywhere it appears.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS listing (
    id          TEXT PRIMARY KEY,
    site        TEXT NOT NULL,
    url         TEXT NOT NULL,
    ref         TEXT,
    title       TEXT,
    price       INTEGER,
    surface     REAL,
    rooms       INTEGER,
    city        TEXT,
    postcode    TEXT,
    agency      TEXT,
    photo_url   TEXT,
    "transaction" TEXT,
    kind        TEXT,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    active      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS listing_by_site ON listing(site, active);

CREATE TABLE IF NOT EXISTS price_change (
    listing_id TEXT NOT NULL REFERENCES listing(id),
    seen_at    TEXT NOT NULL,
    old_price  INTEGER NOT NULL,
    new_price  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS site_run (
    site        TEXT NOT NULL,
    ran_at      TEXT NOT NULL,
    found_count INTEGER NOT NULL,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS site_run_by_site ON site_run(site, ran_at);
"""

_INSERT = """
INSERT INTO listing (id, site, url, ref, title, price, surface, rooms, city, postcode, agency,
                     photo_url, "transaction", kind, first_seen, last_seen, active)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
"""

_UPDATE = """
UPDATE listing SET url = ?, ref = ?, title = ?, price = ?, surface = ?, rooms = ?, city = ?,
                   postcode = ?, agency = ?, photo_url = ?, "transaction" = ?, kind = ?,
                   last_seen = ?, active = 1
WHERE id = ?
"""


@dataclass(frozen=True, slots=True)
class PriceChange:
    listing: Listing
    old_price: int
    new_price: int

    @property
    def is_drop(self) -> bool:
        return self.new_price < self.old_price


@dataclass(frozen=True, slots=True)
class Changes:
    """What one site's run changed. `anomaly` set means the removals were deliberately skipped."""

    site: str
    new: list[Listing]
    price_changes: list[PriceChange]
    removed: list[Listing]
    anomaly: str | None = None


def _fields(listing: Listing) -> tuple[object, ...]:
    """The mutable columns, in the order both statements above expect."""
    return (
        listing.url,
        listing.ref,
        listing.title,
        listing.price,
        listing.surface,
        listing.rooms,
        listing.city,
        listing.postcode,
        listing.agency,
        listing.photo_url,
        listing.transaction,
        listing.kind,
    )


def _to_listing(row: sqlite3.Row) -> Listing:
    """Rebuild a listing from its row: a removed listing still has to be displayable."""
    return Listing(
        site=row["site"],
        url=row["url"],
        ref=row["ref"],
        title=row["title"],
        price=row["price"],
        surface=row["surface"],
        rooms=row["rooms"],
        city=row["city"],
        postcode=row["postcode"],
        agency=row["agency"],
        photo_url=row["photo_url"],
        transaction=cast("Transaction | None", row["transaction"]),
        kind=row["kind"],
    )


class Store:
    """The listing database. Open it, diff a site's run against it, close it."""

    SCHEMA_VERSION = 1

    def __init__(self, path: Path | str) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    # -- API ---------------------------------------------------------------

    def known_ids(self, site: str) -> set[str]:
        """The identities this site currently has on the market.

        The pipeline uses it to keep tracking a listing it already knows even when the listing no
        longer satisfies the criteria: that is what turns a rise above `price_max` into a price
        rise rather than a removal.
        """
        cursor = self._conn.execute("SELECT id FROM listing WHERE site = ? AND active = 1", (site,))
        return {row["id"] for row in cursor}

    def diff(
        self,
        site: str,
        listings: Sequence[Listing],
        *,
        error: str | None = None,
        now: datetime | None = None,
        commit: bool = True,
    ) -> Changes:
        """Record what this run saw and report what moved. Reads and writes, in one transaction.

        `error` is what the caller hit while collecting (a `FetchError`, a parser blowing up):
        pass it and no removal is computed — half a run is not evidence of absence.

        `commit=False` leaves the transaction open for the caller to `commit` or `rollback`. That
        is what lets the digest be *sent before* anything is recorded: a listing stored but never
        mailed is a listing that is new only once, and nobody ever saw it (principle 5).
        """
        stamp = (now or datetime.now(UTC)).isoformat()
        # A sitemap can list the same listing twice; two inserts of one identity would abort the
        # whole run. Last occurrence wins, and the run count is what we actually stored.
        seen = {listing.id: listing for listing in listings}

        try:
            before = {
                row["id"]: row
                for row in self._conn.execute("SELECT * FROM listing WHERE site = ?", (site,))
            }
            new, price_changes = self._upsert(seen, before, stamp)
            anomaly = self._anomaly(site, error, len(seen))
            removed = (
                []
                if anomaly is not None
                else self._deactivate(
                    [row for row in before.values() if row["active"] and row["id"] not in seen]
                )
            )
            self._conn.execute(
                "INSERT INTO site_run (site, ran_at, found_count, error) VALUES (?, ?, ?, ?)",
                (site, stamp, len(seen), error),
            )
        except Exception:
            self._conn.rollback()
            raise
        if commit:
            self._conn.commit()

        return Changes(
            site=site,
            new=new,
            price_changes=price_changes,
            removed=removed,
            anomaly=anomaly,
        )

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        """Give up everything since the last commit: the run leaves no trace and repeats itself."""
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # -- Internals ---------------------------------------------------------

    def _migrate(self) -> None:
        version = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
        if version > self.SCHEMA_VERSION:
            raise RuntimeError(
                f"database schema v{version} is newer than this version of findmyhome "
                f"(v{self.SCHEMA_VERSION}): upgrade findmyhome rather than downgrade the database"
            )
        with self._conn:
            self._conn.executescript(_SCHEMA)
            # ponytail: no migration machinery, just the hook one would need. A schema change
            # bumps SCHEMA_VERSION and adds an `if version < n` step here.
            self._conn.execute(f"PRAGMA user_version = {self.SCHEMA_VERSION}")

    def _upsert(
        self,
        seen: dict[str, Listing],
        before: dict[str, sqlite3.Row],
        stamp: str,
    ) -> tuple[list[Listing], list[PriceChange]]:
        new: list[Listing] = []
        price_changes: list[PriceChange] = []
        for identity, listing in seen.items():
            row = before.get(identity)
            if row is None:
                self._conn.execute(
                    _INSERT, (identity, listing.site, *_fields(listing), stamp, stamp)
                )
                new.append(listing)
                continue

            self._conn.execute(_UPDATE, (*_fields(listing), stamp, identity))
            if not row["active"]:
                # Back on the market: news for the reader, but it kept its history and its
                # first_seen. The guard rail below is what keeps this from flapping.
                new.append(listing)
            elif (
                listing.price is not None
                and row["price"] is not None
                and listing.price != row["price"]
            ):
                self._conn.execute(
                    "INSERT INTO price_change (listing_id, seen_at, old_price, new_price) "
                    "VALUES (?, ?, ?, ?)",
                    (identity, stamp, row["price"], listing.price),
                )
                price_changes.append(PriceChange(listing, row["price"], listing.price))
        return new, price_changes

    def _anomaly(self, site: str, error: str | None, found: int) -> str | None:
        """Principle 6: silence is a bug, not information. Returning non-None cancels removals."""
        if error is not None:
            return f"{site}: run failed - {error}"
        if found:
            return None
        previous = self._last_successful_count(site)
        if previous == 0:
            return None
        # ponytail: only N > 0 -> 0 trips this, not 40 -> 3. A ratio threshold needs real data to
        # be calibrated on; guessing one now would either cry wolf or miss the real breakage.
        return (
            f"{site}: 0 listings found, {previous} on the previous successful run "
            f"- nothing marked as removed"
        )

    def _last_successful_count(self, site: str) -> int:
        """`error IS NULL` on purpose: a run that failed at 0 must not become the reference."""
        row = self._conn.execute(
            "SELECT found_count FROM site_run WHERE site = ? AND error IS NULL "
            "ORDER BY ran_at DESC, rowid DESC LIMIT 1",
            (site,),
        ).fetchone()
        return 0 if row is None else int(row["found_count"])

    def _deactivate(self, rows: Iterable[sqlite3.Row]) -> list[Listing]:
        """`last_seen` deliberately stays put: it is when we last saw it, not when we noticed."""
        gone = list(rows)
        self._conn.executemany(
            "UPDATE listing SET active = 0 WHERE id = ?", [(row["id"],) for row in gone]
        )
        return [_to_listing(row) for row in gone]
