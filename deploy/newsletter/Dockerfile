FROM node:22-bookworm-slim AS frontend
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

FROM caddy:2.10-alpine AS web
# Caddy listens on 8080; file capabilities prevent exec with cap_drop: ALL.
RUN setcap -r /usr/bin/caddy
COPY deploy/newsletter/Caddyfile /etc/caddy/Caddyfile
COPY --from=frontend /web/dist /srv
USER 10001:10001

FROM python:3.12-slim-bookworm AS python-builder
COPY --from=ghcr.io/astral-sh/uv:0.11.21 /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable --no-cache

FROM python:3.12-slim-bookworm AS runtime
WORKDIR /app
COPY --from=python-builder /app/.venv /app/.venv
COPY alembic.ini ./
COPY migrations ./migrations
COPY deploy/newsletter/maintenance.py ./deploy/newsletter/maintenance.py
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TZ=Asia/Seoul PGSSLROOTCERT=/etc/ssl/certs/ca-certificates.crt
USER 10001:10001
CMD ["uvicorn", "xfolio.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
