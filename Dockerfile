# DocuMind: one container serving the API (FastAPI) and the built UI (React SPA).
#   docker build -t documind .
#   docker run -p 8000:8000 -e DATABASE_URL=postgresql://... documind

# --- 1. Build the frontend ------------------------------------------------------------
FROM node:22-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# Same-origin API: the SPA calls /api on the host that served it.
ENV VITE_API_BASE_URL=""
RUN npm run build

# --- 2. Runtime: Python + Tesseract ------------------------------------------------------
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Tesseract 5 with English data; libglib for OpenCV.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 app

WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

COPY backend/alembic.ini backend/docker-entrypoint.sh ./
COPY backend/alembic ./alembic
COPY backend/app ./app
COPY --from=frontend /frontend/dist ./static

ENV ENVIRONMENT=production \
    LOG_FORMAT=json \
    STATIC_DIR=/app/static \
    CORS_ORIGINS=""

USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/api/health', timeout=4)" || exit 1
CMD ["sh", "./docker-entrypoint.sh"]
