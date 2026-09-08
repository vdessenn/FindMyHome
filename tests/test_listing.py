# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Victor DESSENNE
"""Listing identity: the frozen contract principle 5 rests on.

"New" means "absent from our database", so an identity that moves between two runs would
report the whole market as new. These tests are what keeps it still.
"""

from __future__ import annotations

import dataclasses

import pytest

from findmyhome.listing import Listing, canonical_url

URL = "https://agency.test/listing-sale-house-4br-springfield-12345-67890"


def listing(**overrides: object) -> Listing:
    fields: dict[str, object] = {"site": "orpi", "url": URL}
    fields.update(overrides)
    return Listing(**fields)  # type: ignore[arg-type]


def test_reference_wins_over_the_url() -> None:
    assert listing(ref="A-4212").id == "orpi:A-4212"


def test_the_same_reference_on_two_sites_stays_two_listings() -> None:
    assert listing(ref="A-4212").id != listing(site="laforet", ref="A-4212").id


def test_an_empty_reference_falls_back_to_the_url() -> None:
    """An adapter that finds no reference must not make every listing share one identity."""
    assert listing(ref="").id == listing().id
    assert listing(ref=None).id == listing().id


def test_the_url_identity_ignores_tracking_parameters() -> None:
    assert listing(url=f"{URL}?utm_source=newsletter").id == listing().id


def test_the_url_identity_ignores_the_fragment_and_a_trailing_slash() -> None:
    assert listing(url=f"{URL}/#photos").id == listing().id


def test_the_url_identity_ignores_host_case() -> None:
    assert listing(url=URL.replace("agency.test", "Agency.Test")).id == listing().id


def test_two_different_pages_keep_two_identities() -> None:
    assert listing(url=f"{URL}-other").id != listing().id


def test_identity_is_stable_across_calls() -> None:
    assert listing().id == listing().id


def test_the_identity_carries_the_site_in_both_variants() -> None:
    assert listing(ref="A-4212").id.startswith("orpi:")
    assert listing().id.startswith("orpi:")


def test_canonical_url_keeps_the_path_intact() -> None:
    """Only the volatile parts go: the path is what identifies the page."""
    assert canonical_url(f"{URL}?a=1#b") == URL


def test_a_listing_is_immutable() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        listing().price = 1  # type: ignore[misc]


def test_every_field_but_the_site_and_the_url_is_optional() -> None:
    """An incomplete adapter is still useful (ARCHITECTURE.md, adapter contract)."""
    incomplete = listing()
    assert incomplete.price is None
    assert incomplete.title is None
