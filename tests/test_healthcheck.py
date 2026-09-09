# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Victor DESSENNE
"""Principle 6 at the scheduler boundary.

Inside a run, a broken scraper reports an anomaly and `run` exits 1. Around the run, nothing said
anything: with `send_when_empty = false`, a day without an email means either a quiet market or a
run that never happened. `healthcheck` is what separates the two, so these tests are mostly about
the second - the silence, not the noise.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from findmyhome.__main__ import EXIT_FAILED, EXIT_OK, _healthcheck
from findmyhome.config import Config, Digest, Search, Smtp, Storage
from findmyhome.store import Store

MAX_AGE = 48.0


def config_for(tmp_path: Path, *sites: str) -> Config:
    return Config(
        search=Search(transaction="sale"),
        sites=sites,
        storage=Storage(database=tmp_path / "findmyhome.db"),
        digest=Digest(),
        smtp=Smtp(
            host="smtp.test", port=587, sender="a@test", recipients=("b@test",), password="x"
        ),
    )


def record(database: Path, site: str, *, hours_ago: float, error: str | None = None) -> None:
    """One `site_run` row, as far in the past as the test needs."""
    with Store(database) as store:
        store.diff(site, [], error=error, now=datetime.now(UTC) - timedelta(hours=hours_ago))


def test_a_recent_run_without_error_is_healthy(tmp_path: Path) -> None:
    config = config_for(tmp_path, "orpi")
    record(config.storage.database, "orpi", hours_ago=3)
    assert _healthcheck(config, config.storage.database, MAX_AGE) == EXIT_OK


def test_a_run_older_than_the_limit_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = config_for(tmp_path, "orpi")
    record(config.storage.database, "orpi", hours_ago=72)
    assert _healthcheck(config, config.storage.database, MAX_AGE) == EXIT_FAILED
    assert "orpi" in capsys.readouterr().err


def test_an_enabled_site_that_never_ran_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The database exists and other sites are fine: this one simply was never collected."""
    config = config_for(tmp_path, "orpi", "laforet")
    record(config.storage.database, "orpi", hours_ago=3)
    assert _healthcheck(config, config.storage.database, MAX_AGE) == EXIT_FAILED
    assert "laforet" in capsys.readouterr().err


def test_a_run_carrying_an_error_fails_even_when_recent(tmp_path: Path) -> None:
    config = config_for(tmp_path, "orpi")
    record(config.storage.database, "orpi", hours_ago=1, error="FetchError: 503")
    assert _healthcheck(config, config.storage.database, MAX_AGE) == EXIT_FAILED


def test_a_missing_database_is_a_failure_and_is_not_created(tmp_path: Path) -> None:
    """Opening a Store would run _migrate() and hide the outage behind empty tables - and the
    watchdog must never write to production."""
    config = config_for(tmp_path, "orpi")
    absent = tmp_path / "nowhere" / "findmyhome.db"
    assert _healthcheck(config, absent, MAX_AGE) == EXIT_FAILED
    assert not absent.exists()


def test_one_stale_site_among_healthy_ones_still_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The check is per site: an adapter that quietly stopped being collected while the others
    keep running is exactly what principle 6 is about."""
    config = config_for(tmp_path, "orpi", "laforet")
    record(config.storage.database, "orpi", hours_ago=3)
    record(config.storage.database, "laforet", hours_ago=200)
    assert _healthcheck(config, config.storage.database, MAX_AGE) == EXIT_FAILED
    reported = capsys.readouterr().err
    assert "laforet" in reported
    assert "orpi" not in reported
