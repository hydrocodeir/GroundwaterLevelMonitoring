FROM node:22-alpine AS frontend-builder

WORKDIR /build

COPY package.json package-lock.json ./
RUN npm ci

COPY tailwind.config.js ./
COPY scripts ./scripts
COPY frontend/src ./frontend/src
COPY frontend/templates ./frontend/templates
COPY frontend/assets ./frontend/assets

RUN npm run assets


FROM python:3.13-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    MALLOC_ARENA_MAX=2 \
    HOME=/tmp

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY Data ./Data
COPY frontend/templates ./frontend/templates
COPY --from=frontend-builder /build/frontend/assets ./frontend/assets

RUN groupadd --system dashboard \
    && useradd --system --gid dashboard --home-dir /app dashboard \
    && chown -R dashboard:dashboard /app

USER dashboard

EXPOSE 8228

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8228", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips=*", "--timeout-keep-alive", "75", "--no-server-header"]
