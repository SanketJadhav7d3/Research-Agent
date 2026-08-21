FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.2 /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

ENV PATH="/app/.venv/bin:$PATH"

# Executed code runs as this user, not root. It owns nothing: /app is root's,
# and the only writable paths are the tmpfs mounts declared at deploy time.
RUN useradd --create-home --shell /usr/sbin/nologin --uid 10001 runner \
    && mkdir -p /data \
    && chown runner:runner /data

USER runner

EXPOSE 8080
# Shell form so $PORT expands. Cloud Run injects it and expects the container
# to listen there; a hardcoded port works only while the two happen to agree.
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
