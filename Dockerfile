# --- build stage: resolve and install dependencies with uv -------------------
FROM python:3.12-slim AS build

RUN pip install --no-cache-dir uv
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

# --- runtime stage ------------------------------------------------------------
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=build /app /app
ENV PATH="/app/.venv/bin:${PATH}"

# The repo to maintain is mounted at /workspace (see docker-compose.yml).
WORKDIR /workspace
EXPOSE 8000

ENTRYPOINT ["autodev"]
CMD ["loop", "--interval", "3600"]
