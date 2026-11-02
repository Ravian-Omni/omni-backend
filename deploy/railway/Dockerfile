# DAXAGENT on Railway: one service, one domain. The backend serves the built frontend, so the sign-in
# session cookie reaches every API call, image, download and WebSocket. Data lives on a volume at /data.

FROM node:20-slim AS frontend
WORKDIR /app
COPY omni-frontend/package.json omni-frontend/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY omni-frontend/ ./
ENV VITE_BACKEND_SYSTEM_API_URL=same-origin \
    VITE_BACKEND_WEB_API_URL=same-origin \
    VITE_APP_FOLDER=/data
RUN npx vite build

FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
COPY omni-backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY omni-backend/ ./
COPY --from=frontend /app/dist-react /app/static
# Trust the host's TLS proxy for X-Forwarded-Proto, so OAuth callbacks are built as https (Cognito rejects http)
ENV DAXAGENT_DATA_DIR=/data \
    DAXAGENT_STATIC_DIR=/app/static \
    FORWARDED_ALLOW_IPS=* \
    PYTHONUNBUFFERED=1
CMD ["sh", "-c", "uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
