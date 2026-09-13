# syntax=docker/dockerfile:1
# API image (ADR 0023). DEPLOYMENT_MODE is baked at image build time and is
# immutable for the container's lifetime — on-prem default; cloud images:
#   docker build --build-arg DEPLOYMENT_MODE=cloud -t unhinted-api:cloud .

FROM python:3.12-slim AS build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Deps without cp312 wheels compile here (PyStemmer via semantic-router) —
# the toolchain stays out of the runtime image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first for layer caching, then the source.
COPY pyproject.toml README.md ./
COPY internal ./internal
COPY schemas ./schemas
COPY cmd ./cmd
RUN python -m venv /opt/venv && /opt/venv/bin/pip install .

FROM python:3.12-slim

# libpq for psycopg (pure-python build pulled by langgraph-checkpoint-postgres).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH

WORKDIR /app

ARG DEPLOYMENT_MODE=onprem
ENV DEPLOYMENT_MODE=${DEPLOYMENT_MODE}
# On-prem local media lives under MEDIA_ROOT (default data/media). Mount a
# volume there for persistence / multi-worker; or set S3_* (ADR 0024).

COPY --from=build /opt/venv /opt/venv
COPY internal ./internal
COPY schemas ./schemas
COPY cmd ./cmd
COPY migrations ./migrations
COPY alembic.ini ./
COPY docker/api-entrypoint.sh /usr/local/bin/api-entrypoint.sh
RUN chmod +x /usr/local/bin/api-entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["api-entrypoint.sh"]
CMD ["uvicorn", "cmd.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
