FROM node:24-slim AS asset-builder
WORKDIR /app
COPY package.json package-lock.json style.config.js* postcss.config.js style.css ./
COPY src/webapp/static/js/ ./src/webapp/static/js/
RUN npm ci \
    && mkdir -p src/webapp/static/css/ \
    && npm run build

FROM ghcr.io/astral-sh/uv:0.13 AS uv-stage
FROM python:3.15-slim AS builder

RUN apt-get update && apt-get install -y --no-install-suggests --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv-stage /uv /usr/local/bin/uv
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ src/
COPY app.py README.md ./

COPY --from=asset-builder /app/src/webapp/static/css/style.min.css ./src/webapp/static/css/style.min.css
COPY --from=asset-builder /app/src/webapp/static/js/*.min.js ./src/webapp/static/js/

RUN uv sync --frozen --no-dev


FROM python:3.15-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY --from=builder /app/app.py /app/app.py

RUN useradd --system --create-home --uid 1001 appuser
USER appuser

ENV PATH="/app/.venv/bin:$PATH"
ENV PORT=8000
EXPOSE ${PORT}

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://localhost:${PORT}/api/health').status == 200 else 1)"

CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT} --timeout 120 --graceful-timeout 30 --preload --workers ${WEB_CONCURRENCY:-2} app:app"]
