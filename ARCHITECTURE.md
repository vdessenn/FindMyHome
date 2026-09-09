# Architecture

How FindMyHome is put together, and what you need to know to write an adapter.
For installation and configuration, see [README.md](README.md).

## Principles

Seven principles arbitrate the project's decisions. When in doubt, come back here.

1. **The cost of adding a site is the project's metric.**
   Adding a site means one file in `sites/`, one entry in the config, and zero changes anywhere
   else. If a change forces you to touch several adapters, the logic sits in the wrong place:
   it belongs in the core.

2. **Adapters do not filter, do not store, do not send.**
   An adapter discovers candidate URLs and extracts fields. Filtering by criteria, deduplication,
   history and email live in exactly one place — the core. That is what lets principle 1 hold.

3. **Sitemaps before search pages.**
   Several agency sites disallow their search endpoints in `robots.txt` while publishing a
   sitemap that is regenerated daily and allowing listing pages. An adapter therefore starts
   from the sitemap. No usable sitemap means the adapter documents the case and handles it
   explicitly — it never works around the rule.

4. **Polite by default, never work around.**
   `robots.txt` obeyed (`urllib.robotparser`, stdlib), at most one request per second per domain,
   an honest `User-Agent` pointing at this repository, and a slug prefilter so only the necessary
   pages are downloaded. No anti-bot circumvention, no forged authentication. A public project
   that hits hard gets banned and exposes its author.

5. **Newness comes from our state, not from the site.**
   Sitemaps expose no per-listing `lastmod`, and agency references are unstable. "New" therefore
   means "absent from our database". SQLite is the backbone of the system, not a cache.

6. **A broken scraper must never look like an empty market.**
   If an adapter that returned N > 0 listings on the previous run returns 0, nothing is marked as
   removed: an anomaly is reported. The rule also covers HTTP errors and HTML structure changes.
   Silence is a bug, not information.

7. **The core is a command-line executable, ignorant of its scheduler.**
   `python -m findmyhome run` must behave identically whether it is started by hand, by cron, by
   systemd or by a CI. No dependency on an absolute path or a particular environment: everything
   comes from the config and from environment variables.

## The pipeline

```
config.toml
    │
    ▼
[1] discover      each adapter reads the site's sitemap → candidate URLs
    │
    ▼
[2] prefilter     filters on the URL slug (transaction, kind, rooms, city/postcode)
    │             ← avoids 95 % of the downloads
    ▼
[3] fetch         polite HTTP: robots.txt, rate limit, timeout, retry
    │
    ▼
[4] parse         adapter → Listing (price, surface, rooms, agency, photo, ref)
    │
    ▼
[5] filter        hard criteria on the real fields (exact price, exact surface)
    │             ← unknown listings only, see below
    ▼
[6] diff          compared against SQLite → new / price drops / price rises / removals
    │
    ▼
[7] digest        HTML rendering + SMTP send (nothing to send → no email)
                  ← sent before the run is committed, see Data model
```

Every stage is a pure function except `fetch` (network), `diff` (database read/write) and
`digest` (send). Stages 1 and 4 are the only ones that know about sites.

**A listing we already know is never filtered out.** The prefilter reads the slug, which does
not encode the price: a listing whose price rises past `price_max` is still discovered and still
downloaded, but it fails stage 5. Dropping it there would report a price rise as a removal — the
two things the digest exists to tell apart. Stage 5 therefore applies to unknown listings only:

```python
if listing.id in store.known_ids(site) or search.matches(listing):
```

"Removed" then means exactly one thing: gone from the site.

**Key discovery**: listing slugs already encode the criteria — for example
`annonce-vente-maison-t4-villers-sur-meuse-55220-…`. Stage 2 exploits this to download a handful
of pages out of a sitemap that holds tens of thousands: on the first live run, 14 URLs out of
44,722. The prefilter is the same `Search.matches` as stage 5, applied to what the URL gives away
— an unknown field never rejects, so nothing is skipped in silence.

## The adapter contract

This is the interface that must stay stable for as long as possible.

```python
# findmyhome/sites/base.py
class Site(Protocol):
    name: str            # "orpi"
    base_url: str

    def discover(self) -> Iterable[str]:
        """Candidate listing URLs, from the site's sitemap(s)."""

    def prefilter(self, url: str) -> bool:
        """True if the URL slug is compatible with the search criteria. Defaults to True."""

    def parse(self, url: str, html: str) -> Listing | None:
        """Extract the fields. None if the page is not (or no longer) a valid listing."""
```

**What counts as a breakage.** A `FetchError` or an adapter raising stops that site's collection
and is passed to `diff` as an error: principle 6 then reports an anomaly and marks nothing as
removed, while the listings seen before the failure are still recorded. A page that answers 404,
one `robots.txt` disallows, and a `parse` returning `None` are answers rather than failures — they
are skipped in silence. An adapter that raises is one that no longer understands the page, which
is the HTML structure change principle 6 names.

`Listing` is a frozen dataclass: `site`, `url`, `ref`, `title`, `price`, `surface`, `rooms`,
`city`, `postcode`, `agency`, `photo_url`, `transaction` (`sale`/`rent`), `kind`
(`house`/`flat`/…). Unknown fields are `None` — an incomplete adapter is still useful.

**Listing identity** (the deduplication key, principle 5):
`site:ref` when the site exposes a reference, `site:canonical-url` otherwise — query string and
fragment stripped, host lowercased, trailing slash dropped. The site prefixes both variants: two
agencies numbering their listings from 1 must not collide. Changing this rule does not migrate
the database, it resets it: every listing would come back as new.

A secondary fingerprint `(postcode, surface, rooms, price)` is meant to detect republications
under a new URL and merely report them in the email. It is **not implemented yet**: the digest
that would carry it now exists, so what it still waits for is a run of real history to measure its
false positives against — two houses of the same size at the same price in the same town are not a
republication, and only data says how often that happens.

## Data model

```sql
listing(id TEXT PRIMARY KEY,   -- the identity above
        site, url, ref, title, price, surface, rooms, city, postcode,
        agency, photo_url, transaction, kind,
        first_seen, last_seen, active INTEGER)

price_change(listing_id, seen_at, old_price, new_price)

site_run(site, ran_at, found_count, error)
```

`ref` is stored even though the identity already encodes it: a removed listing is read back from
its row to be displayed in the email, and a `Listing` that cannot be rebuilt exactly would not
compute the same identity.

**Recorded last, on purpose.** A run diffs, *then* sends, *then* commits. A listing written to the
database is new exactly once (principle 5), so one stored before a delivery that fails would be new
to nobody: the send therefore happens inside the transaction, and a `DigestError` rolls the whole
run back for the next one to report again. A duplicate email is the failure this trades for, and it
is the cheaper one by far.

`site_run` is what arms principle 6: comparing against the previous `found_count` is what tells a
quiet market apart from a broken scraper. The comparison reads the last run **with no error** —
a run that failed at zero listings must not become the reference that disarms the guard rail.
`PRAGMA user_version` carries the schema version; there is no migration machinery until a schema
actually changes.

## Dependencies

Two, deliberately.

| Need | Choice | Why not more |
|---|---|---|
| HTTP | `httpx` | correct timeouts, retries and gzip without rewriting `urllib` |
| HTML parsing | `selectolax` | CSS selectors, very fast, no `lxml` to compile |
| Config | `tomllib` | **stdlib** |
| Database | `sqlite3` | **stdlib** |
| Email | `smtplib` + `email.message` | **stdlib** |
| Templating | f-strings | a single ~50-line template — Jinja2 unjustified, under the condition below |
| robots.txt | `urllib.robotparser` | **stdlib** |

**When Jinja2 gets reconsidered.** The titles, agencies and cities injected into the email come
from scraped HTML. Jinja2 escapes automatically; with f-strings you have to call `html.escape()`
(stdlib) on *every* field, with no safety net.

The rule used to be "if `digest.py` grows past a hundred lines". `digest.py` is past it — and
roughly half of it is SMTP delivery, which a template engine would not shorten by one line. The
condition is therefore what it was always aiming at: **the rendering**. It stands as long as the
markup stays under about fifty lines *and* every scraped value keeps reaching the HTML through a
single escaping function, so that an escape cannot be remembered in one branch and forgotten in
another. The day either half stops holding — a second template, a field interpolated directly —
Jinja2 is the right choice and the dependency is worth it.

## Source tree

```
findmyhome/
    __main__.py      # CLI: run, --dry-run, --site, list-sites, healthcheck
    config.py        # TOML loading + validation
    listing.py       # Listing dataclass + identity computation
    fetch.py         # polite HTTP: robots, rate limit, retry
    store.py         # SQLite: upsert, diff, price history
    digest.py        # HTML rendering + SMTP send
    sites/
        base.py      # Site Protocol + registry + private overlay
        orpi.py
findmyhome_local/    # optional, git-ignored: private adapters (see below)
config.example.toml
tests/test_store.py
tests/test_orpi.py
tests/fixtures/      # pruned real pages, offline tests
```

Deliberately flat: six modules, no extra abstraction layer until a second use case demands one.

Every module of that tree now exists; `sites/` holds one adapter, and a second one is what will
prove principle 1.

`findmyhome_local` is the one part of the tree this repository does not contain. Adapters for
small agencies are the maintainer's own research and live in a separate private repository, so
`base.py` merges that package into `SITES` when it happens to be importable and carries on
without it when it is not. Nothing else in the codebase knows the difference: a private adapter
honours the same `Site` contract and goes through the same pipeline. The registry catches only
`ModuleNotFoundError` naming `findmyhome_local` itself - an overlay that is present but fails to
import is raised, not swallowed, because principle 6 applies to our own code too.

The tests are `test_smoke`, `test_fetch`, `test_listing`, `test_config`, `test_search`,
`test_store`, `test_sites`, `test_pipeline`, `test_orpi` and `test_digest`.

## Development

```bash
uv sync                  # environment from uv.lock
uvx pre-commit install   # git hooks (ruff, file hygiene, secret detection)
make check               # lint + types + tests (3.13 and 3.11)
make help                # every target
```

`make check` is what must be green before committing; `make coverage` produces an informative
report that never blocks.

The type checker is not a comfort: the `Site` contract is a `Protocol`, and mypy verifies that a
new adapter honours it **before** runtime — principle 1, tooled. `pre-commit` carries ruff, file
hygiene and **gitleaks**: the repository is public and the project handles an SMTP password;
`.gitignore` protects `config.toml`, it does not protect against a secret pasted into a `.py`.
`requires-python` declares 3.11+ and `make check` actually verifies it by replaying the tests on
3.11.

### Writing an adapter without hammering sites

The HTTP client can cache its responses on disk. The cache is off by default — it is a
development tool, not a production optimisation. Cache entries are named readably, so a page can
be copied straight into `tests/fixtures/` with no tooling.

See [tests/fixtures/README.md](tests/fixtures/README.md) for how to capture a page and turn it
into a fixture. `make cache-clear` empties the cache; `make clean` deliberately leaves it alone.

## Packaging and distribution

Three channels, three distinct audiences.

| Channel | Audience | Cost | Requires |
|---|---|---|---|
| Wheel + `uvx --from git+…` | developer, repository visitor | none — falls out of `pyproject.toml` | `uv` |
| Docker image | **self-hosted production** | one `Dockerfile` | Docker |
| PyInstaller binary | machine with neither Python nor uv | one spec, **one runner per OS** | nothing |

| Target | Command | Note |
|---|---|---|
| Wheel + sdist | `make build` | feeds the other two |
| Docker image | `make image` | production channel |
| Standalone binary | `make binary` | **does not cross-compile**: one machine per OS |

Docker stays the production channel: it pins the runtime, exposes a volume for the database and
reads the secret from the environment — `docker run` behaves identically by hand or from cron
(principle 7). PyInstaller does not cross-compile: only Linux x86_64 is producible until there is
a CI, and an unsigned binary gets blocked by SmartScreen and Gatekeeper. The spec file is
versioned anyway, so that adding a multi-OS matrix is only ever a CI file.

`make` is the single entry point, written so that a CI can call `make check` without reinventing
anything.

## Releasing

```bash
uv version --bump patch                        # pyproject.toml + uv.lock
$EDITOR CHANGELOG.md                           # move "Unreleased" to the version
git commit -am "chore: release v$(uv version --short)"
git tag "v$(uv version --short)"
```

The version is **static** in `pyproject.toml`, moved by `uv version --bump`, and read at runtime
through `importlib.metadata`. It is deliberately not derived from git tags: that would evaporate
inside the frozen binary, where there is no repository left.
