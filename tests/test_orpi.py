# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Victor DESSENNE
"""The Orpi adapter, offline, on pruned captures of real pages.

What is worth pinning here is what the site actually does, not what an adapter would like it to
do: a listing that no longer exists answers 200 with the generic homepage, the surface is missing
from the analytics block and only appears in the body, and the cities are unaccented slugs.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from findmyhome.config import Search
from findmyhome.fetch import Fetcher, FetchError
from findmyhome.sites.orpi import SITEMAP, Orpi

FIXTURES = Path(__file__).resolve().parent / "fixtures"

NANTES = "https://www.orpi.com/annonce-vente-maison-t5-nantes-44000-1849954c-7350-45e1-8601-132c34380a1c/"
REZE = (
    "https://www.orpi.com/annonce-vente-maison-t4-reze-44400-c623e71d-6b04-4793-8236-b8f88be8fb80/"
)
FLAT = "https://www.orpi.com/annonce-vente-appartement-t2-nantes-44000-eecc4f70-de4e-4c90-be20-6bd4485eeef1/"
NANTES_NORTH = "https://www.orpi.com/annonce-vente-maison-t8-nantes-44300-3f9c89e5-4f65-493a-8c11-8509345a6b7d/"
ELSEWHERE = "https://www.orpi.com/annonce-vente-maison-t4-villers-sur-meuse-55220-7230-048927-180/"

SEARCH = Search(
    transaction="sale",
    kinds=("house",),
    cities=("Nantes", "Rezé"),
    postcodes=("44000", "44400"),
    price_max=450000,
    surface_min=80,
    rooms_min=4,
)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def offline() -> Iterator[Fetcher]:
    """A fetcher that serves the sitemap fixture and 404s the rest: no test touches the network."""

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/robots.txt"):
            return httpx.Response(200, text="User-agent: *\nDisallow: /recherche/")
        if str(request.url) == SITEMAP:
            return httpx.Response(200, text=fixture("orpi-sitemap.xml"))
        return httpx.Response(404)

    with Fetcher(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
        delay=0.0,
        retries=0,
    ) as fetcher:
        yield fetcher


@pytest.fixture
def orpi(offline: Fetcher) -> Orpi:
    return Orpi(offline, SEARCH)


# -- discover ---------------------------------------------------------------


def test_discover_reads_the_listing_urls_from_the_sitemap(orpi: Orpi) -> None:
    urls = list(orpi.discover())
    assert len(urls) == 6
    assert NANTES in urls


def test_a_sitemap_we_cannot_read_is_a_failure_not_an_empty_market(offline: Fetcher) -> None:
    """Principle 6 starts here: no sitemap means we know nothing, not that nothing is for sale."""
    adapter = Orpi(offline, SEARCH)
    adapter.sitemap = "https://www.orpi.com/sitemap-absent.xml"
    with pytest.raises(FetchError):
        list(adapter.discover())


# -- prefilter --------------------------------------------------------------


def test_a_matching_slug_is_downloaded(orpi: Orpi) -> None:
    assert orpi.prefilter(NANTES)


def test_an_unaccented_city_slug_matches_an_accented_criterion(orpi: Orpi) -> None:
    """`reze` is what Orpi writes; `Rezé` is what a human writes in the configuration."""
    assert orpi.prefilter(REZE)


def test_the_wrong_kind_and_too_few_rooms_are_read_off_the_slug(orpi: Orpi) -> None:
    assert not orpi.prefilter(FLAT), "an apartment with two rooms costs a download for nothing"


def test_another_town_is_read_off_the_slug(orpi: Orpi) -> None:
    assert not orpi.prefilter(ELSEWHERE)


def test_the_right_town_under_an_unlisted_postcode_is_still_downloaded(orpi: Orpi) -> None:
    """Postcode *or* city: a big town spans several postcodes, and the criteria name the town."""
    assert orpi.prefilter(NANTES_NORTH)


def test_a_rental_slug_is_refused_by_a_sale_search(orpi: Orpi) -> None:
    assert not orpi.prefilter("https://www.orpi.com/annonce-location-maison-t5-nantes-44000-abc/")


def test_a_url_the_slug_rule_cannot_read_is_downloaded(orpi: Orpi) -> None:
    """When in doubt, download: a silent skip is the one failure mode with no symptom."""
    assert orpi.prefilter("https://www.orpi.com/agence-immobiliere-nantes-centre/")


# -- parse ------------------------------------------------------------------


def test_parse_extracts_the_fields_of_a_real_listing(orpi: Orpi) -> None:
    listing = orpi.parse(NANTES, fixture("orpi-house-t5.html"))
    assert listing is not None
    assert listing.ref == "1849954c-7350-45e1-8601-132c34380a1c"
    assert listing.id == "orpi:1849954c-7350-45e1-8601-132c34380a1c"
    assert listing.price == 419800
    assert listing.rooms == 5
    assert listing.city == "Nantes"
    assert listing.postcode == "44000"
    assert listing.kind == "house"
    assert listing.transaction == "sale"
    assert listing.agency == "Urban Immo"
    assert listing.photo_url is not None and listing.photo_url.startswith("https://")
    assert listing.title is not None and "Orpi" not in listing.title


def test_the_surface_is_read_from_the_body_not_the_analytics(orpi: Orpi) -> None:
    """The analytics block ships an empty `surfaceBien`; the page itself says 87,34 m²."""
    listing = orpi.parse(NANTES, fixture("orpi-house-t5.html"))
    assert listing is not None
    assert listing.surface == pytest.approx(87.34)


def test_the_surface_is_read_from_the_analytics_when_the_body_omits_it(orpi: Orpi) -> None:
    """The other real page: `surfaceBien` says `105-3` and no "Surface" line exists in the body.

    Two pages of the same site, two places for the same field - which is why both are read, and
    why a listing that has neither is a `None` surface rather than a guess.
    """
    listing = orpi.parse(NANTES, fixture("orpi-house-surface-in-analytics.html"))
    assert listing is not None
    assert listing.surface == pytest.approx(105.3)
    assert listing.price == 423000


def test_the_land_area_is_never_taken_for_the_living_space(orpi: Orpi) -> None:
    """That page carries `Terrain 59,40 m²`: reading it as the surface would fail `surface_min`
    upwards, which is the kind of wrong that never looks wrong."""
    listing = orpi.parse(NANTES, fixture("orpi-house-surface-in-analytics.html"))
    assert listing is not None
    assert listing.surface != pytest.approx(59.40)


def test_a_parsed_listing_satisfies_the_criteria_it_was_filtered_on(orpi: Orpi) -> None:
    listing = orpi.parse(NANTES, fixture("orpi-house-t5.html"))
    assert listing is not None
    assert SEARCH.matches(listing)


def test_a_listing_that_no_longer_exists_is_none(orpi: Orpi) -> None:
    """Orpi answers 200 with its homepage rather than 404: only the missing block says so."""
    assert orpi.parse(NANTES, fixture("orpi-not-a-listing.html")) is None
