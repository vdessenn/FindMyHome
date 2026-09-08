"""The hard filter (pipeline stage 5): criteria decide, listings do not.

Two rules carry the whole file: an unknown field never rejects — an incomplete adapter is still
useful — and the location matches on the postcode *or* the city, since a listing rarely carries
both reliably.
"""

from __future__ import annotations

from findmyhome.config import Search
from findmyhome.listing import Listing


def listing(**overrides: object) -> Listing:
    fields: dict[str, object] = {"site": "orpi", "url": "https://agency.test/a"}
    fields.update(overrides)
    return Listing(**fields)  # type: ignore[arg-type]


def test_a_search_without_criteria_matches_everything() -> None:
    assert Search(transaction="sale").matches(listing())


def test_the_transaction_must_agree() -> None:
    search = Search(transaction="sale")
    assert search.matches(listing(transaction="sale"))
    assert not search.matches(listing(transaction="rent"))


def test_the_kind_must_be_one_of_the_wanted_ones() -> None:
    search = Search(transaction="sale", kinds=("house", "farmhouse"))
    assert search.matches(listing(kind="farmhouse"))
    assert not search.matches(listing(kind="flat"))


def test_the_price_ceiling_is_inclusive() -> None:
    search = Search(transaction="sale", price_max=400000)
    assert search.matches(listing(price=400000))
    assert not search.matches(listing(price=400001))


def test_the_surface_floor_is_inclusive() -> None:
    search = Search(transaction="sale", surface_min=80)
    assert search.matches(listing(surface=80.0))
    assert not search.matches(listing(surface=79.5))


def test_the_rooms_floor_is_inclusive() -> None:
    search = Search(transaction="sale", rooms_min=4)
    assert search.matches(listing(rooms=4))
    assert not search.matches(listing(rooms=3))


def test_the_postcode_alone_places_a_listing() -> None:
    search = Search(transaction="sale", cities=("Springfield",), postcodes=("12345",))
    assert search.matches(listing(postcode="12345", city=None))


def test_the_city_alone_places_a_listing() -> None:
    search = Search(transaction="sale", cities=("Springfield",), postcodes=("12345",))
    assert search.matches(listing(city="Springfield", postcode=None))


def test_the_city_is_compared_without_case() -> None:
    search = Search(transaction="sale", cities=("Springfield",))
    assert search.matches(listing(city="SPRINGFIELD "))


def test_the_city_is_compared_without_accents() -> None:
    """Sites write their cities as URL slugs, so a config saying "Rezé" has to match "reze"."""
    search = Search(transaction="sale", cities=("Rezé",))
    assert search.matches(listing(city="reze"))


def test_the_city_is_compared_without_its_separators() -> None:
    """A slug hyphenates what a human spaces out; neither spelling may decide a match."""
    search = Search(transaction="sale", cities=("Villers-sur-Meuse",))
    assert search.matches(listing(city="Villers Sur Meuse"))


def test_a_listing_placed_elsewhere_is_rejected() -> None:
    search = Search(transaction="sale", cities=("Springfield",), postcodes=("12345",))
    assert not search.matches(listing(city="Shelbyville", postcode="99999"))


def test_an_unknown_field_never_rejects() -> None:
    """The prefilter already did the slug work; dropping in silence would be a bug (principle 6)."""
    search = Search(
        transaction="sale",
        kinds=("house",),
        cities=("Springfield",),
        postcodes=("12345",),
        price_max=400000,
        surface_min=80,
        rooms_min=4,
    )
    assert search.matches(listing())


def test_a_known_field_out_of_range_still_rejects_when_others_are_unknown() -> None:
    search = Search(transaction="sale", price_max=400000, surface_min=80)
    assert not search.matches(listing(price=500000))
