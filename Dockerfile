FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    OPPORTUNITY_RADAR_HOME=/app

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN uv sync --frozen --no-dev

VOLUME ["/app/data", "/app/config"]

# Default: the long-running daemon. Override for one-shot commands, e.g.:
#   docker compose run radar uv run opportunity-radar scan
CMD ["uv", "run", "opportunity-radar", "daemon"]
