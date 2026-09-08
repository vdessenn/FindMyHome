# Production channel: multi-stage image, pinned Python runtime.
# The container is ignorant of its scheduler - cron/systemd runs `docker run` (principle 7).
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY findmyhome/ findmyhome/

# --no-editable: the package is copied into the venv, so the final stage needs no sources.
RUN uv sync --frozen --no-dev --no-editable


FROM python:3.13-slim-bookworm

LABEL org.opencontainers.image.title="findmyhome" \
      org.opencontainers.image.source="https://github.com/vdessenn/FindMyHome" \
      org.opencontainers.image.licenses="AGPL-3.0-only"

COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# SQLite database and configuration are mounted from the host; the SMTP secret comes from
# FINDMYHOME_SMTP_PASSWORD, never from the image.
RUN useradd --create-home --uid 1000 findmyhome && mkdir -p /data && chown findmyhome /data
USER findmyhome
WORKDIR /data
VOLUME ["/data"]

ENTRYPOINT ["findmyhome"]
CMD ["run"]
