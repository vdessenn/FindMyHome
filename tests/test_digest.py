"""The email: what it says, what it escapes, and what it refuses to send.

The rendering is a pure function, so most of this file reads values off a string. The one property
worth more than the rest is the escaping: every field in this email came from someone else's HTML.
"""

from __future__ import annotations

import smtplib
from typing import Any

import pytest
from conftest import FakeServer

from findmyhome.config import Smtp
from findmyhome.digest import DigestError, is_quiet, render, send
from findmyhome.listing import Listing
from findmyhome.store import Changes, PriceChange

SMTP = Smtp(
    host="smtp.test",
    port=587,
    sender="findmyhome@test",
    recipients=("me@test",),
    password="hunter2",
)


def listing(ref: str = "1", price: int | None = 419800, **fields: Any) -> Listing:
    return Listing(
        site=fields.pop("site", "orpi"),
        url=f"https://orpi.test/listing/{ref}",
        ref=ref,
        title=fields.pop("title", "House with a garden"),
        price=price,
        surface=fields.pop("surface", 87.34),
        rooms=fields.pop("rooms", 5),
        city=fields.pop("city", "Nantes"),
        postcode="44000",
        agency=fields.pop("agency", "Urban Immo"),
        photo_url=fields.pop("photo_url", "https://cdn.test/1.jpg"),
        transaction="sale",
        kind="house",
    )


def changes(**fields: Any) -> Changes:
    return Changes(
        site=fields.pop("site", "orpi"),
        new=fields.pop("new", []),
        price_changes=fields.pop("price_changes", []),
        removed=fields.pop("removed", []),
        anomaly=fields.pop("anomaly", None),
    )


# -- what the digest says ---------------------------------------------------


def test_a_run_with_nothing_to_say_is_quiet() -> None:
    assert is_quiet([changes()])


def test_an_anomaly_alone_is_never_quiet() -> None:
    """`send_when_empty` is about a calm market, not about a scraper that stopped answering."""
    assert not is_quiet([changes(anomaly="orpi: 0 listings found")])


def test_the_sections_appear_only_when_they_have_something_in_them() -> None:
    mail = render([changes(new=[listing()])])
    assert "New listings" in mail.html
    assert "Removed" not in mail.html
    assert "Price" not in mail.html


def test_price_drops_come_before_price_rises() -> None:
    """The reason the email gets opened goes first."""
    mail = render(
        [
            changes(
                price_changes=[
                    PriceChange(listing("up"), 400000, 420000),
                    PriceChange(listing("down"), 400000, 380000),
                ]
            )
        ]
    )
    assert mail.text.index("Price drops") < mail.text.index("Price rises")


def test_the_subject_summarises_what_moved() -> None:
    mail = render([changes(new=[listing("1"), listing("2")], removed=[listing("3")])])
    assert "2 new" in mail.subject
    assert "1 removed" in mail.subject


def test_the_subject_counts_a_single_change_in_the_singular() -> None:
    mail = render([changes(price_changes=[PriceChange(listing(), 400000, 380000)])])
    assert "1 price drops" not in mail.subject
    assert "1 price drop" in mail.subject


def test_every_listing_carries_its_link_and_its_site() -> None:
    mail = render([changes(new=[listing()])])
    assert "https://orpi.test/listing/1" in mail.html
    assert "orpi" in mail.text


def test_an_unknown_field_is_not_invented() -> None:
    """An adapter that found no surface must not produce a listing that claims one."""
    mail = render([changes(new=[listing(surface=None, price=None)])])
    assert "None" not in mail.text
    assert "None" not in mail.html


def test_the_html_escapes_what_the_sites_wrote() -> None:
    """Every field here came from someone else's HTML. This is the one that must never fail."""
    mail = render([changes(new=[listing(title='<script>alert("x")</script>', agency="Foo & Bar")])])
    assert "<script>" not in mail.html
    assert "&lt;script&gt;" in mail.html
    assert "Foo &amp; Bar" in mail.html


def test_the_photo_is_a_thumbnail_the_email_can_do_without() -> None:
    mail = render([changes(new=[listing()])])
    assert 'src="https://cdn.test/1.jpg"' in mail.html
    assert "alt=" in mail.html
    assert "House with a garden" in mail.text, "the text part never depends on an image"


def test_the_anomaly_names_the_site_and_says_nothing_was_removed() -> None:
    mail = render([changes(anomaly="orpi: 0 listings found, 7 on the previous successful run")])
    assert "Anomalies" in mail.html
    assert "orpi" in mail.text


# -- sending ----------------------------------------------------------------


def test_send_builds_a_multipart_message(smtp_server: type[FakeServer]) -> None:
    send(SMTP, render([changes(new=[listing()])]))
    (message,) = smtp_server.sent
    assert message["To"] == "me@test"
    assert message["From"] == "findmyhome@test"
    assert message.get_body(("plain",)) is not None, "a text part, for the mobile preview"
    assert message.get_body(("html",)) is not None


def test_send_starts_tls_on_the_submission_port(smtp_server: type[FakeServer]) -> None:
    send(SMTP, render([changes(new=[listing()])]))
    assert smtp_server.started_tls
    assert smtp_server.logged_in == [("findmyhome@test", "hunter2")]


def test_an_implicit_tls_port_is_not_upgraded(smtp_server: type[FakeServer]) -> None:
    import dataclasses

    send(dataclasses.replace(SMTP, port=465), render([changes(new=[listing()])]))
    assert not smtp_server.started_tls, "465 is already encrypted; STARTTLS on it is an error"


def test_a_missing_password_is_refused_before_connecting(smtp_server: type[FakeServer]) -> None:
    import dataclasses

    with pytest.raises(DigestError, match="FINDMYHOME_SMTP_PASSWORD"):
        send(dataclasses.replace(SMTP, password=None), render([changes(new=[listing()])]))
    assert smtp_server.opened == [], "no point opening a connection we cannot authenticate"


def test_a_refused_delivery_is_a_digest_error_not_an_smtplib_one(
    smtp_server: type[FakeServer],
) -> None:
    """The caller has to be able to catch it and roll the database back."""
    smtp_server.failure = smtplib.SMTPRecipientsRefused({})
    with pytest.raises(DigestError):
        send(SMTP, render([changes(new=[listing()])]))
