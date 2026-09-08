# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Victor DESSENNE
"""The command line: it must say the truth about what it did, and nothing more.

These tests run the real `main`, so they deliberately restrict every `run` to `laforet` - the site
the example configuration enables and no adapter serves yet. That keeps the smoke tests offline;
what the pipeline does once an adapter answers is `test_pipeline.py`'s job.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from findmyhome.__main__ import main

EXAMPLE = Path(__file__).resolve().parent.parent / "config.example.toml"


@pytest.fixture
def config(tmp_path: Path) -> Path:
    """The shipped example, copied: if it stops being usable, these tests say so."""
    path = tmp_path / "config.toml"
    shutil.copy(EXAMPLE, path)
    return path


def test_version_flag_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "findmyhome" in capsys.readouterr().out


def test_no_command_prints_help() -> None:
    assert main([]) == 2


def test_run_opens_the_database(tmp_path: Path, config: Path) -> None:
    database = tmp_path / "findmyhome.db"
    assert main(["run", "--site", "laforet", "--config", str(config), "--db", str(database)]) == 0
    assert database.exists()


def test_run_creates_the_database_where_the_config_says(
    tmp_path: Path, config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default path is relative, so it follows the working directory (and Docker's /data)."""
    monkeypatch.chdir(tmp_path)
    assert main(["run", "--site", "laforet", "--config", str(config)]) == 0
    assert (tmp_path / "findmyhome.db").exists()


def test_dry_run_writes_nothing(tmp_path: Path, config: Path) -> None:
    database = tmp_path / "findmyhome.db"
    argv = ["run", "--dry-run", "--site", "laforet", "--config", str(config)]
    assert main([*argv, "--db", str(database)]) == 0
    assert not database.exists(), "--dry-run means write nothing, database included"


def test_a_missing_config_is_reported_not_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["run", "--config", str(tmp_path / "absent.toml")]) == 2
    assert "absent.toml" in capsys.readouterr().err


def test_an_invalid_config_exits_two(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    broken = tmp_path / "config.toml"
    broken.write_text('[search]\ntransaction = "barter"\n', encoding="utf-8")
    assert main(["run", "--config", str(broken)]) == 2
    assert "transaction" in capsys.readouterr().err


def test_list_sites_names_the_enabled_sites(
    config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["list-sites", "--config", str(config)]) == 0
    out = capsys.readouterr().out
    assert "orpi" in out
    assert "laforet\t(no adapter yet)" in out, "the listing has to say which sites can run"


def test_a_site_absent_from_the_config_is_refused(
    config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["run", "--site", "unknown", "--config", str(config)]) == 2
    assert "unknown" in capsys.readouterr().err


def test_a_configured_site_without_an_adapter_is_named_and_skipped(
    tmp_path: Path, config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Skipped, not fatal: the example configuration is allowed to describe more than exists."""
    code = main(
        ["run", "--site", "laforet", "--config", str(config), "--db", str(tmp_path / "d.db")]
    )
    assert code == 0
    assert "laforet" in capsys.readouterr().err.lower()
