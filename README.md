# DocuMind

**Turn Documents Into Data.** Upload an invoice or receipt (a PDF, a scan or a phone
photo) and DocuMind reads it, extracts the vendor, dates, totals, tax and line
items, checks that the numbers add up, and tells you what needs a second look.

## Features (working end to end)

- **Upload with real validation**
  - The file type is detected from its bytes, not the extension.
  - Size and page limits are enforced on the server.
  - Corrupt, encrypted and disguised files are rejected with a clear message.
- **Background processing with live status**
  - Stages: queued → reading → OCR (only when needed) → extracting → validating
    → ready / review needed / failed.
  - Status comes from the server, not a simulated progress bar. Failed
    documents can be retried.
- **Text extraction**
  - PDF text layers are read with PyMuPDF.
  - Scanned pages and photos are read with Tesseract OCR after OpenCV
    preprocessing: deskew, denoise, contrast and adaptive thresholding.
- **Structured extraction** with deterministic, explainable rules:
  - Fields: vendor, invoice/receipt number, invoice and due dates, currency,
    subtotal, tax (CGST + SGST summed), discount, total, payment method and
    addresses.
  - Line items, including tables across pages.
  - US, EU and Indian number and date formats, and common OCR mistakes
    (`T0TAL`, `4.0O`).
- **Validation that never edits your data**
  - Checks that subtotal + tax − discount = total, that line items add up, and
    that dates are valid and in order.
  - Ambiguous dates (`03/04/2025`), conflicting totals and missing required
    fields are flagged, so the document goes to **Review needed**.
- **Review and correct**
  - Each field shows its status (OK, check, invalid, missing), a confidence
    score and where it came from.
  - The real page preview sits alongside the fields.
  - Edits to fields and line items persist; validation re-runs on save.
  - Download the original file, export JSON, reprocess (with a warning that
    corrections will be replaced), or delete.
- **Dashboard and analytics**
  - Counts, recent documents, monthly spending, vendors, statuses and types,
    computed from your stored records.
  - Totals are per currency and never mixed.
  - Honest empty states when there isn't enough data.
- **Safe public demo**
  - Each browser gets a private anonymous workspace.
  - Uploads are deleted automatically after 24 h.
  - Uploads are rate-limited and capped per workspace. See
    [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

**Not yet available:** "Ask your documents" (RAG/LLM Q&A) is on the roadmap and is
clearly marked *coming soon* in the app. There are no user accounts.

## Try it

Use the synthetic documents in [`backend/samples/`](backend/samples/): fictional
companies and numbers, including clean invoices, a receipt, a GST invoice, EU
formats, a multi-page table, every validation warning, a scanned PDF and a phone
photo. [`manifest.json`](backend/samples/manifest.json) says what each one shows.
**Please don't upload real personal or financial documents to a public demo.**

## Architecture

```
Browser (React SPA) ──/api──► FastAPI (one container, also serves the SPA)
  per-browser workspace key       ├─ upload validation → storage (local disk or PostgreSQL)
                                  ├─ background job: PyMuPDF / OpenCV + Tesseract
                                  │    → classify → extract → validate
                                  └─ PostgreSQL: documents, pages, fields, line items,
                                     warnings, jobs (Alembic migrations)
```

A modular monolith:
- Routes are thin, and the business logic lives in services.
- OCR, storage, extraction, classification and the job runner each sit
  behind an interface.
- See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the full design and
  decision log, and [backend/README.md](backend/README.md) for the API.

| Layer | Tech |
|---|---|
| Frontend | React 19, TypeScript, Vite, Tailwind CSS 4, TanStack Query, Recharts, wouter |
| Backend | Python 3.12+, FastAPI, Pydantic, SQLAlchemy 2, Alembic |
| Database | PostgreSQL |
| Documents | PyMuPDF, Pillow, OpenCV, Tesseract OCR |
| Deployment | One Docker image; Render Blueprint (`render.yaml`) |

## Project structure

```
frontend/            React SPA (src/services/api.ts is the API seam)
backend/             FastAPI service, tests, samples (see backend/README.md)
e2e/                 Playwright browser end-to-end / smoke test
docs/DEPLOYMENT.md   Render and Docker deployment
Dockerfile           production image (UI + API + Tesseract)
render.yaml          Render Blueprint
docker-compose.yml   local PostgreSQL (+ optional production image)
```

## Local setup

Prerequisites: Python 3.12+, Node 20+, Docker, Tesseract OCR
(Windows: `winget install UB-Mannheim.TesseractOCR`; macOS: `brew install tesseract`;
Debian/Ubuntu: `apt install tesseract-ocr`).

```bash
docker compose up -d postgres

# Backend: http://127.0.0.1:8000/docs
cd backend
python -m venv .venv && .venv/Scripts/activate   # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# Frontend: http://localhost:5173 (proxies /api to the backend)
cd frontend
npm install
npm run dev
```

Or run the production image locally: `docker compose --profile app up -d --build`
(<http://127.0.0.1:8080>).

Environment variables are documented in [`backend/.env.example`](backend/.env.example)
and [`frontend/.env.example`](frontend/.env.example). Only `VITE_*` variables reach the
browser; no secrets belong there.

## Tests

```bash
cd backend
pytest                                   # SQLite
TEST_DATABASE_URL=postgresql+psycopg://documind:documind@127.0.0.1:5432/documind_test pytest
ruff check . && ruff format --check . && alembic check

cd frontend && npm run build             # type-check + production build

python e2e/run_e2e.py http://127.0.0.1:8080   # browser end-to-end (see docs/DEPLOYMENT.md)
```

## Known limitations

- **Extraction:**
  - Rules are English (plus GST/VAT terms).
  - Two-column "Bill to / Ship to" layouts can merge.
  - Line items in noisy photos are often missed.
- **Confidence scores** are documented heuristics, not measured accuracy.
- **Reprocessing** replaces manual corrections (you're warned first).
- **Processing runs in the web process:** a restart mid-job needs a retry
  after 15 minutes. Single instance only.
- **No accounts:** the demo isolates visitors by an anonymous per-browser key,
  which is not authentication.

## Roadmap

Document Q&A with embeddings, retrieval and a local LLM (citing document and page);
a durable job queue; optional user accounts.
