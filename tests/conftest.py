"""Fixtures shared by more than one test module."""

from __future__ import annotations

import smtplib
from collections.abc import Iterator
from typing import Any, ClassVar

import pytest


class FakeServer:
    """Stands in for `smtplib.SMTP` and records the conversation instead of having it."""

    opened: ClassVar[list[tuple[str, int]]] = []
    sent: ClassVar[list[Any]] = []
    logged_in: ClassVar[list[tuple[str, str]]] = []
    started_tls = False
    failure: ClassVar[Exception | None] = None

    def __init__(self, host: str, port: int, timeout: float = 0) -> None:
        FakeServer.opened.append((host, port))

    def __enter__(self) -> FakeServer:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def starttls(self) -> None:
        FakeServer.started_tls = True

    def login(self, user: str, password: str) -> None:
        FakeServer.logged_in.append((user, password))

    def send_message(self, message: Any) -> None:
        if FakeServer.failure is not None:
            raise FakeServer.failure
        FakeServer.sent.append(message)


@pytest.fixture
def smtp_server(monkeypatch: pytest.MonkeyPatch) -> Iterator[type[FakeServer]]:
    """No test opens a socket: both entry points of smtplib answer from the fake above."""
    FakeServer.opened, FakeServer.sent, FakeServer.logged_in = [], [], []
    FakeServer.started_tls, FakeServer.failure = False, None
    monkeypatch.setattr(smtplib, "SMTP", FakeServer)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeServer)
    yield FakeServer
