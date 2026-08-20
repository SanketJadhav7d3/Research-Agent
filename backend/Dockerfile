FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy the uv binary from its official image — no pip, no root-install warning.
# Pinned to match the version used locally to generate uv.lock.
COPY --from=ghcr.io/astral-sh/uv:0.11.2 /uv /usr/local/bin/uv

# Dependency layer: cached until pyproject/lockfile actually change.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8080
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8080"]
