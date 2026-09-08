# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Victor DESSENNE
"""The Orpi adapter — principle 3: in through the sitemap, never through the search pages.

Three things about this site shaped the module.

Its listing pages carry an analytics block that names every field we need, and it is far steadier
than the utility classes around it: a redesign renames `h2 text-primary`, it does not rename
`prdamount`. The surface is the exception - that block ships it empty and only the page body
carries it.

And a listing that no longer exists answers **200 with the generic homepage**, not 404. The
absence of the analytics block is therefore what "gone" looks like, which is exactly what `parse`
returning `None` is for.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import urlsplit
from xml.etree import ElementTree

# selectolax ships two backends: Modest (LGPL-2.1) and lexbor (Apache-2.0). We take lexbor,
# whose licence carries no relink obligation for the standalone binary. The API is identical.
from selectolax.lexbor import LexborHTMLParser

from findmyhome.config import Search
from findmyhome.fetch import Fetcher, FetchError
from findmyhome.listing import Listing, Transaction

NAME = "orpi"
BASE_URL = "https://www.orpi.com"
SITEMAP = f"{BASE_URL}/sitemap-biens-a-vendre.xml"

# The site's vocabulary mapped onto the configuration's. It lives here and nowhere else: the core
# and `config.toml` stay in English and never learn that this site is French (principle 1). A word
# that is not in the table travels as-is - it will match no English criterion, which is the right
# answer for a "terrain" in a search for houses.
_KINDS = {
    "maison": "house",
    "appartement": "flat",
    "terrain": "land",
    "immeuble": "building",
    "bureau": "office",
    "local": "premises",
    "parking": "parking",
}
_TRANSACTIONS: dict[str, Transaction] = {"vente": "sale", "location": "rent", "buy": "sale"}

# `key: 'value'` and `key: "value"`, both of which the block mixes. A value containing a quote
# would be cut short; every field read below is a slug, a number or a postcode.
_PAIR = re.compile(r"(\w+)\s*:\s*['\"]([^'\"]*)['\"]")
_ROOMS = re.compile(r"^t(\d+)$")
_POSTCODE = re.compile(r"^\d{5}$")
# Thin and non-breaking spaces are what a French page groups thousands with.
_NUMBER = re.compile(r"\d[\d\s]*(?:[.,]\d+)?")


def _meta(tree: LexborHTMLParser, prop: str) -> str | None:
    node = tree.css_first(f'meta[property="{prop}"]')
    return None if node is None else node.attributes.get("content")


def _analytics(tree: LexborHTMLParser) -> dict[str, str] | None:
    """The page's analytics block as a flat table, or None when the page is not a listing."""
    for node in tree.css("script"):
        text = node.text()
        if "prdref" in text:
            return dict(_PAIR.findall(text))
    return None


def _int(value: str | None) -> int | None:
    return int(value) if value and value.isdigit() else None


def _decimal(text: str) -> float | None:
    """`87,34 m²` -> 87.34, `1 200 m²` -> 1200.0."""
    found = _NUMBER.search(text)
    if found is None:
        return None
    return float(re.sub(r"\s", "", found.group()).replace(",", "."))


def _pretty(value: str | None) -> str | None:
    """`urban-immo` -> `Urban Immo`: the site stores slugs, the email shows names."""
    return value.replace("-", " ").title() if value else None


def _surface(tree: LexborHTMLParser, data: dict[str, str]) -> float | None:
    """The living space, from whichever of its two homes has it on this page.

    The analytics block writes it with a dash for a decimal separator (`105-3`), the same way it
    writes coordinates - and leaves it empty on some listings, which is why the body is read as
    well. In the body it is deliberately the span that says *Surface*, never the one that says
    *Terrain* or *Séjour*: reading a garden as living space would pass `surface_min` on land.
    """
    declared = data.get("surfaceBien")
    if declared:
        return _decimal(declared.replace("-", "."))
    for node in tree.css("span"):
        text = node.text(deep=False, strip=True)
        if text.startswith("Surface"):
            return _decimal(text)
    return None


def _from_slug(url: str) -> Listing | None:
    """The URL slug read as a partial listing, or None when it is not a listing URL at all.

    `annonce-vente-maison-t4-villers-sur-meuse-55220-7230-048927-180` gives away the transaction,
    the kind, the rooms, the town and the postcode - everything but the price and the surface.
    """
    tokens = urlsplit(url).path.strip("/").split("/")[-1].split("-")
    if len(tokens) < 4 or tokens[0] != "annonce" or tokens[1] not in _TRANSACTIONS:
        return None

    rooms: int | None = None
    postcode: str | None = None
    town: list[str] = []
    for token in tokens[3:]:
        found = _ROOMS.match(token)
        if rooms is None and found is not None:
            rooms = int(found.group(1))
        elif _POSTCODE.match(token):
            postcode = token
            break  # whatever follows the postcode is the agency's own reference
        else:
            town.append(token)

    return Listing(
        site=NAME,
        url=url,
        rooms=rooms,
        city="-".join(town) or None,
        postcode=postcode,
        transaction=_TRANSACTIONS[tokens[1]],
        kind=_KINDS.get(tokens[2], tokens[2]),
    )


class Orpi:
    """orpi.com. Inherits nothing: `Site` is a Protocol, and mypy checks the shape."""

    name = NAME
    base_url = BASE_URL

    def __init__(self, fetcher: Fetcher, search: Search) -> None:
        self.fetcher = fetcher
        self.search = search
        self.sitemap = SITEMAP

    def discover(self) -> Iterable[str]:
        body = self.fetcher.fetch(self.sitemap)
        if body is None:
            # Missing, or disallowed by robots.txt: we know nothing, which is not the same thing
            # as "nothing is for sale". Raising is what makes this an anomaly rather than 44,000
            # phantom removals (principle 6).
            raise FetchError(f"{self.sitemap}: no sitemap, so no listings could be discovered")
        # A flat <urlset>, with no lastmod anywhere - which is why newness comes from our database
        # and not from the site (principle 5). A <sitemapindex> would need one more hop; the day
        # an adapter meets one, it handles it there.
        root = ElementTree.fromstring(body)
        return [
            node.text.strip()
            for node in root.iter()
            if node.tag.rsplit("}", 1)[-1] == "loc" and node.text
        ]

    def prefilter(self, url: str) -> bool:
        """The search criteria, applied to what the URL alone gives away.

        Same filter, less information: `Search.matches` already treats an unknown field as no
        reason to reject, which is exactly the rule a prefilter needs.
        """
        partial = _from_slug(url)
        # A URL whose slug we cannot read gets downloaded. A page skipped in silence is the one
        # failure mode that leaves no trace anywhere.
        return True if partial is None else self.search.matches(partial)

    def parse(self, url: str, html: str) -> Listing | None:
        tree = LexborHTMLParser(html)
        data = _analytics(tree)
        if data is None or not data.get("prdref"):
            return None  # the generic page Orpi serves for a listing that is gone

        title = _meta(tree, "og:title")
        return Listing(
            site=self.name,
            url=url,
            ref=data["prdref"],
            title=" ".join(title.removesuffix("| Orpi").split()) if title else None,
            price=_int(data.get("prdamount")),
            surface=_surface(tree, data),
            rooms=_int(data.get("nbPieces")),
            city=_pretty(data.get("nomVille")),
            postcode=data.get("codePostal") or None,
            agency=_pretty(data.get("agenceNom")),
            photo_url=_meta(tree, "og:image"),
            transaction=_TRANSACTIONS.get(data.get("type_transaction", "")),
            kind=_KINDS.get(data.get("typeBien", ""), data.get("typeBien") or None),
        )
