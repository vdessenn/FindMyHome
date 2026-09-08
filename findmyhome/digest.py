# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Victor DESSENNE
"""The email: one digest for every enabled site, rendered by hand and sent over SMTP.

f-strings rather than a template engine, under the condition ARCHITECTURE.md sets for reopening
that choice. The safety net it asks for is structural: every scraped value reaches the HTML
through `_e`, and the two `_row` functions are the only places a listing's fields are read. An
escape cannot be remembered in one branch and forgotten in another when there is one branch.
"""

from __future__ import annotations

import html
import smtplib
from collections.abc import Sequence
from dataclasses import dataclass
from email.message import EmailMessage

from findmyhome.config import PASSWORD_ENV, Smtp
from findmyhome.listing import Listing
from findmyhome.store import Changes, PriceChange

_MUTED = "color:#666"
_TIMEOUT = 30.0


class DigestError(RuntimeError):
    """The digest could not be delivered. Nothing is recorded when this is raised."""


@dataclass(frozen=True, slots=True)
class Mail:
    subject: str
    text: str
    html: str


def _e(value: object) -> str:
    """The only door into the HTML. Everything on the other side came from someone else's page."""
    return html.escape(str(value))


def _price(value: int | None) -> str | None:
    return None if value is None else f"{value:,} €".replace(",", " ")


def _facts(listing: Listing) -> str:
    """Whatever is known about a listing, in one line. What is unknown is left out, not invented."""
    known = (
        _price(listing.price),
        None if listing.surface is None else f"{listing.surface:g} m²",
        None if listing.rooms is None else f"{listing.rooms} rooms",
        listing.city,
        listing.agency,
        listing.site,
    )
    return " · ".join(fact for fact in known if fact)


def _move(change: PriceChange) -> str:
    return f" ({_price(change.old_price)} → {_price(change.new_price)})"


def _text_row(listing: Listing, note: str) -> str:
    return f"- {listing.title or listing.url}{note}\n  {_facts(listing)}\n  {listing.url}"


def _html_row(listing: Listing, note: str) -> str:
    photo = (
        ""
        if listing.photo_url is None
        else f'<a href="{_e(listing.url)}"><img src="{_e(listing.photo_url)}" alt="" width="110" '
        'style="border-radius:4px;float:left;margin:0 12px 0 0"></a>'
    )
    return (
        f'<li style="margin:0 0 18px;overflow:hidden;list-style:none">{photo}'
        f'<a href="{_e(listing.url)}">{_e(listing.title or listing.url)}</a>{_e(note)}'
        f'<div style="{_MUTED}">{_e(_facts(listing))}</div></li>'
    )


def _sections(runs: Sequence[Changes]) -> list[tuple[str, str, list[tuple[Listing, str]]]]:
    """Each section as (heading, how the subject counts it, rows).

    Drops before rises: the reason this email gets opened comes first.
    """
    moves = [change for run in runs for change in run.price_changes]
    return [
        ("New listings", "new", [(found, "") for run in runs for found in run.new]),
        ("Price drops", "price drops", [(m.listing, _move(m)) for m in moves if m.is_drop]),
        ("Price rises", "price rises", [(m.listing, _move(m)) for m in moves if not m.is_drop]),
        ("Removed", "removed", [(gone, "") for run in runs for gone in run.removed]),
    ]


def _anomalies(runs: Sequence[Changes]) -> list[str]:
    return [run.anomaly for run in runs if run.anomaly is not None]


def is_quiet(runs: Sequence[Changes]) -> bool:
    """True when there is nothing to say at all.

    An anomaly is something to say even when the market did not move: `send_when_empty` is about a
    calm market, never about a scraper that stopped answering (principle 6).
    """
    return not _anomalies(runs) and not any(rows for _, _, rows in _sections(runs))


def _count(number: int, label: str) -> str:
    return f"{number} {label[:-1] if number == 1 and label.endswith('s') else label}"


def render(runs: Sequence[Changes]) -> Mail:
    """The digest as a subject and two bodies. Pure: it neither reads nor sends anything."""
    sections = _sections(runs)
    anomalies = _anomalies(runs)
    text: list[str] = []
    body: list[str] = []

    for heading, _, rows in sections:
        if not rows:
            continue
        text.append(
            f"{heading}\n{'=' * len(heading)}\n" + "\n".join(_text_row(*row) for row in rows)
        )
        body.append(
            f"<h2 style='font-size:17px'>{heading}</h2><ul style='padding:0'>"
            + "".join(_html_row(*row) for row in rows)
            + "</ul>"
        )
    if anomalies:
        text.append("Anomalies\n=========\n" + "\n".join(f"- {note}" for note in anomalies))
        body.append(
            "<h2 style='font-size:17px'>Anomalies</h2><ul>"
            + "".join(f"<li>{_e(note)}</li>" for note in anomalies)
            + "</ul>"
        )

    counts = [_count(len(rows), label) for _, label, rows in sections if rows]
    if anomalies:
        counts.append(
            f"{len(anomalies)} anomaly" if len(anomalies) == 1 else f"{len(anomalies)} anomalies"
        )
    return Mail(
        subject=f"FindMyHome: {', '.join(counts) or 'nothing new'}",
        text="\n\n".join(text) or "Nothing moved.",
        html=(
            "<html><body style='font-family:system-ui,sans-serif;font-size:15px;color:#222'>"
            + ("".join(body) or "<p>Nothing moved.</p>")
            + f"<p style='{_MUTED};font-size:12px'>FindMyHome</p></body></html>"
        ),
    )


def _server(smtp: Smtp) -> smtplib.SMTP:
    if smtp.port == 465:
        # Implicit TLS: the connection is encrypted before the first command, and STARTTLS on it
        # is an error rather than an upgrade.
        return smtplib.SMTP_SSL(smtp.host, smtp.port, timeout=_TIMEOUT)
    server = smtplib.SMTP(smtp.host, smtp.port, timeout=_TIMEOUT)
    server.starttls()
    return server


def send(smtp: Smtp, mail: Mail) -> None:
    """Deliver the digest, or raise `DigestError`.

    Raising is what lets the caller record nothing: a digest that did not leave must be reported
    again on the next run, and the database is what decides whether it will be.
    """
    if not smtp.recipients:
        raise DigestError("[smtp] to: no recipient is configured")
    if smtp.password is None:
        # ponytail: the login is the `from` address. Add an [smtp] username key the day a provider
        # wants a different one - most want exactly this.
        raise DigestError(f"{PASSWORD_ENV} is not set, so the digest cannot be sent")

    message = EmailMessage()
    message["Subject"] = mail.subject
    message["From"] = smtp.sender
    message["To"] = ", ".join(smtp.recipients)
    message.set_content(mail.text)
    message.add_alternative(mail.html, subtype="html")

    try:
        with _server(smtp) as server:
            server.login(smtp.sender, smtp.password)
            server.send_message(message)
    except (smtplib.SMTPException, OSError) as error:
        raise DigestError(f"{smtp.host}:{smtp.port}: {error}") from error
