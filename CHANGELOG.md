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
- CLI skeleton (`findmyhome --version`), used as a load test for the tooling.
- `findmyhome/fetch.py`: polite HTTP client — `robots.txt` obeyed, one request per second per
  domain, honest `User-Agent`, retry on server errors. A failure is reported (`FetchError`) and
  can never pass for a missing page.
- On-disk HTTP cache, off by default, with readably named entries: develop an adapter without
  re-downloading, and use the entries as the source for test fixtures.

### Changed

- Documentation split by reader: `README.md` for whoever uses the tool, `ARCHITECTURE.md` for
  whoever writes an adapter. Everything published is now in English.

### Removed

- `GUIDELINE.md`, whose content moved into `README.md` and `ARCHITECTURE.md`.

## [0.1.0]

Initial version: tooling only, pipeline not implemented.
