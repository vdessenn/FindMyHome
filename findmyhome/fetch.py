# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Victor DESSENNE
"""Polite HTTP client — principle 4 of ARCHITECTURE.md: polite by default, never work around.

`robots.txt` obeyed, one request per second per domain, honest `User-Agent` pointing at the
repository, retry on server errors.

The disk cache is not a production optimisation: it is what lets you develop an adapter without
re-downloading the same pages fifty times. It is therefore **off by default** and named readably,
so that a cache entry can be copied straight into `tests/fixtures/`.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from findmyhome import __version__

logger = logging.getLogger(__name__)

USER_AGENT = f"FindMyHome/{__version__} (+https://github.com/vdessenn/FindMyHome)"

# Codes meaning "this page does not (or no longer) exist": not a failure, an answer.
_ABSENT = frozenset({404, 410})

_SLUG = re.compile(r"[^a-z0-9]+")

# RobotFileParser does expose allow_all/disallow_all flags, but they are not part of its
# declared API. We go through synthetic rules instead: same effect, public API.
_ROBOTS_ALLOW_ALL = ["User-agent: *", "Disallow:"]
_ROBOTS_DENY_ALL = ["User-agent: *", "Disallow: /"]


class FetchError(RuntimeError):
    """Network or HTTP failure after every attempt has been exhausted.

    Distinct from a missing page, which is `None`: principle 6 requires that a failure can never
    be confused with "there is nothing".
    """


def cache_name(url: str) -> str:
    """Readable, stable file name for a URL.

    The hash alone would be enough for uniqueness; the slug is there so a page can be spotted by
    eye in the cache directory and copied into `tests/fixtures/` with no tooling.
    """
    parts = urlsplit(url)
    digest = hashlib.sha256(url.encode()).hexdigest()[:8]
    slug = _SLUG.sub("-", f"{parts.netloc}{parts.path}".lower()).strip("-")[:80]
    return f"{slug}-{digest}.html"


class Fetcher:
    """Fetches HTML pages politely, with an optional disk cache."""

    def __init__(
        self,
        *,
        delay: float = 1.0,
        timeout: float = 10.0,
        retries: int = 2,
        backoff: float = 1.0,
        cache_dir: Path | str | None = None,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.delay = delay
        self.retries = retries
        self.backoff = backoff
        self.user_agent = USER_AGENT
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self._sleep = sleep
        self._owns_client = client is None
        self._client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            follow_redirects=True,
        )
        self._robots: dict[str, RobotFileParser] = {}
        self._last: dict[str, float] = {}

    # -- API ---------------------------------------------------------------

    def fetch(self, url: str) -> str | None:
        """The page HTML, or `None` if it is missing or disallowed by `robots.txt`.

        Raises `FetchError` on a persistent network or server failure.
        """
        cached = self._cache_read(url)
        if cached is not None:
            # Cache first: an existing entry was already fetched politely, and short-circuiting
            # the network is exactly what this cache is for during development.
            logger.debug("cache: %s", url)
            return cached

        if not self._allowed(url):
            logger.info("robots.txt disallows %s", url)
            return None

        response = self._request(url)
        if response.status_code in _ABSENT:
            return None
        if response.status_code >= 400:
            raise FetchError(f"HTTP {response.status_code} sur {url}")

        self._cache_write(url, response.text)
        return response.text

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> Fetcher:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # -- Politeness --------------------------------------------------------

    def _allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        robots = self._robots.get(origin)
        if robots is None:
            robots = self._load_robots(origin)
            self._robots[origin] = robots
        return robots.can_fetch(self.user_agent, url)

    def _load_robots(self, origin: str) -> RobotFileParser:
        robots = RobotFileParser()
        try:
            response = self._request(f"{origin}/robots.txt")
        except FetchError:
            # robots.txt unreachable: we forbid ourselves everything (RFC 9309). Knowing
            # nothing about the rules does not license ignoring them.
            logger.warning("robots.txt unreachable on %s - domain treated as disallowed", origin)
            robots.parse(_ROBOTS_DENY_ALL)
            return robots

        if response.status_code in _ABSENT:
            # No robots.txt: nothing is disallowed (RFC 9309 section 2.3.1.3).
            robots.parse(_ROBOTS_ALLOW_ALL)
        elif response.status_code >= 400:
            robots.parse(_ROBOTS_DENY_ALL)
        else:
            robots.parse(response.text.splitlines())
        return robots

    def _wait(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            remaining = self.delay - (time.monotonic() - last)
            if remaining > 0:
                self._sleep(remaining)
        self._last[host] = time.monotonic()

    def _request(self, url: str) -> httpx.Response:
        host = urlsplit(url).netloc
        detail = "no attempt"
        for attempt in range(self.retries + 1):
            self._wait(host)
            try:
                response = self._client.get(url)
            except httpx.HTTPError as exc:
                detail = f"{type(exc).__name__}: {exc}"
            else:
                # Only 5xx deserve a retry: a 4xx will repeat identically.
                if response.status_code < 500:
                    return response
                detail = f"HTTP {response.status_code}"
            if attempt < self.retries:
                self._sleep(self.backoff * 2**attempt)
        raise FetchError(f"{url} : {detail} after {self.retries + 1} attempts")

    # -- Cache -------------------------------------------------------------

    def _cache_path(self, url: str) -> Path | None:
        return None if self.cache_dir is None else self.cache_dir / cache_name(url)

    def _cache_read(self, url: str) -> str | None:
        path = self._cache_path(url)
        if path is None or not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def _cache_write(self, url: str, body: str) -> None:
        path = self._cache_path(url)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
