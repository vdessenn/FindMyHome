"""Throwaway skeleton — a load test for the tooling, not the start of the CLI.

This module exists to give uv, ruff, mypy, pytest, PyInstaller and Docker something to bite on
before there is any business logic. It is replaced wholesale by step 2 of the roadmap
(`listing.py`, `config.py`, `store.py`).
"""

from __future__ import annotations

import argparse

from findmyhome import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="findmyhome",
        description="Aggregates property listings and delivers them by email.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run", help="Run the full pipeline (not implemented).")
    run.add_argument("--dry-run", action="store_true", help="Write nothing, send nothing.")

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 2

    print("findmyhome: skeleton — the pipeline is not implemented yet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
