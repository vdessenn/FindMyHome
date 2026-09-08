"""The registry and the adapter contract.

There is little to run here: the contract is a `Protocol`, so what actually proves an adapter
honours it is mypy `--strict`, not a test. These tests pin what mypy cannot see - that the
registry names what it claims to name, and that an unknown site is a `None`, not a crash.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

import pytest

from findmyhome.config import Search
from findmyhome.fetch import Fetcher
from findmyhome.listing import Listing
from findmyhome.sites.base import SITES, Site, build


class Minimal:
    """The smallest thing that satisfies `Site`. It inherits nothing - the point of a Protocol."""

    name = "minimal"
    base_url = "https://agency.test"

    def __init__(self, fetcher: Fetcher, search: Search) -> None:
        self.fetcher = fetcher
        self.search = search

    def discover(self) -> Iterable[str]:
        return ()

    def prefilter(self, url: str) -> bool:
        return True

    def parse(self, url: str, html: str) -> Listing | None:
        return None


@pytest.fixture
def search() -> Search:
    return Search(transaction="sale")


@pytest.fixture
def fetcher() -> Iterator[Fetcher]:
    with Fetcher() as ready:
        yield ready


def test_an_adapter_needs_no_base_class(fetcher: Fetcher, search: Search) -> None:
    """mypy is what checks this; the assignment is here so the check is not silently dropped."""
    adapter: Site = Minimal(fetcher, search)
    assert adapter.name == "minimal"


def test_an_unknown_site_is_none_not_an_exception(fetcher: Fetcher, search: Search) -> None:
    assert build("nosuchsite", fetcher, search) is None


@pytest.mark.parametrize("name", sorted(SITES))
def test_every_registered_adapter_is_named_after_its_key(
    name: str, fetcher: Fetcher, search: Search
) -> None:
    """The config names sites by string: a key that disagrees with `name` would report a run
    against a site nobody enabled."""
    adapter = build(name, fetcher, search)
    assert adapter is not None
    assert adapter.name == name
