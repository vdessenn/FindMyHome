# HTML fixtures

Real pages, captured so that `parse` tests run offline and do not depend on the availability —
or the patience — of the sites.

## Capturing a page

The development HTTP cache names its entries readably, so it doubles as the source:

```python
from findmyhome.fetch import Fetcher

with Fetcher(cache_dir=".cache/http") as f:
    f.fetch("https://www.example-agency.com/listing-house-...")
```

```bash
ls .cache/http/                       # spot the page by eye
cp .cache/http/<file>.html tests/fixtures/agency-house-4br.html
```

## Two rules

- **Prune before committing.** The repository is public: keep the HTML fragment the test needs,
  not a full agency page with its scripts and ad networks.
- **Name by site and by case** (`agency-house-4br.html`, `agency-no-price.html`), so a failing
  test points straight at what changed and where.
