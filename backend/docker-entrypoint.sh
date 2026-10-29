#!/bin/sh
# Container entrypoint: apply migrations, then serve.
# Migrations run before the app accepts traffic; a failed migration stops the deploy.
set -e

echo "Applying database migrations..."
alembic upgrade head

# One worker: background jobs and the upload rate limiter live in this process.
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --workers 1 \
    --proxy-headers \
    --forwarded-allow-ips="*" \
    --no-access-log
