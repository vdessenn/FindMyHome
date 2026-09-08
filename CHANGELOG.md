# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning: [SemVer](https://semver.org/).

## [Unreleased]

### Added

- Project foundations: `pyproject.toml` (uv, `uv_build` backend, flat layout), `uv.lock` under
  version control, Python pinned to 3.13 for development.
- Quality tooling: ruff (lint + format), mypy `--strict`, pytest, `pre-commit` with secret
  detection (gitleaks), and `Makefile` as the single entry point.
- Three distribution channels: wheel, Docker image, standalone PyInstaller binary
  (Linux x86_64).
- Command line: `findmyhome run [--config] [--db] [--dry-run] [--site]` and `list-sites`.
  Everything comes from the configuration file, nothing from a path baked into the code
  (principle 7). Exit codes: 0 fine, 1 the run failed, 2 the configuration is wrong.
- `findmyhome/fetch.py`: polite HTTP client — `robots.txt` obeyed, one request per second per
  domain, honest `User-Agent`, retry on server errors. A failure is reported (`FetchError`) and
  can never pass for a missing page.
- On-disk HTTP cache, off by default, with readably named entries: develop an adapter without
  re-downloading, and use the entries as the source for test fixtures.
- `findmyhome/listing.py`: the `Listing` dataclass and the identity principle 5 rests on —
  `site:ref`, or the canonical URL when the site exposes no reference.
- `findmyhome/config.py`: TOML loading with strict validation. Every problem is reported at once,
  and an unknown key is an error rather than a silently ignored one. The search criteria live
  here too: an unknown field never rejects a listing, and the location matches on the postcode or
  the city.
- `findmyhome/store.py`: SQLite storage — one transaction per site run, price history, removals,
  and the principle 6 guard rail. Zero listings after a non-empty run reports an anomaly and
  marks nothing as removed; the comparison reads the last run that did not fail.
- A listing already in the database keeps being tracked even when it no longer matches the
  criteria, so a price rise past `price_max` is reported as a rise and not as a removal.
- `findmyhome/sites/base.py`: the adapter contract as a `Protocol` and the site registry. An
  adapter inherits nothing — mypy `--strict` checks its shape against the registry, so principle 1
  is enforced before runtime rather than during it. A configured site with no adapter is named on
  stderr and skipped, never fatal.
- The pipeline itself: `run` walks discover → prefilter → fetch → parse → filter → diff for every
  enabled site, and prints what moved. A listing already in the database skips the filter, so a
  price rise past `price_max` is reported as a rise.
- A site ending its run on an anomaly makes `run` exit 1: until the digest exists, the exit code
  is the only way a scheduler can hear about a broken scraper.
- `run --dry-run` now collects for real and prints the extracted fields, so an adapter can be
  eyeballed. It opens an existing database read-only and never creates one.
- `[storage] database` configuration key, relative by default so the Docker image's `/data`
  working directory is enough to place it.

### Changed

- Documentation split by reader: `README.md` for whoever uses the tool, `ARCHITECTURE.md` for
  whoever writes an adapter. Everything published is now in English.

### Removed

- `GUIDELINE.md`, whose content moved into `README.md` and `ARCHITECTURE.md`.

## [0.1.0]

Initial version: tooling only, pipeline not implemented.
