# DocuMind

**Turn Documents Into Data.** Upload an invoice or receipt (a PDF, a scan or a phone
photo) and DocuMind reads it, extracts the vendor, dates, totals, tax and line items,
checks that the numbers add up, shows you where each value is on the page, and tells
you what needs a second look.

Live demo: <https://documind-klhw.onrender.com>. Synthetic documents only, please; see
[Try it](#try-it).

## What works today

- **Upload with real validation**
  - The file type is detected from its bytes. Size and page limits are enforced on the server.
  - Corrupt, encrypted and disguised files are rejected with a clear message.
  - Uploading the same file twice is detected; you can open the existing copy or keep both.
- **Background processing with live status**
  - Stages: queued → reading → OCR (only when needed) → extracting → validating →
    ready / review needed / failed.
  - Failures say whether retrying can help.
  - A server restart never leaves a document stuck in "processing": interrupted runs are
    marked failed and offer a retry.
- **Text extraction**
  - PDF text layers via PyMuPDF.
  - Scans and photos via Tesseract OCR after OpenCV preprocessing (deskew, denoise,
    contrast, adaptive threshold).
- **Structured extraction** with deterministic, explainable rules:
  - Fields: vendor, buyer, invoice/receipt number, PO number, vendor tax/VAT/GST ID,
    invoice and due dates, currency, subtotal, tax (CGST + SGST summed), discount, total,
    payment method (never card digits), addresses.
  - Line items, including tables across pages, separate tax columns, wrapped
    descriptions, `2 x item @ price` receipt lines and weighed items.
  - Rows are never invented: a row without a table header must prove itself by
    arithmetic, or by adding up to the document's own total.
  - US, EU and Indian number and date formats, and common OCR mistakes (`T0TAL`, `4.0O`).
  - Where each value is on the page: selecting a field highlights it on the preview.
    This works for text PDFs and unrotated scans.
- **Validation that never edits your data**
  - Every warning has a stable code, a severity, the affected field or line, its page,
    and a suggested review action.
  - Checks: arithmetic, line items, date order and plausibility, negative amounts,
    ambiguous dates, conflicting values, low confidence, and the same invoice number
    from the same vendor uploaded twice.
- **Review and correct**
  - Each field shows its status, a heuristic confidence score and where it came from.
  - Edits persist and validation re-runs on save.
  - **Corrections survive reprocessing.** You can explicitly discard them instead.
  - Every change is kept in a correction history.
  - Download the original, export JSON, delete.
- **Dashboard and analytics**, aggregated in SQL from your records:
  - spending per currency, with tax and discounts; months and vendors;
  - statuses and document types;
  - processing time, why documents needed review, how often key fields were found,
    and which fields people corrected.
- **Works on phones and tablets.** Audited at 320, 360 and 390 px phone widths, a
  768 px tablet and a 1024 px laptop.
- **Safe public demo.** Each browser gets a private anonymous workspace. Uploads are
  deleted after 24 h, rate-limited and capped per workspace.

**Measured, not claimed:** extraction is scored against hand-labelled ground truth for
the 17 synthetic samples ([docs/EVALUATION.md](docs/EVALUATION.md)). Timings and memory
are in [docs/BENCHMARKS.md](docs/BENCHMARKS.md). Confidence scores are documented
heuristics, not probabilities, and no accuracy claim is made for real-world documents.

**Not available:**
- "Ask your documents" (chat) is marked *coming soon*.
- The optional language-model assistance is **off** on the demo: the free server cannot
  run a model, and the demo has no user accounts.

## Try it

Open the app, go to **Upload** and click one of the four bundled synthetic samples, or
use any file from [`backend/samples/`](backend/samples/). These are fictional companies
and numbers covering every warning, a GST invoice, EU formats, multi-page tables,
two-column layouts, a till receipt, scans and a phone photo.
[`manifest.json`](backend/samples/manifest.json) says what each one shows.
**Please don't upload real personal or financial documents to the public demo.**

## Architecture

```
                      ┌──────────────────────── one container ────────────────────────┐
Browser (React SPA)   │ FastAPI                                                       │
 per-browser key ────►│  /api/documents ── upload validation ─► StorageBackend        │
 X-Workspace-Token    │                                          (disk or PostgreSQL) │
                      │  JobRunner (in-process) ─► DocumentProcessor                  │
                      │      read pages: PyMuPDF text layer │ OpenCV + Tesseract OCR  │
                      │      → classify → extract (rules [+ optional local LLM])     │
                      │      → re-apply user corrections → validate → locate fields   │
                      │  /api/analytics (SQL aggregation)                             │
                      │  maintenance loop: retention · interrupted jobs · orphans     │
                      └───────────────────────────────┬───────────────────────────────┘
                                                      ▼
                       PostgreSQL: documents, pages, extracted_fields, line_items,
                       validation_warnings, processing_jobs, extraction_edits, stored_files
```

It's a modular monolith: routes are thin, and logic lives in services. OCR, storage,
extraction, classification, the language-model provider and the job runner each sit
behind an interface. The design and the decision log (D1–D65) are in
[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md); the API is in
[backend/README.md](backend/README.md) and at `/docs` on a running server.

| Layer | Tech |
|---|---|
| Frontend | React 19, TypeScript, Vite 7, Tailwind CSS 4, TanStack Query, Recharts, wouter; Vitest |
| Backend | Python 3.12+, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic; pytest, Ruff |
| Database | PostgreSQL (SQLite for fast tests) |
| Documents | PyMuPDF, Pillow, OpenCV, Tesseract OCR |
| Optional AI | Local Ollama model via `LLMProvider` (off by default) |
| Deployment | One Docker image; Render Blueprint (`render.yaml`) |

## Project structure

```
frontend/              React SPA (src/services/api.ts is the API seam)
backend/               FastAPI service, migrations, tests, samples, scripts
  samples/             synthetic documents + ground_truth.json
  scripts/             generate_samples.py, evaluate_extraction.py
e2e/                   run_e2e.py (browser journeys / smoke test), mobile_audit.py, benchmark_api.py
docs/                  DEPLOYMENT.md, EVALUATION.md, BENCHMARKS.md
Dockerfile             production image (UI + API + Tesseract)
render.yaml            Render Blueprint
docker-compose.yml     local PostgreSQL (+ optional production image)
```

## Local setup

Prerequisites: Python 3.12+, Node 20+, Docker, and Tesseract OCR.

**OCR setup.** Install Tesseract:
- Windows: `winget install UB-Mannheim.TesseractOCR`
- macOS: `brew install tesseract`
- Debian/Ubuntu: `apt install tesseract-ocr`

DocuMind finds it on `PATH` or in the default Windows location; otherwise set
`TESSERACT_CMD`. `/api/health` reports whether OCR is available.

```bash
docker compose up -d postgres

# Backend: http://127.0.0.1:8000/docs
cd backend
python -m venv .venv && .venv/Scripts/activate   # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
alembic upgrade head                             # database migrations
uvicorn app.main:app --reload --port 8000

# Frontend: http://localhost:5173 (proxies /api to the backend)
cd frontend
npm install
npm run dev
```

You can also run the production image locally: `docker compose --profile app up -d --build`
(<http://127.0.0.1:8080>).

**Environment variables:** every setting is documented in
[`backend/.env.example`](backend/.env.example) and
[`frontend/.env.example`](frontend/.env.example).
- Main groups: database, storage backend, demo safeguards (`DEMO_MODE`,
  `RETENTION_HOURS`, rate limit, workspace cap), processing limits, date order and
  confidence thresholds, maintenance loop, and the optional LLM (`LLM_PROVIDER`).
- Only `VITE_*` variables reach the browser, so no secrets belong there.

**Migrations:** `alembic upgrade head` (the container does this at start-up).
- Revisions are additive and reversible (`alembic downgrade -1`).
- `alembic check` confirms the models and migrations match.

**Optional local LLM** (development only):
```bash
ollama pull llama3.2:3b
LLM_PROVIDER=ollama   # backend/.env
```
- The model only fills fields the rules missed.
- A value must appear verbatim in the document, and is always sent to review.
- Compare against the rules with `python scripts/evaluate_extraction.py --llm`.

## Tests and quality checks

```bash
cd backend
pytest                                   # 376 tests, SQLite
TEST_DATABASE_URL=postgresql+psycopg://documind:documind@127.0.0.1:5432/documind_test pytest
ruff check . && ruff format --check . && alembic check
python scripts/evaluate_extraction.py   # extraction quality vs ground truth

cd frontend
npm test                                 # Vitest unit/component tests
npm run build                            # type-check + production build

python e2e/run_e2e.py http://127.0.0.1:8000        # 21 browser journeys (Playwright)
python e2e/mobile_audit.py http://127.0.0.1:8000 --out shots/   # 5 screen sizes
python e2e/benchmark_api.py http://127.0.0.1:8000  # timings
```

The e2e tools need `pip install -r backend/requirements-e2e.txt && playwright install chromium`.

## Security and privacy

- **No user accounts.** The public demo isolates visitors with an anonymous
  per-browser key.
  - The server stores only its SHA-256, and every query is scoped by it, so another
    visitor's document ID returns 404.
  - This is isolation, not authentication.
- **Synthetic data only on the demo.** Uploads are deleted after 24 h. Rate limits,
  size, page and pixel limits, and bounded concurrency protect the free server.
- **Storage keys are generated by the server**, so paths can't be traversed.
  Queries go through the ORM, with LIKE input escaped.
- **Errors never expose internals**, and logs record IDs and codes, never document
  values or filenames.
- **Payment card numbers are never stored**; only the method name ("Visa") is kept.
- **Documents are never sent to an external AI service.** The optional model must be
  a local server you run yourself.
- Dependency audits: `pip-audit` reports none. `npm audit` reports none for runtime
  dependencies; one moderate dev-only build tool advisory has no non-breaking fix.

## Known limitations

- **Rules:** extraction rules are English (plus GST/VAT terms). Unfamiliar layouts
  should be expected to need review.
- **Line items:** per-line tax and discount columns are recognised, so they aren't
  read as prices, but they aren't stored.
- **Field highlighting:** not available on skewed photos, where positions would be
  unreliable.
- **Processing runs in the web process.** A restart marks running documents as
  interrupted (retry with one click). Single instance only.
- **Accounts:** none, and the chat feature is not built.

## Roadmap

- User accounts, then document Q&A: retrieval over page text, SQL for numbers, a local
  LLM, and answers citing document and page.
- A durable job queue, and storing per-line tax and discount.
- More labelled real-world-style samples; per-field confidence calibration once
  labelled data allows it.
