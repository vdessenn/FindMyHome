"""The command line — principle 7: identical by hand, from cron, from systemd or from a CI.

Everything comes from the configuration file and the environment; nothing from an absolute path
baked into the code. The pipeline itself does not exist yet: `run` loads the configuration and
opens the database, and says so rather than pretending to collect anything.

Exit codes: 0 fine, 1 the run failed, 2 the configuration or the command line is wrong.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from findmyhome import __version__
from findmyhome.config import Config, ConfigError, load
from findmyhome.store import Store

DEFAULT_CONFIG = Path("config.toml")

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_INVALID = 2


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


def _run(*, sites: tuple[str, ...], database: Path, dry_run: bool) -> int:
    # No adapter exists yet, so there is nothing to discover, fetch or parse. Saying it is the
    # honest thing; the pipeline lands here with the first adapter.
    if dry_run:
        print(f"findmyhome: configuration is valid, {len(sites)} site(s) enabled.")
        print("findmyhome: --dry-run, so nothing was written - no adapter is available yet.")
        return EXIT_OK

    with Store(database):
        pass  # opening is what creates the schema; the pipeline lands here with the adapters
    print(f"findmyhome: database ready at {database}.")
    print(f"findmyhome: no adapter is available yet, so none of {len(sites)} site(s) ran.")
    return EXIT_OK


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
            print(f"{site}\t(no adapter yet)")
        return EXIT_OK

    sites = _enabled(config, args.site)
    if sites is None:
        print(
            f"findmyhome: site {args.site!r} is not in [sites] enabled "
            f"({', '.join(config.sites) or 'none'})",
            file=sys.stderr,
        )
        return EXIT_INVALID

    return _run(
        sites=sites,
        database=args.db or config.storage.database,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
