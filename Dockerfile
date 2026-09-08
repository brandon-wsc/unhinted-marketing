# syntax=docker/dockerfile:1
# API image (ADR 0023). DEPLOYMENT_MODE is baked at image build time and is
# immutable for the container's lifetime — on-prem default; cloud images:
#   docker build --build-arg DEPLOYMENT_MODE=cloud -t unhinted-api:cloud .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

ARG DEPLOYMENT_MODE=onprem
ENV DEPLOYMENT_MODE=${DEPLOYMENT_MODE}

# Install dependencies first for layer caching, then the source.
COPY pyproject.toml README.md ./
COPY internal ./internal
COPY schemas ./schemas
COPY cmd ./cmd
COPY migrations ./migrations
COPY alembic.ini ./
RUN pip install .

# On-prem media files (ADR 0024). Cloud images ignore this and write to S3.
# Bind-mount a volume here so generated/uploaded images survive container recreate.
ENV MEDIA_ROOT=/var/lib/unhinted/media
VOLUME ["/var/lib/unhinted/media"]

EXPOSE 8000
CMD ["uvicorn", "cmd.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
