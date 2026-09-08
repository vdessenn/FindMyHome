# Contributing

Start with [ARCHITECTURE.md](ARCHITECTURE.md): it describes the pipeline, the adapter contract
and the seven principles that arbitrate the project's decisions. Adding a site should mean one
file in `sites/`, one entry in the config, and nothing else.

Run `make check` before opening a pull request — ruff, mypy `--strict` and pytest all have to
pass.

## Adapters and the crawling rules

Principle 4 is not negotiable: `robots.txt` obeyed, at most one request per second per domain,
an honest `User-Agent`, and no anti-bot circumvention of any kind. An adapter that works around
a site's stated rules will not be merged.

## Copyright assignment

FindMyHome is dual licensed: AGPL-3.0 for everyone, and a commercial licence for those who
cannot use it — see [LICENSING.md](LICENSING.md). Offering that second licence requires a single
copyright holder for the whole codebase.

So, by opening a pull request, you agree to assign the economic rights in your contribution to
Victor Dessenne, who will publish it under the AGPL along with the rest. Say so explicitly in the
pull request description:

> I assign the economic rights in this contribution to the maintainer, who may license it under
> the AGPL-3.0 and under separate commercial terms.

If you would rather not, that is a fair position — open an issue describing the change instead,
and it can be reimplemented independently.
