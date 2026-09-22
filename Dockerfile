# syntax=docker/dockerfile:1

# --- Builder: resolve the package into a self-contained virtualenv ----------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN python -m venv /opt/venv

# Only what the build needs (see .dockerignore for the rest).
COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN /opt/venv/bin/pip install --quiet --upgrade pip \
    && /opt/venv/bin/pip install --quiet .

# --- Runtime ----------------------------------------------------------------
FROM python:3.12-slim AS runtime

RUN groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid app --create-home app

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    YNAB_MCP_HOST=0.0.0.0 \
    YNAB_MCP_PORT=8000

# Build stamp for traceability (set by CI build args).
ARG BUILD_COMMIT=unknown
ARG BUILD_TIME=unknown
ARG BUILD_TAG=unknown
ENV YNAB_BUILD_COMMIT=${BUILD_COMMIT} \
    YNAB_BUILD_TIME=${BUILD_TIME} \
    YNAB_BUILD_TAG=${BUILD_TAG}

COPY --from=builder --chown=app:app /opt/venv /opt/venv

USER app
WORKDIR /app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, sys, urllib.request; url = 'http://127.0.0.1:' + os.environ.get('YNAB_MCP_PORT', '8000') + '/healthz'; sys.exit(0 if urllib.request.urlopen(url, timeout=4).status == 200 else 1)"

CMD ["ynab-mcp-lite", "serve", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8000"]
