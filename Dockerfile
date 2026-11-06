# Imagem única: console web (build estático) + API. Pronta para ECS Fargate / App Runner.
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /usr/local/bin/uv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
RUN uv sync --frozen --no-dev
COPY --from=web /web/dist /app/web/dist
ENV HIVE_DATA_DIR=/data PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8000
RUN useradd -r hive && mkdir -p /data && chown hive /data
USER hive
CMD ["uv", "run", "--no-dev", "uvicorn", "hive.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
