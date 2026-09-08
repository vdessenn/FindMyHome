# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Victor DESSENNE
"""Configuration loading: strict, and it reports every problem at once.

A config file is edited by hand. Stopping on the first error means as many runs as there are
typos, and a silently ignored key is the worst of them: the search runs, on the wrong criteria.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from findmyhome.config import ConfigError, load

EXAMPLE = Path(__file__).resolve().parent.parent / "config.example.toml"

VALID = """
[search]
transaction = "sale"
kinds = ["house"]
cities = ["Springfield"]
postcodes = ["12345"]
price_max = 400000
surface_min = 80
rooms_min = 4

[sites]
enabled = ["orpi"]

[smtp]
host = "smtp.example.net"
port = 587
from = "findmyhome@example.net"
to = ["me@example.net"]
"""


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_the_shipped_example_loads() -> None:
    """config.example.toml documents every key: if it stops loading, it stops documenting."""
    config = load(EXAMPLE)
    assert config.search.transaction == "sale"
    assert config.sites == ("orpi", "laforet")


def test_a_missing_storage_table_falls_back_to_a_relative_default(tmp_path: Path) -> None:
    """Relative on purpose: the Docker image runs in /data, so the default lands there."""
    config = load(write(tmp_path, VALID))
    assert config.storage.database == Path("findmyhome.db")
    assert not config.storage.database.is_absolute()


def test_the_storage_table_overrides_the_default(tmp_path: Path) -> None:
    config = load(write(tmp_path, VALID + '\n[storage]\ndatabase = "/srv/findmyhome.db"\n'))
    assert config.storage.database == Path("/srv/findmyhome.db")


def test_send_when_empty_defaults_to_false(tmp_path: Path) -> None:
    assert load(write(tmp_path, VALID)).digest.send_when_empty is False


def test_the_smtp_from_key_becomes_the_sender(tmp_path: Path) -> None:
    """`from` is a Python keyword: the TOML key and the attribute cannot share a name."""
    config = load(write(tmp_path, VALID))
    assert config.smtp.sender == "findmyhome@example.net"
    assert config.smtp.recipients == ("me@example.net",)


def test_the_smtp_password_comes_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FINDMYHOME_SMTP_PASSWORD", "s3cret")
    assert load(write(tmp_path, VALID)).smtp.password == "s3cret"


def test_an_absent_password_is_none_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only sending needs it; loading a config to inspect it must not require the secret."""
    monkeypatch.delenv("FINDMYHOME_SMTP_PASSWORD", raising=False)
    assert load(write(tmp_path, VALID)).smtp.password is None


def test_the_password_never_shows_up_in_a_repr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The repository is public and a config gets printed into logs by accident."""
    monkeypatch.setenv("FINDMYHOME_SMTP_PASSWORD", "s3cret")
    config = load(write(tmp_path, VALID))
    assert "s3cret" not in repr(config)


def test_a_missing_table_is_named(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"\[smtp\]"):
        load(write(tmp_path, VALID.replace("[smtp]", "[unused]")))


def test_a_missing_required_key_is_named(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="transaction"):
        load(write(tmp_path, VALID.replace('transaction = "sale"', "")))


def test_an_unknown_key_is_refused_not_ignored(tmp_path: Path) -> None:
    """`price_maxx` silently ignored is a search that runs on the wrong criteria."""
    with pytest.raises(ConfigError, match="price_maxx"):
        load(write(tmp_path, VALID.replace("price_max =", "price_maxx =")))


def test_an_unknown_table_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="serach"):
        load(write(tmp_path, VALID + "\n[serach]\n"))


def test_an_invalid_transaction_lists_what_is_allowed(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="sale"):
        load(write(tmp_path, VALID.replace('"sale"', '"barter"')))


def test_a_wrong_type_is_reported(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="price_max"):
        load(write(tmp_path, VALID.replace("price_max = 400000", 'price_max = "400000"')))


def test_every_problem_is_reported_in_one_go(tmp_path: Path) -> None:
    """One run, one fix round: the whole point of accumulating instead of raising early."""
    broken = VALID.replace('transaction = "sale"', "").replace("rooms_min", "rooms_minimum")
    broken = broken.replace("port = 587", 'port = "587"')
    with pytest.raises(ConfigError) as error:
        load(write(tmp_path, broken))
    message = str(error.value)
    assert "transaction" in message
    assert "rooms_minimum" in message
    assert "port" in message


def test_a_missing_file_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"config\.toml"):
        load(tmp_path / "config.toml")


def test_invalid_toml_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load(write(tmp_path, "[search\n"))
