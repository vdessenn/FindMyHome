# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Victor DESSENNE
"""The adapter contract and the registry.

The contract is a `Protocol`, so an adapter inherits nothing: it just has the right shape, and
mypy `--strict` checks that shape against `SITES` below - before runtime rather than during it.
That is principle 1 with tooling behind it.

The registry is a plain dict, written by hand. Auto-discovery through `pkgutil` would save the one
line an adapter costs here, at the price of an import PyInstaller cannot see: the standalone binary
is a distribution channel, not a nice-to-have.

`findmyhome_local` is the optional private overlay: a package that is absent from this repository
and, when present, contributes further adapters under the same contract. It stays a literal
`import` for the reason above - PyInstaller resolves those, it does not resolve `pkgutil`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Protocol

from findmyhome.config import Search
from findmyhome.fetch import Fetcher
from findmyhome.listing import Listing
from findmyhome.sites.orpi import Orpi


class Site(Protocol):
    """What the core needs from a site, and all it is allowed to ask of it.

    The criteria and the HTTP client are handed over at construction, which is why `discover` and
    `prefilter` take nothing else.
    """

    name: str
    base_url: str

    def discover(self) -> Iterable[str]:
        """Candidate listing URLs, from the site's sitemap(s)."""
        ...

    def prefilter(self, url: str) -> bool:
        """True if the URL slug is compatible with the search criteria.

        A heuristic on the slug, not a filter on the fields: it exists to avoid downloading pages
        that cannot match. Anything it cannot read from the URL, it accepts.
        """
        ...

    def parse(self, url: str, html: str) -> Listing | None:
        """Extract the fields. None if the page is not (or no longer) a valid listing."""
        ...


SITES: dict[str, Callable[[Fetcher, Search], Site]] = {"orpi": Orpi}

try:
    from findmyhome_local import SITES as _private
except ModuleNotFoundError as missing:
    # No overlay is the normal case. An overlay that is *present but broken* is not: catching
    # plain ImportError here would delete a private adapter silently, which is principle 6
    # applied to our own code.
    if missing.name != "findmyhome_local":
        raise
else:
    SITES.update(_private)


def build(name: str, fetcher: Fetcher, search: Search) -> Site | None:
    """The adapter for this site, or None when none exists yet.

    None rather than an exception: a configuration may legitimately name a site whose adapter has
    not been written, and that is a line on stderr, not a failed run.
    """
    factory = SITES.get(name)
    return None if factory is None else factory(fetcher, search)
