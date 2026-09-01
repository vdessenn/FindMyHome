"""TOML configuration: loading, strict validation, and the search criteria themselves.

A config file is edited by hand, so validation reports *every* problem at once rather than
stopping on the first: one run, one round of fixes. An unknown key is an error too — `price_maxx`
silently ignored is a search that runs, on the wrong criteria.

`Search.matches` lives here, not on `Listing`: filtering is what the criteria do to a listing,
so `config` imports `listing` and never the other way round.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar, cast

from findmyhome.listing import Listing, Transaction

PASSWORD_ENV = "FINDMYHOME_SMTP_PASSWORD"
TRANSACTIONS: tuple[str, ...] = ("sale", "rent")

# Relative on purpose: the Docker image runs in /data, so this default lands on the mounted
# volume without a single absolute path anywhere in the code (principle 7).
DEFAULT_DATABASE = Path("findmyhome.db")

_TABLES = ("search", "sites", "storage", "digest", "smtp")

_T = TypeVar("_T")


class ConfigError(ValueError):
    """The configuration file is unusable. The message lists everything that is wrong with it."""


def _over(value: float | None, ceiling: int | None) -> bool:
    """True only when both are known and the bound is broken: an unknown field never rejects."""
    return value is not None and ceiling is not None and value > ceiling


def _under(value: float | None, floor: int | None) -> bool:
    return value is not None and floor is not None and value < floor


def _fold(text: str) -> str:
    # ponytail: case and spacing only. Strip accents (unicodedata NFD) the day a site writes
    # "REZE" for "Rezé" - not before, since it would also merge names that differ by an accent.
    return text.strip().casefold()


@dataclass(frozen=True, slots=True)
class Search:
    """The hard criteria, applied to the real fields (pipeline stage 5).

    Every bound is optional: a search with no ceiling is legitimate, and so is one that names no
    city.
    """

    transaction: Transaction
    kinds: tuple[str, ...] = ()
    cities: tuple[str, ...] = ()
    postcodes: tuple[str, ...] = ()
    price_max: int | None = None
    surface_min: int | None = None
    rooms_min: int | None = None

    def matches(self, listing: Listing) -> bool:
        """True if the listing satisfies every criterion it carries a value for.

        An unknown field (`None`) never rejects: an adapter that fails to extract the surface is
        incomplete, and dropping its listings in silence would be a bug, not a filter.
        """
        if listing.transaction is not None and listing.transaction != self.transaction:
            return False
        if self.kinds and listing.kind is not None and listing.kind not in self.kinds:
            return False
        if _over(listing.price, self.price_max):
            return False
        if _under(listing.surface, self.surface_min):
            return False
        if _under(listing.rooms, self.rooms_min):
            return False
        return self._is_located(listing)

    def _is_located(self, listing: Listing) -> bool:
        """Postcode *or* city: a listing rarely carries both reliably."""
        if not self.cities and not self.postcodes:
            return True
        if listing.postcode is not None and listing.postcode in self.postcodes:
            return True
        if listing.city is not None and _fold(listing.city) in {_fold(c) for c in self.cities}:
            return True
        return listing.city is None and listing.postcode is None


@dataclass(frozen=True, slots=True)
class Storage:
    database: Path = DEFAULT_DATABASE


@dataclass(frozen=True, slots=True)
class Digest:
    send_when_empty: bool = False


@dataclass(frozen=True, slots=True)
class Smtp:
    host: str
    port: int
    sender: str
    recipients: tuple[str, ...]
    # Never in the file, never in a log: the repository is public and a config gets printed by
    # accident. Absent is `None`, not an error - only sending actually needs it.
    password: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class Config:
    search: Search
    sites: tuple[str, ...]
    storage: Storage
    digest: Digest
    smtp: Smtp


class _Table:
    """One TOML table, read with type checks that accumulate errors instead of raising."""

    def __init__(self, name: str, raw: object, errors: list[str], *, required: bool) -> None:
        self.name = name
        self._errors = errors
        self._read: set[str] = set()
        if isinstance(raw, dict):
            self._data = cast(dict[str, object], raw)
            return
        self._data = {}
        if raw is not None:
            errors.append(f"[{name}]: expected a table")
        elif required:
            errors.append(f"[{name}]: required table is missing")

    def _typed(self, key: str, kind: type[_T]) -> _T | None:
        self._read.add(key)
        raw = self._data.get(key)
        if raw is None:
            return None
        # `bool` is a subclass of `int`: without this, `price_max = true` would be accepted.
        if not isinstance(raw, kind) or (kind is int and isinstance(raw, bool)):
            self._errors.append(
                f"[{self.name}] {key}: expected {kind.__name__}, got {type(raw).__name__}"
            )
            return None
        return raw

    def optional(self, key: str, kind: type[_T]) -> _T | None:
        return self._typed(key, kind)

    def required(self, key: str, kind: type[_T]) -> _T:
        value = self._typed(key, kind)
        if value is not None:
            return value
        if key not in self._data:
            self._errors.append(f"[{self.name}] {key}: required key is missing")
        return kind()

    def strings(self, key: str) -> tuple[str, ...]:
        self._read.add(key)
        raw = self._data.get(key)
        if raw is None:
            return ()
        if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
            self._errors.append(f"[{self.name}] {key}: expected a list of strings")
            return ()
        return tuple(cast(list[str], raw))

    def choice(self, key: str, allowed: tuple[str, ...]) -> str:
        value = self.required(key, str)
        if value and value not in allowed:
            self._errors.append(f"[{self.name}] {key}: {value!r} is not one of {allowed}")
        return value

    def done(self) -> None:
        """Report the keys nobody read: that is how a typo stops being silent."""
        for key in sorted(set(self._data) - self._read):
            self._errors.append(f"[{self.name}] {key}: unknown key")


def load(path: Path | str) -> Config:
    """Read and validate the configuration file. Raises `ConfigError` listing every problem."""
    path = Path(path)
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"{path}: {exc.strerror or exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML - {exc}") from exc

    errors: list[str] = []

    search_table = _Table("search", raw.get("search"), errors, required=True)
    search = Search(
        transaction=cast(Transaction, search_table.choice("transaction", TRANSACTIONS)),
        kinds=search_table.strings("kinds"),
        cities=search_table.strings("cities"),
        postcodes=search_table.strings("postcodes"),
        price_max=search_table.optional("price_max", int),
        surface_min=search_table.optional("surface_min", int),
        rooms_min=search_table.optional("rooms_min", int),
    )
    search_table.done()

    sites_table = _Table("sites", raw.get("sites"), errors, required=True)
    sites = sites_table.strings("enabled")
    sites_table.done()

    storage_table = _Table("storage", raw.get("storage"), errors, required=False)
    database = storage_table.optional("database", str)
    storage = Storage(database=Path(database) if database else DEFAULT_DATABASE)
    storage_table.done()

    digest_table = _Table("digest", raw.get("digest"), errors, required=False)
    send_when_empty = digest_table.optional("send_when_empty", bool)
    digest = Digest(send_when_empty=bool(send_when_empty))
    digest_table.done()

    smtp_table = _Table("smtp", raw.get("smtp"), errors, required=True)
    smtp = Smtp(
        host=smtp_table.required("host", str),
        port=smtp_table.required("port", int),
        sender=smtp_table.required("from", str),
        recipients=smtp_table.strings("to"),
        password=os.environ.get(PASSWORD_ENV),
    )
    smtp_table.done()

    errors.extend(f"[{name}]: unknown table" for name in sorted(set(raw) - set(_TABLES)))

    if errors:
        raise ConfigError(f"{path}:\n  - " + "\n  - ".join(errors))
    return Config(search=search, sites=sites, storage=storage, digest=digest, smtp=smtp)
