# syntax=docker/dockerfile:1
# Pinned python:3.12-slim digest (docker image inspect --format '{{json .RepoDigests}}')
FROM python@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Single source of truth: requirements.txt — keeps Dockerfile and host in sync
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt


FROM python@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/opt/venv/bin:$PATH"

# curl only for HEALTHCHECK
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /usr/sbin/nologin jellysort

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv

# Copy source for prod builds without bind-mount; dev still bind-mounts .:/app and wins at runtime
COPY --chown=jellysort:jellysort . .

# WORKDIR /app itself is root-owned (created before USER); runtime writes go here
RUN mkdir -p /app/logs /app/reports && chown jellysort:jellysort /app/logs /app/reports

EXPOSE 18327

USER jellysort

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=10s CMD curl -f http://localhost:18327/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "18327"]
