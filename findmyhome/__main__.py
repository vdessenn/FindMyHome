# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Victor DESSENNE
"""The command line — principle 7: identical by hand, from cron, from systemd or from a CI.

Everything comes from the configuration file and the environment; nothing from an absolute path
baked into the code.

The whole pipeline is run from here: the CLI is what owns the HTTP client and the database, so it
is what drives the loop. `collect` is a function of its own on purpose — a pipeline that can only
be exercised through argparse cannot be tested.

The order of the last three steps is the load-bearing one: diff, then **send**, then commit. A
listing recorded but never mailed is new exactly once and nobody ever saw it, so a delivery that
fails takes the whole run down with it and the next one reports the same news again.

Exit codes: 0 fine, 1 a site reported an anomaly or the digest could not be delivered, 2 the
configuration or the command line is wrong. An anomaly reaches the mailbox, and the exit code
carries it to the scheduler as well — the mail itself is the thing that may not have left.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from findmyhome import __version__
from findmyhome.config import Config, ConfigError, Search, load
from findmyhome.digest import DigestError, is_quiet, render, send
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


@contextmanager
def _database(path: Path, *, dry_run: bool) -> Iterator[Store]:
    """The database a run works on: the real file, or a throwaway copy when it is a dry run.

    Copying is what lets `--dry-run` show the very digest that would be sent — same code path,
    same diff — while leaving the real file untouched, down to its modification time.
    """
    if not dry_run:
        with Store(path) as store:
            yield store
        return
    with tempfile.TemporaryDirectory() as scratch:
        preview = Path(scratch) / "preview.db"
        if path.exists():
            shutil.copy2(path, preview)
        with Store(preview) as store:
            yield store


def _summarise(changes: Changes) -> bool:
    """One line per site on stdout, anomalies on stderr. True when the run must report failure."""
    print(
        f"{changes.site}: {len(changes.new)} new, {len(changes.price_changes)} price change(s), "
        f"{len(changes.removed)} removed"
    )
    if changes.anomaly is None:
        return False
    print(f"findmyhome: anomaly - {changes.anomaly}", file=sys.stderr)
    return True


def _run(
    config: Config,
    sites: tuple[str, ...],
    database: Path,
    *,
    dry_run: bool,
    fetcher: Fetcher,
) -> int:
    with _database(database, dry_run=dry_run) as store:
        runs: list[Changes] = []
        for name in sites:
            adapter = build(name, fetcher, config.search)
            if adapter is None:
                print(f"findmyhome: {name}: no adapter yet - skipped", file=sys.stderr)
                continue
            # Every network call happens here, before a single write: the transaction opened by
            # the first diff stays open until the digest has left, and has no reason to be long.
            listings, error = collect(adapter, fetcher, config.search, store.known_ids(name))
            runs.append(store.diff(name, listings, error=error, commit=False))

        failed = any([_summarise(changes) for changes in runs])
        mail = render(runs)

        if dry_run:
            print(f"\n{mail.subject}\n\n{mail.text}")
            return EXIT_FAILED if failed else EXIT_OK

        if is_quiet(runs) and not config.digest.send_when_empty:
            print("findmyhome: nothing to report, no digest sent")
        else:
            try:
                send(config.smtp, mail)
            except DigestError as error:
                print(f"findmyhome: {error}", file=sys.stderr)
                store.rollback()
                print(
                    "findmyhome: nothing was recorded, so the next run reports it again",
                    file=sys.stderr,
                )
                return EXIT_FAILED
            print(f"findmyhome: sent to {', '.join(config.smtp.recipients)} - {mail.subject}")
        store.commit()
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
