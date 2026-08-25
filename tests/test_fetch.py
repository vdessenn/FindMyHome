"""The polite client, tested without a network: politeness, retry, absence, cache."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from findmyhome.fetch import Fetcher, FetchError, cache_name

PAGE = "https://agency.test/listing-sale-house-4br-springfield-12345-67890"
ROBOTS = "https://agency.test/robots.txt"


class FakeServer:
    """Fake server: answers from a URL table and remembers what it was asked for."""

    def __init__(self, responses: dict[str, httpx.Response | Exception]) -> None:
        self.responses = responses
        self.requested: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requested.append(url)
        response = self.responses.get(url, httpx.Response(404))
        if isinstance(response, Exception):
            raise response
        return httpx.Response(response.status_code, text=response.text)


def make_fetcher(
    responses: dict[str, httpx.Response | Exception],
    *,
    delay: float = 0.0,
    retries: int = 2,
    cache_dir: Path | None = None,
) -> tuple[Fetcher, FakeServer, list[float]]:
    """Fetcher on a fake server; sleeps are recorded instead of being endured."""
    server = FakeServer(responses)
    sleeps: list[float] = []
    fetcher = Fetcher(
        client=httpx.Client(transport=httpx.MockTransport(server)),
        sleep=sleeps.append,
        delay=delay,
        retries=retries,
        backoff=0.0,
        cache_dir=cache_dir,
    )
    return fetcher, server, sleeps


def test_page_fetched_when_robots_allows() -> None:
    fetcher, server, _ = make_fetcher(
        {
            ROBOTS: httpx.Response(200, text="User-agent: *\nDisallow: /search/"),
            PAGE: httpx.Response(200, text="<html>house</html>"),
        }
    )
    assert fetcher.fetch(PAGE) == "<html>house</html>"
    assert server.requested == [ROBOTS, PAGE]


def test_robots_disallows_page_no_request_made() -> None:
    fetcher, server, _ = make_fetcher(
        {ROBOTS: httpx.Response(200, text="User-agent: *\nDisallow: /listing")}
    )
    assert fetcher.fetch(PAGE) is None
    assert server.requested == [ROBOTS], "the page must never be downloaded"


def test_missing_robots_means_allowed() -> None:
    fetcher, _, _ = make_fetcher({PAGE: httpx.Response(200, text="ok")})
    assert fetcher.fetch(PAGE) == "ok"


def test_unreachable_robots_forbids_everything() -> None:
    """Knowing nothing about the rules does not license ignoring them (RFC 9309)."""
    fetcher, server, _ = make_fetcher(
        {
            ROBOTS: httpx.ConnectError("network down"),
            PAGE: httpx.Response(200, text="ok"),
        },
        retries=0,
    )
    assert fetcher.fetch(PAGE) is None
    assert PAGE not in server.requested


def test_missing_page_is_none_not_an_error() -> None:
    fetcher, _, _ = make_fetcher({PAGE: httpx.Response(410)})
    assert fetcher.fetch(PAGE) is None


def test_server_error_retried_then_reported() -> None:
    """Principle 6: a failure must never be able to pass for "there is nothing"."""
    fetcher, server, _ = make_fetcher({PAGE: httpx.Response(503)}, retries=2)
    with pytest.raises(FetchError, match="503"):
        fetcher.fetch(PAGE)
    assert server.requested.count(PAGE) == 3


def test_one_second_between_requests_to_same_host() -> None:
    fetcher, _, sleeps = make_fetcher(
        {PAGE: httpx.Response(200, text="ok")},
        delay=1.0,
    )
    fetcher.fetch(PAGE)
    # robots.txt then the page: two requests to the same host, so one wait between them.
    assert len(sleeps) == 1
    assert 0.9 < sleeps[0] <= 1.0


def test_cache_short_circuits_the_network(tmp_path: Path) -> None:
    responses: dict[str, httpx.Response | Exception] = {PAGE: httpx.Response(200, text="ok")}
    fetcher, server, _ = make_fetcher(responses, cache_dir=tmp_path)

    assert fetcher.fetch(PAGE) == "ok"
    requests_after_first_call = len(server.requested)

    assert fetcher.fetch(PAGE) == "ok"
    assert len(server.requested) == requests_after_first_call, "second call: no network"


def test_cache_survives_a_new_fetcher(tmp_path: Path) -> None:
    """The cache is on disk: restarting the process must not re-download."""
    first, _, _ = make_fetcher({PAGE: httpx.Response(200, text="ok")}, cache_dir=tmp_path)
    first.fetch(PAGE)

    second, server, _ = make_fetcher({}, cache_dir=tmp_path)
    assert second.fetch(PAGE) == "ok"
    assert server.requested == []


def test_cache_name_is_readable_and_stable() -> None:
    name = cache_name(PAGE)
    assert name.startswith("agency-test-listing-sale-house-4br-springfield-12345-67890")
    assert name.endswith(".html")
    assert name == cache_name(PAGE)
    assert name != cache_name(PAGE + "-other")
