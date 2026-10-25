# DocuMind backend

FastAPI service for DocuMind. It's a modular monolith: thin HTTP routes call
services, and the services reach PostgreSQL, file storage, OCR and the LLM
through interfaces.

> **Status:** Phase 3. Uploads are validated, stored and processed in the
> background: PDF text layers are read with PyMuPDF, and scanned pages and
> images are preprocessed with OpenCV and OCR'd with Tesseract. Per-page
> text, confidence and preview images are saved. Field extraction arrives in
> Phase 4. See [`../IMPLEMENTATION_PLAN.md`](../IMPLEMENTATION_PLAN.md).

## Endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/api/health` | Per-component status (`ok` / `degraded`) |
| POST | `/api/documents/upload` | Multipart field `file`. **202** + `Location`; processing is queued (`job_id`) |
| GET | `/api/documents` | `q`, `status` (repeatable), `document_type`, `date_from`, `date_to`, `sort` (`newest`, `oldest`, `amount_desc`, `amount_asc`, `vendor`), `limit` (1–100), `offset` |
| GET | `/api/documents/{id}` | Detail with pages (text, source, OCR confidence), fields, line items, warnings |
| GET | `/api/documents/{id}/status` | Status, page count, user-safe error, latest job (stage, attempt, timing, `error_code`) |
| POST | `/api/documents/{id}/process` | 202. Retry or reprocess. 409 `already_processing` while a job is active |
| GET | `/api/documents/{id}/pages/{n}/preview` | PNG preview of page *n* (1-based) |
| GET | `/api/documents/{id}/file` | Streams the original file |
| DELETE | `/api/documents/{id}` | 204. Removes the rows (cascade), the stored file and the previews |

### Processing

```
UPLOADED ─► PROCESSING ─► OCR (only if a page has no usable text) ─► COMPLETED
                 └──────────────── any error ─────────────────────► FAILED
```

- **PDFs:** a page whose text layer has at least `PDF_MIN_TEXT_CHARS`
  non-space characters uses that text. Other pages are rendered at
  `OCR_RENDER_DPI`, preprocessed (`PREPROCESS_PDF_STEPS`) and OCR'd.
- **Images:** fully decoded (Pillow) and upright per EXIF, then preprocessed
  (`PREPROCESS_IMAGE_STEPS`) and OCR'd.
- **Retries:** each attempt is a `processing_jobs` row (`attempt` 1, 2, …).
  Pages always reflect the last *successful* run, and a failed run clears
  them. An active job blocks a new one, unless it's older than
  `PROCESSING_STALE_AFTER_SECONDS` (e.g. the server restarted mid-run).
- **Failure codes:** `corrupt_pdf`, `encrypted_pdf`, `empty_document`,
  `too_many_pages`, `corrupt_image`, `image_too_large`, `no_text_found`,
  `ocr_unavailable`, `ocr_failed`, `file_missing`, `internal_error`.
  `documents.error_message` holds a user-safe sentence. Technical detail
  (never document content) goes to `processing_jobs.error_detail` and is
  not exposed by the API.

### Upload rules

- **Type comes from content:** PDF, PNG and JPEG are detected from their leading
  bytes. The filename extension and the declared Content-Type must agree with
  that detection. A generic declared type such as `application/octet-stream`
  is accepted.
- **Size:** `MAX_UPLOAD_SIZE` is enforced twice. A request whose
  `Content-Length` is clearly too big gets a 413 before the body is read, and
  the exact limit is checked while streaming.
- **Filenames:** the client filename is reduced to a safe base name and stored
  as metadata only. Files are stored under server-generated keys such as
  `originals/<uuid>.pdf`.

| Error code | HTTP | When |
|---|---|---|
| `unsupported_file_type` | 415 | Extension is not .pdf/.png/.jpg/.jpeg |
| `unrecognized_file_content` | 415 | Bytes are not a PDF/PNG/JPEG |
| `file_type_mismatch` | 415 | Extension or declared Content-Type disagrees with the content |
| `file_too_large` | 413 | Over `MAX_UPLOAD_SIZE` |
| `empty_file` | 422 | Zero bytes |
| `document_not_found` / `file_not_found` | 404 | Unknown ID / stored file missing |

## Requirements

- Python 3.12+ (developed on 3.14, and the Docker target is 3.12)
- Docker, for PostgreSQL
- Tesseract OCR 5.x, for scanned PDFs and images. Text-layer PDFs work without it.
  - Windows: `winget install UB-Mannheim.TesseractOCR`. It installs to
    `C:\Program Files\Tesseract-OCR`, which the backend finds automatically
    without a `PATH` change.
  - macOS: `brew install tesseract` · Debian/Ubuntu: `apt install tesseract-ocr`
  - Elsewhere, set `TESSERACT_CMD`. `GET /api/health` reports `ocr: error` if it isn't found.

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
| `TESSERACT_CMD` | *(auto)* | Path to `tesseract(.exe)`; empty = `PATH`, then `C:\Program Files\Tesseract-OCR` |
| `OCR_LANGUAGE` | `eng` | Tesseract language pack(s), e.g. `eng+deu` |
| `OCR_TIMEOUT_SECONDS` | `60` | Per-page OCR timeout |
| `OCR_RENDER_DPI` | `300` | Resolution for rendering scanned PDF pages |
| `PDF_MIN_TEXT_CHARS` | `25` | Text-layer characters needed to skip OCR for a page |
| `MAX_PAGES` | `50` | Larger PDFs fail with `too_many_pages` |
| `MAX_IMAGE_PIXELS` | `40000000` | Decompression-bomb guard for images and rendered pages |
| `PREVIEW_MAX_WIDTH` | `1200` | Width of page preview PNGs |
| `PREPROCESS_PDF_STEPS` | `grayscale,deskew` | Steps for rendered PDF pages |
| `PREPROCESS_IMAGE_STEPS` | `resize,grayscale,denoise,contrast,deskew,threshold` | Steps for photos/scans |
| `PROCESSING_STALE_AFTER_SECONDS` | `900` | An active job older than this no longer blocks a retry |

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
- **Migrations**: schema changes go through Alembic. Never use `create_all`
  against Postgres; only tests use it. Review every autogenerated file:
  autogenerate duplicates the CHECK constraints of enum columns (see the
  note in `0001`).
  ```bash
  alembic revision --autogenerate --rev-id 0002 -m "describe change"
  alembic upgrade head
  alembic check                  # models vs database: expect "No new upgrade operations detected."
  alembic downgrade -1           # verify the downgrade path
  ```
  `tests/test_migrations.py` upgrades a throwaway SQLite database, diffs it
  against the models, and downgrades it again.
- **Storage**: code talks to `StorageBackend`
  (`app/services/storage/`), never to file paths. `LocalStorage` writes
  atomically under `STORAGE_PATH`, in `originals/`, `processed/` and `previews/`.

## Layout

```
app/
├── main.py          create_app(): middleware, CORS, routers, error handlers
├── api/routes/      HTTP routes (thin)
├── core/            config, logging, errors, middleware
├── db/              declarative Base + mixins, engine/session
├── models/          ORM models (imported in models/__init__.py for Alembic)
├── schemas/         Pydantic request/response models
├── services/        business logic: document_service, upload_validation, storage/
└── utils/
alembic/             migrations
tests/               pytest suite
```
