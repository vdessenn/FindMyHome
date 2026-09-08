# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Victor DESSENNE
"""The registry and the adapter contract.

There is little to run here: the contract is a `Protocol`, so what actually proves an adapter
honours it is mypy `--strict`, not a test. These tests pin what mypy cannot see - that the
registry names what it claims to name, and that an unknown site is a `None`, not a crash.
"""

from __future__ import annotations

import importlib
import sys
import types
from collections.abc import Iterable, Iterator
from pathlib import Path

import pytest

from findmyhome.config import Search
from findmyhome.fetch import Fetcher
from findmyhome.listing import Listing
from findmyhome.sites import base
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


def test_a_private_overlay_joins_the_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """The mechanism the public/private split rests on: `findmyhome_local` adds adapters without
    this repository knowing they exist."""
    overlay = types.ModuleType("findmyhome_local")
    overlay.SITES = {"private": Minimal}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "findmyhome_local", overlay)
    try:
        reloaded = importlib.reload(base)
        assert reloaded.SITES["private"] is Minimal
        assert "orpi" in reloaded.SITES, "the overlay adds, it does not replace"
    finally:
        monkeypatch.undo()
        importlib.reload(base)


def test_a_broken_overlay_is_raised_not_swallowed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Principle 6 turned on ourselves: a private adapter that fails to import must be loud.
    A bare `except ImportError` here would make it vanish instead of reporting it."""
    package = tmp_path / "findmyhome_local"
    package.mkdir()
    (package / "__init__.py").write_text("import httpx_typo\n")
    monkeypatch.syspath_prepend(tmp_path)
    sys.modules.pop("findmyhome_local", None)
    try:
        with pytest.raises(ModuleNotFoundError, match="httpx_typo"):
            importlib.reload(base)
    finally:
        monkeypatch.undo()
        sys.modules.pop("findmyhome_local", None)
        importlib.reload(base)
