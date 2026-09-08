"""The pipeline: what gets downloaded, what gets kept, and what counts as a breakage.

Two properties carry this module. A listing we already know must survive the filter even once it
stopped matching the criteria - that is what turns a price rise into a price rise instead of a
removal (ARCHITECTURE.md, pipeline stage 5). And any failure met while collecting must reach the
store as an error, so that principle 6 cancels the removals rather than reporting a phantom
emptied market.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import httpx
import pytest

from findmyhome.__main__ import _run, collect
from findmyhome.config import Config, Digest, Search, Smtp, Storage
from findmyhome.fetch import Fetcher
from findmyhome.listing import Listing
from findmyhome.sites import base
from findmyhome.store import Store

HOST = "https://agency.test"
ROBOTS = f"{HOST}/robots.txt"

SEARCH = Search(transaction="sale", price_max=400000)


def url_of(ref: str) -> str:
    return f"{HOST}/listing/{ref}"


def make(ref: str, price: int) -> Listing:
    return Listing(
        site="fake",
        url=url_of(ref),
        ref=ref,
        title=f"House {ref}",
        price=price,
        surface=95.0,
        rooms=5,
        city="Springfield",
        postcode="12345",
        transaction="sale",
        kind="house",
    )


class FakeSite:
    """An adapter that answers from a table. It inherits nothing - `Site` is a Protocol.

    A value of `None` is a page that is not a listing; an exception is an adapter breaking on
    HTML it no longer understands.
    """

    name = "fake"
    base_url = HOST

    def __init__(
        self,
        pages: dict[str, Listing | Exception | None],
        *,
        refuse: Iterable[str] = (),
    ) -> None:
        self.pages = pages
        self.refuse = set(refuse)
        self.parsed: list[str] = []

    def discover(self) -> Iterable[str]:
        return list(self.pages)

    def prefilter(self, url: str) -> bool:
        return url not in self.refuse

    def parse(self, url: str, html: str) -> Listing | None:
        self.parsed.append(url)
        answer = self.pages[url]
        if isinstance(answer, Exception):
            raise answer
        return answer


def make_fetcher(
    *, missing: Iterable[str] = (), broken: Iterable[str] = ()
) -> tuple[Fetcher, list[str]]:
    """A fetcher over a fake network: every page answers 200 unless declared otherwise."""
    absent, failing = set(missing), set(broken)
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        requested.append(url)
        if url in failing:
            raise httpx.ConnectError("the site went away")
        if url == ROBOTS:
            return httpx.Response(200, text="User-agent: *\nDisallow: /search/")
        if url in absent:
            return httpx.Response(404)
        return httpx.Response(200, text=f"<html>{url}</html>")

    fetcher = Fetcher(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
        delay=0.0,
        retries=0,
        backoff=0.0,
    )
    return fetcher, requested


# -- collect: stages 1 to 5 -------------------------------------------------


def test_a_prefiltered_url_is_never_downloaded() -> None:
    """Stage 2 exists to save the downloads, so a failure here is invisible but expensive."""
    adapter = FakeSite(
        {url_of("1"): make("1", 300000), url_of("2"): make("2", 300000)},
        refuse=[url_of("2")],
    )
    fetcher, requested = make_fetcher()

    listings, error = collect(adapter, fetcher, SEARCH, set())

    assert error is None
    assert [listing.ref for listing in listings] == ["1"]
    assert url_of("2") not in requested


def test_a_known_listing_that_stopped_matching_is_still_collected() -> None:
    """The decision this whole stage hangs on: 'removed' must keep meaning 'gone from the site'."""
    adapter = FakeSite({url_of("1"): make("1", 500000)})
    fetcher, _ = make_fetcher()

    listings, error = collect(adapter, fetcher, SEARCH, {"fake:1"})

    assert error is None
    assert [listing.ref for listing in listings] == ["1"], "a price rise is not a removal"


def test_an_unknown_listing_that_does_not_match_is_dropped() -> None:
    adapter = FakeSite({url_of("1"): make("1", 500000)})
    fetcher, _ = make_fetcher()

    assert collect(adapter, fetcher, SEARCH, set()) == ([], None)


def test_a_missing_page_is_skipped_not_a_failure() -> None:
    """A 404 and a page that is no longer a listing are answers, not breakages."""
    adapter = FakeSite(
        {
            url_of("gone"): make("gone", 300000),
            url_of("notalisting"): None,
            url_of("kept"): make("kept", 300000),
        }
    )
    fetcher, _ = make_fetcher(missing=[url_of("gone")])

    listings, error = collect(adapter, fetcher, SEARCH, set())

    assert error is None
    assert [listing.ref for listing in listings] == ["kept"]
    assert url_of("gone") not in adapter.parsed, "a missing page is never handed to the parser"


def test_a_fetch_failure_stops_the_site_and_keeps_what_was_seen() -> None:
    adapter = FakeSite({url_of("1"): make("1", 300000), url_of("2"): make("2", 300000)})
    fetcher, _ = make_fetcher(broken=[url_of("2")])

    listings, error = collect(adapter, fetcher, SEARCH, set())

    assert error is not None
    assert [listing.ref for listing in listings] == ["1"], "having seen a listing is never wrong"


def test_a_parser_that_blows_up_is_a_failure_not_an_empty_market() -> None:
    """Principle 6 covers HTML structure changes, and this is what one looks like."""
    adapter = FakeSite({url_of("1"): AttributeError("'NoneType' object has no attribute 'text'")})
    fetcher, _ = make_fetcher()

    listings, error = collect(adapter, fetcher, SEARCH, set())

    assert listings == []
    assert error is not None
    assert "AttributeError" in error


# -- _run: the wiring, the store and the exit code -------------------------


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(
        search=SEARCH,
        sites=("fake",),
        storage=Storage(database=tmp_path / "findmyhome.db"),
        digest=Digest(),
        smtp=Smtp(host="smtp.test", port=587, sender="a@test", recipients=("b@test",)),
    )


def run_once(
    config: Config,
    adapter: FakeSite,
    monkeypatch: pytest.MonkeyPatch,
    *,
    dry_run: bool = False,
    broken: Iterable[str] = (),
) -> int:
    """One `run`, with the fake adapter registered under its name for the duration."""
    monkeypatch.setitem(base.SITES, "fake", lambda fetcher, search: adapter)
    fetcher, _ = make_fetcher(broken=broken)
    with fetcher:
        return _run(config, ("fake",), config.storage.database, dry_run=dry_run, fetcher=fetcher)


def test_run_records_what_it_collected(
    config: Config, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    adapter = FakeSite({url_of("1"): make("1", 300000), url_of("2"): make("2", 320000)})

    assert run_once(config, adapter, monkeypatch) == 0
    assert "2 new" in capsys.readouterr().out
    with Store(config.storage.database) as store:
        assert store.known_ids("fake") == {"fake:1", "fake:2"}


def test_a_second_run_reports_nothing_new(
    config: Config, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The classic trap of this kind of system: a moving identity re-announces the whole market."""
    for _ in range(2):
        run_once(config, FakeSite({url_of("1"): make("1", 300000)}), monkeypatch)
    assert "0 new" in capsys.readouterr().out.splitlines()[-1]


def test_a_failure_marks_nothing_as_removed_and_exits_one(
    config: Config, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run_once(config, FakeSite({url_of("1"): make("1", 300000)}), monkeypatch)

    broken = FakeSite({url_of("1"): make("1", 300000)})
    assert run_once(config, broken, monkeypatch, broken=[url_of("1")]) == 1

    with Store(config.storage.database) as store:
        assert store.known_ids("fake") == {"fake:1"}, "a broken run removes nothing"
    assert "anomaly" in capsys.readouterr().err.lower()


def test_dry_run_neither_creates_nor_writes_the_database(
    config: Config, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    adapter = FakeSite({url_of("1"): make("1", 300000)})

    assert run_once(config, adapter, monkeypatch, dry_run=True) == 0
    assert not config.storage.database.exists(), "--dry-run means write nothing, database included"
    assert "fake:1" in capsys.readouterr().out


def test_a_site_without_an_adapter_is_skipped_not_fatal(
    config: Config, capsys: pytest.CaptureFixture[str]
) -> None:
    """`config.example.toml` enables laforet: the design is multi-site before the adapters are."""
    with Fetcher() as fetcher:
        code = _run(config, ("laforet",), config.storage.database, dry_run=False, fetcher=fetcher)
    assert code == 0
    assert "laforet" in capsys.readouterr().err
