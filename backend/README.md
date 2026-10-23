# DocuMind backend

FastAPI service for DocuMind. It's a modular monolith: thin HTTP routes call
services, and the services reach PostgreSQL, file storage, OCR and the LLM
through interfaces.

> **Status:** Phase 1 (skeleton). The health endpoint, configuration,
> structured logging, the error envelope, the database session and Alembic are
> in place. Document endpoints arrive in Phase 2. See
> [`../IMPLEMENTATION_PLAN.md`](../IMPLEMENTATION_PLAN.md).

## Requirements

- Python 3.12+ (developed on 3.14, and the Docker target is 3.12)
- Docker, for PostgreSQL

## Setup

```bash
# from the repository root: start PostgreSQL
docker compose up -d postgres

cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env

alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

- API docs: <http://127.0.0.1:8000/docs>
- Health: <http://127.0.0.1:8000/api/health>

> Use `127.0.0.1`, not `localhost`, in `DATABASE_URL` on Windows. `localhost`
> resolves to IPv6 first, and the Compose port is bound to IPv4, so every
> connection stalls before falling back.

## Configuration

All settings live in [`app/core/config.py`](app/core/config.py) and are read from
the environment or `backend/.env`. See [`.env.example`](.env.example).

| Variable | Default | Purpose |
|---|---|---|
| `ENVIRONMENT` | `development` | `development` / `test` / `production` |
| `LOG_LEVEL` | `INFO` | Root log level |
| `LOG_FORMAT` | `json` | `json` (one object per line) or `console` |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Comma-separated allowed origins |
| `DATABASE_URL` | `postgresql+psycopg://documind:documind@127.0.0.1:5432/documind` | SQLAlchemy URL |
| `DATABASE_CONNECT_TIMEOUT` | `5` | Seconds before a DB connection attempt fails |
| `STORAGE_PATH` | `storage` | Upload storage root, relative to `backend/` |
| `MAX_UPLOAD_SIZE` | `15728640` | Upload size limit in bytes |

## Tests

```bash
pytest                       # SQLite in-memory, fast and hermetic
TEST_DATABASE_URL=postgresql+psycopg://documind:documind@127.0.0.1:5432/documind_test pytest
ruff check . && ruff format --check .
```

The `documind_test` database is created by
`docker/postgres/init/01-test-db.sql` the first time the Postgres volume is
initialised.

## Conventions

- **Errors**: services raise `AppError` subclasses (`app/core/errors.py`). Every
  non-2xx response has this shape:
  `{"error": {"code", "message", "details"}, "request_id"}`.
- **Logging**: use `logger.info("event_name", extra={...})` with IDs, stages and
  durations. Never log document text or extracted values.
- **Request IDs**: every response carries `X-Request-ID`, and every log line
  written during that request includes the same ID.
- **Migrations**: schema changes go through Alembic
  (`alembic revision --autogenerate -m "..."`). Never use `create_all` against
  Postgres; only tests use it.

## Layout

```
app/
├── main.py          create_app(): middleware, CORS, routers, error handlers
├── api/routes/      HTTP routes (thin)
├── core/            config, logging, errors, middleware
├── db/              declarative Base + mixins, engine/session
├── models/          ORM models (imported in models/__init__.py for Alembic)
├── schemas/         Pydantic request/response models
├── services/        business logic (Phase 2+)
└── utils/
alembic/             migrations
tests/               pytest suite
```
