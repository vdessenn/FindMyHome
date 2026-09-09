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
- `findmyhome healthcheck [--max-age HOURS]`: principle 6 applied to the scheduler. Inside a run
  a broken scraper reports an anomaly; around one, `send_when_empty = false` made a stopped cron
  indistinguishable from a quiet market. The command exits 1 when an enabled site is stale, failed
  or was never collected, reporting on the exit code so it still works when SMTP is the failure.
  It refuses to create a missing database rather than hide the outage behind empty tables.
- `Store.last_run(site)`: the most recent run for a site, error included — public counterpart of
  the successful-run lookup the principle 6 guard rail already used.
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
- `findmyhome/digest.py`: the email. One digest for every enabled site, as HTML with a plain-text
  alternative, sections for new listings, price drops, price rises, removals and anomalies.
  Nothing moved means no email — but an anomaly is always worth one, even when the market is calm.
- The digest is **sent before the run is committed**: a delivery that fails rolls the database
  back, so the news is reported again next time instead of being new to nobody.
- `run --dry-run` prints the very digest it would have sent, computed on a throwaway copy of the
  database. The real file is never opened for writing, not even to create it.
- `findmyhome/sites/orpi.py`: the first adapter. It enters through the sitemap (principle 3),
  reads the transaction, kind, rooms, town and postcode off the URL slug to avoid downloading
  what cannot match, and extracts the fields from the page. A listing that no longer exists is
  answered with a generic page rather than a 404, so the parser reports it as gone rather than
  trusting the status code; a sitemap it cannot read is an anomaly, never an empty market.
- Cities are now compared without case, accents or separators: sites publish them as URL slugs,
  where `Rezé` is written `reze` and `Saint-Nazaire` either way. A criterion that silently
  matched nothing was the worse failure.
- `[storage] database` configuration key, relative by default so the Docker image's `/data`
  working directory is enough to place it.

### Changed

- Documentation split by reader: `README.md` for whoever uses the tool, `ARCHITECTURE.md` for
  whoever writes an adapter. Everything published is now in English.
- **Licence: MIT to `AGPL-3.0-only`** (2026-09-08). The project is meant to be offered as a
  service one day, and the AGPL is the only licence whose section 13 stops a third party from
  running a closed fork as a competing service. Dual licensing is documented in `LICENSING.md`,
  and `CONTRIBUTING.md` now asks contributors for the copyright assignment it depends on.
  Commits up to `b5c3a1a` stay MIT for whoever already holds them — the change is prospective.
- `findmyhome/sites/orpi.py` parses through selectolax's lexbor backend (Apache-2.0) instead of
  Modest (LGPL-2.1): identical API, and no relink obligation on the standalone binary.
- `findmyhome/sites/base.py` merges an optional `findmyhome_local` package into the registry,
  so private adapters can be added without touching this repository.

### Removed

- `GUIDELINE.md`, whose content moved into `README.md` and `ARCHITECTURE.md`.

## [0.1.0]

Initial version: tooling only, pipeline not implemented.
