# FindMyHome

One digest email of the property listings matching your criteria, aggregated from the websites of
small estate agencies, instead of manually doing the rounds of a dozen different interfaces.

The email only contains what moved: **new listings, price drops, price rises, removals**.
The goal is to stop opening any site at all until an email flags something.

> **Status: it works end to end**, for one site (Orpi) so far. `findmyhome run` reads the sitemap,
> downloads the listings that can match, stores them and emails what moved. What is left is more
> adapters — the second one is what will prove the design. The design itself — principles,
> pipeline, adapter contract, data model — lives in [ARCHITECTURE.md](ARCHITECTURE.md).

## How it behaves

Seven principles arbitrate the project's decisions ([all seven](ARCHITECTURE.md#principles)).
Three of them are visible in daily use:

- **Polite by default** — `robots.txt` obeyed, one request per second per domain, honest
  `User-Agent`. No anti-bot circumvention, ever.
- **Sitemaps, not search pages** — several sites disallow their search endpoints, so adapters
  enter through the sitemap.
- **A broken scraper never looks like an empty market** — zero listings after N on the previous
  run is reported as an anomaly, not treated as removals.

## Installation

No installation at all, if you have [uv](https://docs.astral.sh/uv/):

```bash
uvx --from git+https://github.com/vdessenn/FindMyHome findmyhome --version
```

Standalone binary (no Python required): see the artefacts produced by `make binary`, or
[the releases](https://github.com/vdessenn/FindMyHome/releases) once there are any.

Docker image, the production channel:

```bash
docker build -t findmyhome:latest .
docker run --rm \
  -v /srv/findmyhome:/data \
  -e FINDMYHOME_SMTP_PASSWORD \
  findmyhome:latest run
```

## Configuration

```bash
cp config.example.toml config.toml   # git-ignored
```

Search criteria, enabled sites and SMTP settings live in `config.toml`;
[`config.example.toml`](config.example.toml) documents every key with neutral values.

**The SMTP password never appears in it**: it comes from the `FINDMYHOME_SMTP_PASSWORD`
environment variable (see `.env.example`). The repository is public — no secret is ever
committed.

How often it runs is not part of the configuration: that belongs to the scheduler (cron, systemd,
a Docker timer). The program behaves identically started by hand or by a machine.

## Scope

**In**: one complete adapter, the whole pipeline, SQLite, an HTML email with photo previews,
`--dry-run`, and a documented example configuration.

**Out, and why**:

- Headless browser → no site has been confirmed as requiring JavaScript. To be added the day an
  adapter needs it, behind the same `Site` contract.
- Scoring and keyword exclusions → hard filters first; we will see what the real noise looks like.
- Multiple searches, web UI, push notifications → not asked for.
- Downloading photos → the email points at the site's images, no attachments.

## Contributing

The pipeline, the adapter contract and the data model are described in
[ARCHITECTURE.md](ARCHITECTURE.md). Adding a site should mean one file in `sites/`, one entry in
the config, and nothing else.

## License

MIT — see [LICENSE](LICENSE).
