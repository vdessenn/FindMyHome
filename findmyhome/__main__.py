"""The command line — principle 7: identical by hand, from cron, from systemd or from a CI.

Everything comes from the configuration file and the environment; nothing from an absolute path
baked into the code.

Stages 1 to 6 of the pipeline are run from here: the CLI is what owns the HTTP client and the
database, so it is what drives the loop. `collect` is a function of its own on purpose — a
pipeline that can only be exercised through argparse cannot be tested. It moves to a module of its
own the day `digest.py` needs to call it without a command line.

Exit codes: 0 fine, 1 a site reported an anomaly, 2 the configuration or the command line is
wrong. An anomaly has to reach the scheduler somehow, and until the digest exists the exit code is
the only channel there is — a cron that stays quiet about a broken scraper would undo principle 6.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from findmyhome import __version__
from findmyhome.config import Config, ConfigError, Search, load
from findmyhome.fetch import Fetcher, FetchError
from findmyhome.listing import Listing
from findmyhome.sites.base import SITES, Site, build
from findmyhome.store import Changes, Store

DEFAULT_CONFIG = Path("config.toml")

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_INVALID = 2


def collect(
    adapter: Site,
    fetcher: Fetcher,
    search: Search,
    known: set[str],
) -> tuple[list[Listing], str | None]:
    """Pipeline stages 1 to 5: discover, prefilter, fetch, parse, filter.

    Returns what was retained *and* the breakage met on the way — both, never one instead of the
    other: listings seen before a failure are still listings we saw, and the store records them
    while computing no removal at all.
    """
    listings: list[Listing] = []
    try:
        for url in adapter.discover():
            if not adapter.prefilter(url):
                continue
            html = fetcher.fetch(url)
            if html is None:
                continue  # 404, gone, or disallowed by robots.txt: an answer, not a failure
            listing = adapter.parse(url, html)
            if listing is None:
                continue
            # Stage 5 applies to unknown listings only. A listing whose price rose past price_max
            # still has to be reported as a rise; dropping it here would report it as removed.
            if listing.id in known or search.matches(listing):
                listings.append(listing)
    except FetchError as error:
        return listings, str(error)
    except Exception as error:
        # An adapter that raises is an adapter that no longer understands the page, and principle
        # 6 covers HTML structure changes explicitly. Catching narrowly would mean guessing which
        # exceptions a parser can raise; letting it through would sink every other site with it.
        # ponytail: the first failure stops this site, whatever it was. No tolerance threshold
        # until real data says what a normal rate of unparseable pages looks like.
        return listings, f"{type(error).__name__}: {error}"
    return listings, None


def _describe(listing: Listing) -> str:
    price = f"{listing.price} EUR" if listing.price is not None else "price unknown"
    surface = f"{listing.surface:g} m2" if listing.surface is not None else "? m2"
    rooms = f"{listing.rooms} rooms" if listing.rooms is not None else "? rooms"
    return f"{price}  {surface}  {rooms}  {listing.city or '?'}  {listing.url}"


def _anomaly(message: str) -> bool:
    print(f"findmyhome: anomaly - {message}", file=sys.stderr)
    return True


def _record(store: Store, site: str, listings: Sequence[Listing], error: str | None) -> bool:
    changes: Changes = store.diff(site, listings, error=error)
    print(
        f"{site}: {len(changes.new)} new, {len(changes.price_changes)} price change(s), "
        f"{len(changes.removed)} removed"
    )
    return False if changes.anomaly is None else _anomaly(changes.anomaly)


def _preview(site: str, listings: Sequence[Listing], error: str | None, *, known: bool) -> bool:
    """`--dry-run`: show the extracted fields, which is the only way to eyeball an adapter."""
    print(f"{site}: {len(listings)} listing(s) retained, nothing written")
    if not known:
        print(f"{site}: no database yet, so nothing here is known to be new")
    for listing in listings:
        print(f"  {listing.id}  {_describe(listing)}")
    return False if error is None else _anomaly(f"{site}: {error}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="findmyhome",
        description="Aggregates property listings and delivers them by email.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="Run the pipeline for the enabled sites.")
    run.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Configuration file.")
    run.add_argument("--db", type=Path, help="Database path, overriding the configuration.")
    run.add_argument("--dry-run", action="store_true", help="Write nothing, send nothing.")
    run.add_argument("--site", help="Restrict the run to one of the enabled sites.")

    sites = sub.add_parser("list-sites", help="List the sites enabled in the configuration.")
    sites.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Configuration file.")

    return parser


def _enabled(config: Config, only: str | None) -> tuple[str, ...] | None:
    """The sites to run, or None if `--site` names one the configuration does not enable."""
    if only is None:
        return config.sites
    return (only,) if only in config.sites else None


def _run(
    config: Config,
    sites: tuple[str, ...],
    database: Path,
    *,
    dry_run: bool,
    fetcher: Fetcher,
) -> int:
    # A dry run never creates the database, and reads an existing one read-only: "write nothing"
    # is a claim the file system gets to enforce rather than a comment.
    store: Store | None = None
    if not dry_run:
        store = Store(database)
    elif database.exists():
        store = Store(database, create=False)

    failed = False
    try:
        for name in sites:
            adapter = build(name, fetcher, config.search)
            if adapter is None:
                print(f"findmyhome: {name}: no adapter yet - skipped", file=sys.stderr)
                continue
            known = store.known_ids(name) if store is not None else set()
            listings, error = collect(adapter, fetcher, config.search, known)
            if dry_run or store is None:
                failed = _preview(name, listings, error, known=store is not None) or failed
            else:
                failed = _record(store, name, listings, error) or failed
    finally:
        if store is not None:
            store.close()
    return EXIT_FAILED if failed else EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return EXIT_INVALID

    try:
        config = load(args.config)
    except ConfigError as error:
        print(f"findmyhome: {error}", file=sys.stderr)
        return EXIT_INVALID

    if args.command == "list-sites":
        for site in config.sites:
            print(f"{site}\t{'ready' if site in SITES else '(no adapter yet)'}")
        return EXIT_OK

    sites = _enabled(config, args.site)
    if sites is None:
        print(
            f"findmyhome: site {args.site!r} is not in [sites] enabled "
            f"({', '.join(config.sites) or 'none'})",
            file=sys.stderr,
        )
        return EXIT_INVALID

    with Fetcher() as fetcher:
        return _run(
            config,
            sites,
            args.db or config.storage.database,
            dry_run=args.dry_run,
            fetcher=fetcher,
        )


if __name__ == "__main__":
    raise SystemExit(main())
