"""The `Listing` dataclass and its identity — principle 5 of ARCHITECTURE.md.

Sitemaps expose no per-listing `lastmod` and agency references are unstable, so "new" means
"absent from our database". Everything therefore hangs on an identity that does not move between
two runs: a change here does not migrate the database, it resets it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

Transaction = Literal["sale", "rent"]


def canonical_url(url: str) -> str:
    """The URL stripped of everything that varies without designating another page.

    Query string and fragment go (tracking parameters, photo anchors), the host is lowercased and
    a trailing slash is dropped. The path stays untouched: it is what identifies the page.
    """
    parts = urlsplit(url)
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme, parts.netloc.lower(), path, "", ""))


@dataclass(frozen=True, slots=True)
class Listing:
    """One listing as an adapter extracted it.

    Every field but `site` and `url` is optional: an adapter that fails to find the agency or the
    photo is incomplete, not useless. Filtering handles the missing values (see `Search.matches`).
    """

    site: str
    url: str
    ref: str | None = None
    title: str | None = None
    price: int | None = None
    surface: float | None = None
    rooms: int | None = None
    city: str | None = None
    postcode: str | None = None
    agency: str | None = None
    photo_url: str | None = None
    transaction: Transaction | None = None
    kind: str | None = None

    @property
    def id(self) -> str:
        """The deduplication key: the site's reference when it has one, its URL otherwise.

        The site prefixes both variants: two agencies numbering their listings from 1 must not
        collide, and an identity reads at a glance in the database.
        """
        return f"{self.site}:{self.ref or canonical_url(self.url)}"
