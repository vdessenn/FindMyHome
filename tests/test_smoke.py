"""Proves the package imports, the entry point is wired and pytest is configured."""

from __future__ import annotations

import pytest

from findmyhome.__main__ import main


def test_version_flag_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "findmyhome" in capsys.readouterr().out


def test_no_command_prints_help() -> None:
    assert main([]) == 2


def test_run_is_a_stub() -> None:
    assert main(["run", "--dry-run"]) == 0
