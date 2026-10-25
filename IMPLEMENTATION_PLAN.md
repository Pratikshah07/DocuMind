# DocuMind — Implementation Plan

> Turn Documents Into Data. This file is the working plan for taking the
> frontend prototype to a real full-stack application. Update the
> **Status** table as phases complete; record decisions in the
> **Decision log** at the bottom.

## Status

| Phase | Scope | Status |
|---|---|---|
| 0 | Repository audit, plan, architecture | ✅ Done |
| 1 | Backend skeleton: FastAPI, config, DB, health | ✅ Done |
| 2 | Upload, validation, storage, document model, initial migration | ✅ Done |
| 3 | PDF/image processing, preprocessing, OCR | ✅ Done |
| 4 | Classification, extraction, validation, confidence | ⏳ Next |
| 5 | Frontend ↔ backend integration | — |
| 6 | Analytics | — |
| 7 | Embeddings, vector store, retrieval | — |
| 8 | LLM provider (Ollama), chat, source references | — |
| 9 | Authentication (only if needed) | — |
| 10 | Testing, security and performance review | — |
| 11 | Docker / deployment preparation | — |
| 12 | README, docs, cleanup | — |

---

## 1. Current architecture (audit findings)

### Repository layout

```
documind/
├── frontend/            React + Vite SPA (the UI prototype, mock data layer)
├── backend/             FastAPI service (Phase 1+)
├── docker/              container init scripts
├── docker-compose.yml   local Postgres (more services in Phase 11)
└── IMPLEMENTATION_PLAN.md
```

### Frontend stack (`frontend/`)

| Concern | Actual implementation |
|---|---|
| Framework | React **19.1**, TypeScript ~5.9, Vite **7** |
| Styling | Tailwind CSS **4** (`@tailwindcss/vite`), CSS-variable theme in `src/index.css`, light + dark |
| Components | shadcn/ui (new-york) primitives in `src/components/ui/` — **largely unused**; pages use hand-rolled Tailwind markup |
| Icons | lucide-react |
| Routing | **wouter** 3 (not React Router) |
| Server state | TanStack Query 5 (`QueryClientProvider` in `App.tsx`) |
| Charts | Recharts 2 |
| Toasts | Custom `documind-toast` window event + `ToastViewport` in `App.tsx` (shadcn `Toaster` also mounted but unused) |
| Data layer | `src/services/api.ts` — a **localStorage mock** with 10 seed documents |
| Env config | `vite.config.ts`: optional `PORT` (default 5173), `BASE_PATH`, `VITE_API_PROXY_TARGET`; `/api` is proxied to the backend in dev |
| Scripts | `dev`, `build` (typecheck + bundle), `preview`, `typecheck` (npm) |
| Tests | None |

### Routes (wouter, all defined in `App.tsx`)

| Route | Component | Location |
|---|---|---|
| `/` | `Landing` | `App.tsx` |
| `/app/dashboard` | `DashboardPage` | `pages/dashboard.tsx` |
| `/app/documents` | `DocumentsPage` | `pages/documents.tsx` |
| `/app/documents/:id` | `DocumentDetail` | `App.tsx` |
| `/app/upload` | `UploadPage` | `pages/upload.tsx` |
| `/app/analytics` | `AnalyticsPage` | `pages/analytics.tsx` |
| `/app/chat` | `ChatPage` | `App.tsx` |
| `/app/settings` | `SettingsPage` | `pages/settings.tsx` |
| `*` | `NotFoundPage` | `App.tsx` |

### Existing types (`src/services/api.ts`)

```ts
ProcessingStatus = 'Ready' | 'Review needed' | 'Processing' | 'Failed'
DocumentField   = { key, label, value: string, confidence: number /* 0–100 */ }
LineItem        = { id, description, quantity, unitPrice, total }
Document        = { id, name, vendor, type: 'Invoice'|'Receipt', date, dueDate?, amount,
                    currency, status, category, pages, fields[], lineItems[] }
ChatMessage     = { id, role, content, sources?: string[], createdAt }
Analytics       = { totalSpend, documentCount, averageInvoice, vendors[], categories[],
                    monthly[], types[] }
User            = { name, email, workspace, currency, theme }
```

### What already works (as UI)

- Polished landing page, app shell (sidebar, topbar, mobile drawer), light/dark theme.
- Dashboard: stat cards, recent documents, processing activity, monthly spend area chart, type donut.
- Documents: search, status/type/date filters, six sort orders, table on desktop, cards on mobile, empty/loading/error states.
- Document detail: simulated preview with zoom/paging, editable extracted fields with confidence bars, editable line items, save, JSON export, delete with confirm modal.
- Upload: drag-and-drop dropzone, extension filter, per-file queue with stage + progress.
- Analytics: four metric cards, monthly/vendor/category bar charts, type donut.
- Chat: thread list (localStorage), suggestions, message list with clickable source chips.
- Settings: profile, preferences, theme, "reset demo data".

### What is fake / missing

| Area | Current state |
|---|---|
| Upload | Only the filename is stored in localStorage; no file is sent anywhere |
| Processing | Progress stages are **timers** (`pause(280)`), not real states |
| Extraction | `finishDemoProcessing` writes hardcoded values (`$428.75`, vendor "New demo upload") |
| Preview | A drawn HTML mock of an invoice, not the uploaded file |
| Analytics | Computed client-side; the first five monthly values are **hardcoded** |
| Chat | Keyword-matched canned answers; sources are just the first two documents |
| Backend / DB / OCR / AI | None |
| Tests | None |

### Code-quality issues to fix along the way

- `App.tsx` is ~85 KB: it holds `Landing`, `AppShell`, `DocumentDetail`, `ChatPage`, helpers,
  and **large dead code blocks** (unreachable code after `return` in `DocumentsPage`/`UploadPage`,
  commented-out old versions of Dashboard/Analytics/Settings).
- `StatusPill`/`Status`, `Metric`/`StatCard`, `formatCurrency`, and error banners are duplicated
  across 4–5 files.
- Production bundle is a single ~900 KB chunk; split by route in Phase 5.

---

## 2. Target architecture

A **modular monolith**: one React SPA, one FastAPI process, PostgreSQL, a
local ChromaDB directory, local file storage, and Ollama as an external LLM.

```
┌──────────────────────┐   REST/JSON    ┌───────────────────────────────────────────┐
│ React SPA (Vite)     │ ─────────────► │ FastAPI (app/api)                          │
│ TanStack Query       │                │   ├─ services/ (business logic)            │
│ services/api.ts ─────┼── fetch ──────►│   ├─ pipeline (BackgroundTasks / job ABC)   │
└──────────────────────┘                │   └─ db/ (SQLAlchemy sessions)             │
                                        └──┬──────────┬───────────┬──────────┬───────┘
                                           │          │           │          │
                                    PostgreSQL   storage/     ChromaDB    Ollama
                                    (metadata,   (originals,  (vectors)   (LLM HTTP)
                                     results)     previews)
```

### Backend layout

```
backend/
├── app/
│   ├── main.py                 # create_app(): middleware, routers, handlers
│   ├── api/
│   │   ├── deps.py             # DI providers (db session, services)
│   │   └── routes/             # health, documents, processing, extraction, analytics, chat
│   ├── core/
│   │   ├── config.py           # pydantic-settings; all env vars live here
│   │   ├── logging.py          # structured JSON logging + request-id context
│   │   └── errors.py           # AppError hierarchy + consistent error envelope
│   ├── db/                     # Base, engine/session factory
│   ├── models/                 # SQLAlchemy ORM models
│   ├── schemas/                # Pydantic request/response + extraction schemas
│   ├── services/
│   │   ├── storage/            # StorageBackend ABC → LocalStorage (S3 later)
│   │   ├── document_service.py
│   │   ├── upload_validation.py
│   │   ├── pdf_service.py      # PyMuPDF: text layer detection, page rendering
│   │   ├── preprocessing_service.py
│   │   ├── ocr/                # OCRService ABC → TesseractOCR
│   │   ├── classification_service.py
│   │   ├── extraction/         # normalize → regex → patterns → (NLP) → (LLM) → validate
│   │   ├── validation_service.py
│   │   ├── confidence.py
│   │   ├── pipeline.py         # orchestrates stages, updates status
│   │   ├── jobs.py             # JobRunner ABC → BackgroundTaskRunner (Celery/RQ later)
│   │   ├── embedding_service.py
│   │   ├── vector_store/       # VectorStore ABC → ChromaVectorStore (pgvector later)
│   │   ├── llm/                # BaseLLMProvider → OllamaProvider; LLMService
│   │   ├── rag_service.py
│   │   ├── chat_service.py     # routes questions: SQL aggregation vs RAG
│   │   └── analytics_service.py
│   └── utils/
├── alembic/                    # migrations
├── tests/                      # pytest + TestClient; fixtures/ with sample docs
├── requirements.txt / requirements-dev.txt
├── .env.example
└── README.md
```

Rules: routes are thin (parse → call service → map to schema). Services do not
import FastAPI. External tools (Tesseract, Chroma, Ollama, filesystem) are only
reached through an interface so they can be swapped or faked in tests.

---

## 3. Database architecture (PostgreSQL + SQLAlchemy 2 + Alembic)

UUID primary keys, `created_at`/`updated_at` on every table, money as
`NUMERIC(14,2)`, confidence as `FLOAT` in 0–1.

| Table | Key columns | Notes |
|---|---|---|
| `users` | id, email (unique), name, created_at | Single local user until auth (Phase 9) |
| `documents` | id, user_id→users (nullable), original_filename, storage_key, mime_type, size_bytes, sha256, page_count, document_type, status, error_message, vendor_name, invoice_number, invoice_date, due_date, currency, subtotal, tax, discount, total, payment_method, category, overall_confidence, processed_at | Denormalized headline fields for fast listing & analytics. Indexes: status, document_type, vendor_name, invoice_date, created_at, sha256 |
| `document_pages` | id, document_id, page_number, text, text_source (`embedded`/`ocr`), ocr_confidence, width, height, preview_key | Unique (document_id, page_number) |
| `extracted_fields` | id, document_id, name, value (text), normalized_value (JSON), confidence, method, page_number, bbox (JSON), is_user_edited | Full provenance per field; unique (document_id, name) |
| `line_items` | id, document_id, position, description, quantity, unit_price, total, confidence, page_number | |
| `validation_warnings` | id, document_id, field, code, message, severity | Kept separate so edits can re-run validation |
| `processing_jobs` | id, document_id, status, stage, attempt, started_at, finished_at, duration_ms, error_code, error_detail | One row per processing attempt; observable lifecycle |
| `document_chunks` | id, document_id, page_number, chunk_index, text, token_count, vector_id | Source of truth for the vector index (rebuildable) |
| `chat_sessions` | id, user_id, document_id (nullable = workspace chat), title | |
| `chat_messages` | id, session_id, role, content, sources (JSON), answer_type (`sql`/`rag`/`none`), created_at | |

Status enum (`documents.status`): `UPLOADED → PROCESSING → OCR → EXTRACTING →
VALIDATING → COMPLETED | NEEDS_REVIEW | FAILED`. The frontend maps these to its
existing labels (`COMPLETED`→Ready, `NEEDS_REVIEW`→Review needed, `FAILED`→Failed,
others→Processing with the real stage shown).

Migrations: `0001` core document tables (Phase 2) → `0002` chunks (Phase 7) →
`0003` chat (Phase 8). Never `create_all` against Postgres outside tests.

---

## 4. API plan

All routes under `/api`. JSON errors use one envelope:
`{"error": {"code": "unsupported_file_type", "message": "...", "details": {...}}, "request_id": "..."}`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness + DB/OCR/LLM/vector-store component checks |
| POST | `/api/documents/upload` | Multipart upload → validates → stores → queues processing → 202 `{id, status, job_id, …}` + `Location` (D20) |
| GET | `/api/documents` | List with search, status, type, date range, sort, pagination |
| GET | `/api/documents/{id}` | Detail incl. pages, fields, line items, warnings |
| DELETE | `/api/documents/{id}` | Deletes rows, stored files, vectors |
| GET | `/api/documents/{id}/file` | Streams the original (never exposes the storage dir) |
| GET | `/api/documents/{id}/pages/{n}/preview` | PNG page preview |
| POST | `/api/documents/{id}/process` | (Re)process |
| GET | `/api/documents/{id}/status` | Status, stage, job timing, error message |
| GET | `/api/documents/{id}/extraction` | Structured `DocumentExtraction` with per-field confidence + warnings |
| PATCH | `/api/documents/{id}/extraction` | User corrections → re-validate, mark `is_user_edited` |
| GET | `/api/analytics/overview` | Counts by status/type, total & average spend |
| GET | `/api/analytics/spending` | Monthly spend (+ category) |
| GET | `/api/analytics/vendors` | Spend per vendor |
| POST | `/api/documents/{id}/chat` | Question about one document (RAG) |
| POST | `/api/chat` | Workspace question: SQL aggregation for numeric questions, RAG otherwise |

FastAPI's OpenAPI at `/docs`. Every route has summary, description,
`response_model` and documented error responses.

---

## 5. Processing pipeline

```
upload → validate (ext + magic bytes + size) → store original → DB row (UPLOADED)
→ JobRunner.enqueue(process_document)
   PROCESSING  PDF? PyMuPDF text layer per page; chars/page ≥ threshold → embedded text
   OCR         pages without text → render @300dpi → preprocessing (configurable) → Tesseract
   EXTRACTING  normalize → classify → regex → patterns/line items → (NLP) → (LLM fallback)
   VALIDATING  dates, numerics, currency, subtotal+tax−discount≈total, Σ line items
   → COMPLETED or NEEDS_REVIEW (low confidence / warnings) ; any stage exception → FAILED
→ index chunks (embeddings) — failures here do not fail extraction
```

- **Preprocessing** steps are a list of named, configurable operations
  (`resize`, `grayscale`, `denoise`, `threshold`, `contrast`, `deskew`). Default
  pipeline is chosen per source (rendered scanned PDF vs photo); the original is never modified.
- **Confidence** is a documented heuristic, *not* a probability:
  `base(method) × format_validity × context_bonus × ocr_factor`, clamped to [0,1],
  then reduced by failing consistency checks. Thresholds (High ≥ 0.85, Medium ≥ 0.6)
  come from settings.
- **Validation** never rewrites values; it records warnings.
- **Background jobs**: `JobRunner` interface with a `BackgroundTaskRunner`
  implementation (FastAPI `BackgroundTasks`). Each run writes a `processing_jobs`
  row, so lifecycle and timings are observable. Celery/RQ can implement the same interface later.

---

## 6. AI / RAG plan

- **LLM abstraction**: `BaseLLMProvider.generate(prompt, system, json_schema?)`;
  `OllamaProvider` over HTTP (`httpx`). `LLMService` exposes
  `summarize_document`, `answer_question`, `classify_document`,
  `extract_complex_fields`. A `NullProvider` is used when Ollama is unreachable,
  so the app still runs and says the AI is unavailable instead of faking answers.
- **Embeddings**: `EmbeddingService` (Sentence Transformers, default
  `all-MiniLM-L6-v2`, loaded lazily).
- **Vector store**: `VectorStore` ABC → `ChromaVectorStore` (persistent dir).
  Postgres `document_chunks` keeps chunk text, so the index can be rebuilt or
  moved to pgvector.
- **Chunking**: per page, ~500 tokens with overlap, page number retained.
- **Question routing** (`chat_service`): an intent classifier recognises
  deterministic aggregate questions ("total spending last month", "highest vendor")
  and answers them **from SQL**, labelled as such. Everything else goes to RAG:
  embed → top-k → prompt with numbered sources → answer must cite sources or say
  "I couldn't find that in your documents". Responses carry
  `sources: [{document_id, filename, page_number, snippet}]`.

---

## 7. Frontend integration plan (Phase 5)

1. Tooling (done during cleanup): standalone npm project, dev proxy for `/api`.
   Add `VITE_API_BASE_URL` for production builds.
2. Add `src/lib/api-client.ts` (fetch wrapper, error envelope → `ApiError`) and
   backend DTO types; keep `src/services/api.ts` as the single seam, adapting
   backend DTOs to the **existing** UI types so pages change minimally.
3. Replace mock calls page by page; upload polls `/status` via TanStack Query
   `refetchInterval` and shows real stages.
4. Document detail: real preview images, warnings, confidence badges.
5. Extract shared components out of `App.tsx` (Sidebar, Topbar, StatCard,
   StatusBadge, ConfidenceBadge, EmptyState, LoadingState, ErrorState,
   DocumentPreview, ExtractionPanel, LineItemsTable, AIChat, ChatMessage,
   SourceReference) — moving markup, not redesigning it — and delete dead code.
6. Replace "demo" copy only where the feature is now real.

---

## 8. Testing plan

- **Backend (pytest + TestClient)**: config, health, upload validation (spoofed
  extension, oversized, empty, path traversal names), storage, PDF text vs scanned
  detection, OCR service (skipped when Tesseract absent), preprocessing, classifier,
  extraction per field, validation rules, confidence, API endpoints, analytics SQL,
  chunking + retrieval with a fake embedder, chat routing.
- Test DB: SQLite in-memory by default for speed; `TEST_DATABASE_URL` runs the
  same suite against Postgres. Models use portable types (`Uuid`, `JSON`, `Numeric`).
- **Fixtures**: generated sample invoices/receipts (PDF with text layer, scanned
  PDF, noisy/blurred PNG, missing invoice number, missing tax, multi-line items,
  malformed totals, non-invoice document). Synthetic data only.
- **Frontend**: Vitest + Testing Library for the API adapter (DTO → UI mapping)
  and critical components (status badge, upload validation).

## 9. Deployment plan

- `docker-compose.yml`: `postgres` (Phase 1), then `backend` (Python 3.12 + Tesseract) and `frontend` (Phase 11).
- Frontend → Vercel/Netlify (`VITE_API_BASE_URL`). Backend → Render/Railway
  (Dockerfile). DB → managed Postgres. Storage → persistent disk now, S3 adapter later.
- Ollama is not available on typical PaaS free tiers; deployed builds run with the
  LLM disabled (deterministic extraction + SQL answers still work) unless an
  Ollama host URL is configured. `docs/DEPLOYMENT.md` will say this plainly.

## 10. Phases (detailed)

| Phase | Deliverables | Exit criteria |
|---|---|---|
| 1 | `backend/` skeleton, settings, JSON logging + request IDs, error envelope, SQLAlchemy engine/session, Alembic wiring, `GET /api/health`, compose with Postgres, pytest | `pytest` green; `/api/health` reports DB ok against Docker Postgres |
| 2 | Storage abstraction, upload validation (magic bytes), document/page/field/line-item/job models, migration 0001, upload/list/get/delete/file endpoints | Upload a PDF via `/docs`, row + file exist, tests green |
| 3 | PDF service, preprocessing pipeline, OCR abstraction + Tesseract, pipeline stages with status updates, `process`/`status` endpoints | Scanned + text PDFs produce per-page text; failure → FAILED with message |
| 4 | Normalizer, classifier, field extractors, line items, validation, confidence, `extraction` GET/PATCH, sample dataset | Fixture docs extract expected values; tests cover edge cases |
| 5 | Frontend tooling fixes, API client, page-by-page integration, component extraction | `npm run build` green; full flow works in the browser |
| 6 | Analytics service + endpoints; frontend charts on real data | Numbers match SQL |
| 7 | Chunking, embeddings, Chroma, migration 0002, indexing stage | Retrieval tests green |
| 8 | LLM provider abstraction, Ollama, chat service, migration 0003, chat UI wiring | Answers cite sources; "not found" path works; SQL path for aggregates |
| 9 | Auth if needed (likely skipped; single-user portfolio app) | Decision recorded |
| 10 | Coverage gaps, security checklist, perf (indexes, N+1, pagination) | Review notes in docs |
| 11 | Dockerfiles, full compose, deployment docs | `docker compose up` runs everything |
| 12 | Root README, screenshots, final cleanup | No dead code, docs accurate |

---

## Decision log

| # | Decision | Why |
|---|---|---|
| D1 | Keep **wouter** instead of switching to React Router | Already working across all pages; switching adds churn with no user-visible benefit |
| D2 | Two top-level apps, `frontend/` and `backend/`, no JS monorepo tooling | A single frontend package does not need workspace tooling; npm keeps setup simple |
| D4 | Tests default to SQLite, optionally Postgres via `TEST_DATABASE_URL` | Fast hermetic tests; portable column types keep behaviour aligned |
| D5 | Python 3.12 is the target for Docker/deploy; local dev also works on 3.14 | Only 3.14 is installed locally; 3.12 is the conservative wheel target for ML deps |
| D6 | spaCy is optional, added only if a concrete extraction need appears | Avoid adding technology for its own sake (rule 17) |
| D7 | Single default local user, no auth initially | Portfolio app; schema has `user_id` so auth can be added later |
| D8 | Confidence is a transparent heuristic, documented as such | Not a calibrated probability; the UI and docs must not imply otherwise |
| D9 | Default DB host is `127.0.0.1`, not `localhost` | On Windows `localhost` resolves to IPv6 first while the Compose port is IPv4-only, which stalls every connection |
| D10 | Postgres `connect_timeout` = 5s (configurable) | Docker Desktop's port proxy accepts TCP when the DB is down, so connections hung forever instead of failing |
| D11 | Tests use `httpx2` | Starlette's TestClient deprecated plain `httpx` |
| D12 | Enums stored as VARCHAR(32) + one named CHECK constraint (`ck_<table>_<enum>`), not native PG ENUM | Portable to SQLite tests; adding a value is a plain constraint swap in a migration |
| D13 | Upload type is decided by magic bytes; extension **and** declared Content-Type must agree; generic `application/octet-stream` is tolerated | "Do not trust the extension alone"; browsers sometimes send generic types |
| D14 | Upload returns **201 Created** (not 202) in Phase 2 | Nothing is queued yet, so 202 would be untrue. Revisit when Phase 3 queues processing |
| D15 | Duplicate uploads (same SHA-256) are allowed; `sha256` is stored and indexed | Spec doesn't define duplicate handling; the index makes detection/dedup a cheap later addition |
| D16 | Storage keys are server-generated (`originals/<uuid><ext>`); the client filename is sanitized metadata only | Removes path traversal by construction; `LocalStorage` also validates keys and confines them to its root |
| D17 | Upload writes file → row (file deleted if the commit fails); delete removes row → file (orphan logged if file delete fails) | The DB never references a missing file |
| D18 | Money is `NUMERIC(14,2)` in the DB and serialized as a JSON number | Exact storage; the UI wants numbers. Float precision is ample for display amounts |
| D19 | `UploadSizeLimitMiddleware` rejects by `Content-Length` before multipart parsing; the service enforces the exact limit while streaming | Starlette otherwise spools the whole body to disk before validation runs |
| D20 | Upload auto-queues processing and returns **202** (supersedes D14); `POST /process` is for retries/reprocessing | Approved 2026-10-24; matches the plan's API table |
| D21 | Phase 3 terminal status is `COMPLETED`; Phase 4 inserts `EXTRACTING`/`VALIDATING` before it | Approved; no enum change needed |
| D22 | Page previews (PNG, ≤1200 px wide) are produced in Phase 3, served by `GET /documents/{id}/pages/{n}/preview` | Approved; pages are rendered anyway, and the UI needs them in Phase 5 |
| D23 | Low OCR confidence is recorded, not fatal; a document fails only if **no** page yields text | Approved; Phase 4 decides NEEDS_REVIEW from confidence + extraction. A blank page inside a document is normal |
| D24 | PyMuPDF pinned `<2` | 2.x pulls in onnxruntime and layout models that are not used |
| D25 | Tesseract via `pytesseract` behind `OCRService`; binary auto-detected (`PATH`, then `C:\Program Files\Tesseract-OCR`), overridable with `TESSERACT_CMD` | Works on Windows without editing PATH; engine is swappable |
| D26 | Pages hold the last **successful** run: replaced in the COMPLETED transaction, cleared on failure; jobs run only from `QUEUED`; an active job → 409 unless older than the stale timeout | Retries and duplicate deliveries cannot create duplicate or stale pages; a crashed worker cannot block a document forever |
| D27 | Deskew uses the projection-profile method on an adaptive-threshold ink mask | Measured: min-area-rect gave 80–90° on short text blocks, and a global threshold gave 18° on shadowed photos; projection profile is within 0.1° on both |
| D28 | Photo profile includes adaptive `threshold` and non-local-means `denoise` (searchWindow 11) at a 2000 px working width | Measured on noisy, unevenly lit photos: without threshold Tesseract returned 0 characters; median/Gaussian denoise read 0/5 vs NL-means 5/5; 12 MP NL-means 10.7 s → 1.8 s at 2000 px |
| D29 | `document_pages.width/height` are the **preview** image dimensions; OCR word boxes are returned by `OCRService` but not persisted yet | Phase 4 consumes boxes in-process; when stored they will be normalized to 0–1 so they map onto previews |

## Phase log

### Phase 1 — backend skeleton (done)
- `backend/` with `create_app()` factory, pydantic-settings config, JSON/console
  structured logging with request IDs, `AppError` hierarchy + error envelope,
  explicit CORS, SQLAlchemy 2 engine/session (lazy), Alembic wired to settings,
  `GET /api/health` with per-component status.
- `docker-compose.yml` with Postgres 17 (+ `documind_test` DB via init script).
- 9 tests passing on SQLite **and** Postgres; ruff clean. Verified live: health
  `ok` → stop Postgres → `degraded` in 5s → restart → `ok`.

### Repository cleanup (done)
- Frontend moved to `frontend/` as a standalone npm project; unused template
  packages (Express server, component sandbox, generated clients, Drizzle,
  scripts) and hosting-specific config removed; unused workspace dependency and
  dev-only Vite plugins dropped.
- `npm run build` (tsc + vite) green on Windows; dev server serves all routes.

### Phase 2 — upload, validation, storage, document model (done)

**Implemented**
- **Models** (`app/models/`): `users`, `documents`, `document_pages`,
  `extracted_fields`, `line_items`, `validation_warnings`, `processing_jobs`.
  UUID PKs, timestamps, cascade deletes, the indexes listed in §3 plus
  `created_at`. SQLite engines now enforce foreign keys (`PRAGMA foreign_keys=ON`).
- **Migration `0001_create_core_document_tables`**: autogenerated, then
  hand-reviewed. The duplicated enum CHECK constraints autogenerate emits
  were removed, leaving one per enum column.
- **Storage** (`app/services/storage/`): `StorageBackend` ABC plus
  `LocalStorage` (atomic temp+rename writes, key validation, root
  confinement, `originals/`, `processed/`, `previews/`).
- **Upload validation** (`app/services/upload_validation.py`): magic-byte
  detection, extension and declared-MIME agreement, streaming size cap,
  SHA-256, filename sanitization (directory parts, control and reserved
  characters, NFKC, length).
- **`DocumentService`** with upload, list (search with escaped LIKE,
  filters, sort with stable tie-break, pagination), get, file streaming
  and delete. Thin routes in `app/api/routes/documents.py`; DI in `app/api/deps.py`.
- **Endpoints**: `POST /api/documents/upload`, `GET /api/documents`,
  `GET /api/documents/{id}`, `GET /api/documents/{id}/file`,
  `DELETE /api/documents/{id}`.
- **`UploadSizeLimitMiddleware`** (D19). Alembic `env.py` now uses the app's
  `build_engine` (connect timeout; previously it hung when Postgres was
  down) and can skip its logging config for programmatic use.

**Verification** (2026-10-24)
- `pytest`: **96 passed** on SQLite and **96 passed** on Docker
  PostgreSQL (`documind_test`). The Postgres run was confirmed by
  `pg_stat_database` commits rising 223 → 447.
- Mutation checks: disabling the SQLite FK pragma, the extension/content
  check, or the size middleware each makes the relevant tests fail.
- `ruff check .` and `ruff format --check .`: clean.
- Alembic on Postgres: `upgrade head` → `check` ("No new upgrade operations
  detected") → `downgrade base` (0 tables) → `upgrade head`. 6 CHECK
  constraints in the database, as intended. `tests/test_migrations.py`
  repeats upgrade/diff/downgrade on SQLite.
- Live (uvicorn + Postgres): upload 201 with the file on disk and the row
  in the DB; HTML disguised as PDF gets 415 `unrecognized_file_content`;
  the download is byte-identical; delete 204 removes both. Logs carry IDs,
  sizes and types, no filenames.
- Frontend: not modified.

**Known limitations / follow-ups**
- Chunked uploads with no `Content-Length` are still spooled by Starlette up
  to the service-level check (the service rejects them, but only after
  parsing). Revisit in Phase 10 (ASGI body counting or a reverse-proxy limit).
- Content validation is signature-only. Truncated or corrupted PDFs and
  images are detected when PyMuPDF and Pillow open them in Phase 3
  (→ `FAILED`). `page_count` stays NULL until then.
- `GET /file` serves inline with `nosniff` and `no-store`. Hardening for
  PDFs with active content (e.g. CSP `sandbox`, which can break browser
  PDF viewers) is deferred to Phase 10.
- No duplicate detection (D15) and no `users` rows yet (Phase 9).
- Test samples are synthetic and structurally minimal (the JPEG has a valid
  signature but isn't decodable). Rendered samples come with Phase 3.

### Phase 3 — PDF/image processing, preprocessing, OCR (done)

**Scope approved before implementation (2026-10-24):** upload auto-queues
(D20), terminal status `COMPLETED` (D21), previews included (D22), low OCR
confidence recorded rather than fatal (D23).

**Implemented**
- `pdf_service.py`: PyMuPDF open/validate (corrupt, encrypted, zero-page,
  page limit), per-page text layer, rendering with a pixel budget. MuPDF's
  stderr messages are suppressed (they can quote document internals).
- `image_service.py`: full Pillow decode (`verify()` + `load()`),
  EXIF orientation, decompression-bomb guard.
- `preprocessing_service.py`: named, configurable steps (resize,
  grayscale, denoise, contrast, threshold, deskew) with separate profiles
  for PDF renders and photos. Inputs are never mutated.
- `ocr/`: `OCRService` ABC plus `TesseractOCR`, returning text, mean
  confidence and word boxes. `OCRUnavailableError` and `OCRError` are separate.
- `jobs.py`: `JobRunner` ABC, `BackgroundTaskRunner` (FastAPI) and
  `InlineJobRunner`. Jobs take IDs only (queue-ready).
- `pipeline.py`: `DocumentProcessor` runs PROCESSING → OCR (if needed) →
  COMPLETED/FAILED and owns all status transitions and the consistency
  rules (D26). The deleted-during-processing case is handled.
- `processing_service.py`: enqueue (row lock + 409 + stale-job recovery)
  and status.
- **API:** upload returns 202 + `job_id`; new `POST /documents/{id}/process`,
  `GET /documents/{id}/status`, `GET /documents/{id}/pages/{n}/preview`.
  The detail endpoint now includes page text, source, OCR confidence and
  `has_preview`. Delete also removes the previews. `/health` gained an `ocr` component.
- **Config:** `TESSERACT_CMD`, `OCR_*`, `MAX_PAGES`, `MAX_IMAGE_PIXELS`,
  `PDF_MIN_TEXT_CHARS`, `PREVIEW_MAX_WIDTH`, `PREPROCESS_*_STEPS`,
  `PROCESSING_STALE_AFTER_SECONDS`.
- **Dependencies:** `pymupdf<2`, `pillow`, `numpy`, `opencv-python-headless`,
  `pytesseract`. All have Windows / Python 3.14 wheels (checked with
  `pip install --dry-run --only-binary=:all:`).
- **No schema change:** existing columns cover Phase 3, and `alembic check`
  is clean at `0001`.

**Tests**: real, decodable fixtures generated in code (`tests/samples.py`):
text PDFs, scanned PDFs, mixed PDFs, encrypted, zero-page, corrupt and
truncated files, PNG, JPEG, a skewed/noisy/shadowed "phone photo", and EXIF
rotation. `FakeOCR` makes pipeline tests deterministic. Real-Tesseract tests
are marked `requires_tesseract` (skipped only if the binary is missing).

**Verification** (2026-10-25)
- `pytest`: **180 passed** on SQLite and **180 passed** on Docker
  PostgreSQL (the latter confirmed by `documind_test` commits 816 → 1552).
  No skips: Tesseract 5.4.0 was present.
- Mutation checks: removing the page replacement on success, the page
  clearing on failure, the 409 guard, or the QUEUED-only guard each makes
  tests fail.
- `ruff check .` and `ruff format --check .`: clean (58 files).
- Alembic: `heads`/`current` = `0001`, `check` → "No new upgrade operations detected."
- **Live on Windows** (uvicorn + Docker Postgres + real Tesseract,
  `TESSERACT_CMD` unset, so auto-detected):
  - text PDF: embedded, 0.7 s
  - scanned PDF: OCR, confidence 0.90, 3.1 s
  - mixed PDF: page 1 embedded, page 2 OCR
  - phone-style photo: confidence 0.92, 4.4 s
  - corrupt PDF: `FAILED` / `corrupt_pdf` with a user-safe message
  - reprocessing: attempt 2 keeps exactly one set of pages
  - delete: 0 rows and 0 files left
  - no document text in the server log
- Frontend: not modified.

**Limitations / follow-ups**
- `BackgroundTasks` run in the API process: jobs are lost on restart
  (stale-job recovery makes them retryable). A real queue would implement
  `JobRunner` (Phase 11 if needed).
- OCR accuracy was measured on synthetic documents only. Real receipts
  (thermal paper, crumpled, small fonts) will need tuning. The preprocessing
  profiles are configurable for that.
- No orientation detection beyond EXIF and ±15° deskew: pages scanned at
  90°/180° OCR poorly. Tesseract OSD could be added.
- OCR word boxes are not persisted (D29). Per-page OCR is sequential, about
  3–4 s per scanned page on this machine.
- A document deleted mid-run between the final check and the commit can
  leave orphaned preview files (logged). Rare; a storage sweep could
  clean them up.
- The Phase 2 limitations (chunked uploads, inline `GET /file` hardening)
  are unchanged.

**Manual setup (Windows)**
- `winget install UB-Mannheim.TesseractOCR` (done on this machine: v5.4.0, `eng` + `osd`).
- `pip install -r requirements-dev.txt` in `backend\` (adds the Phase 3 packages).
- No migration needed, and the existing `.env` keeps working (new settings have defaults).
