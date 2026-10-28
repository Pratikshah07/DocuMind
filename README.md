# DocuMind

**Turn Documents Into Data.** DocuMind is a full-stack document processing app.
You upload invoices and receipts, and it extracts structured fields with
confidence scores, validates them, stores the results, shows analytics, and
answers questions about your documents with retrieval-augmented generation.

> 🚧 **Work in progress.** The project is being built in phases (see
> [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)).
>
> **Working now:** the React frontend (running on local sample data), and a
> FastAPI backend with PostgreSQL and Alembic. The backend:
> - validates uploads by their content and stores them
> - processes them in the background: reads PDF text layers (PyMuPDF), and
>   preprocesses (OpenCV) and OCRs (Tesseract) scans and photos
> - classifies each invoice or receipt, and extracts its fields and line items
>   with deterministic rules
> - validates dates, formats and totals, attaches transparent confidence
>   scores, and flags documents that need review
> - lets you correct extracted values through the API
>
> **Coming next:** connecting the frontend, analytics, and RAG chat.

## Stack

| Layer | Tech |
|---|---|
| Frontend | React 19, TypeScript, Vite, Tailwind CSS, shadcn/ui, TanStack Query, Recharts, wouter |
| Backend | Python, FastAPI, Pydantic, SQLAlchemy 2, Alembic |
| Database | PostgreSQL |
| Document processing | PyMuPDF, Pillow, OpenCV, Tesseract OCR (pytesseract) |
| Planned | Sentence Transformers, ChromaDB, Ollama |

## Project structure

```
frontend/            React SPA
backend/             FastAPI service (see backend/README.md)
docker/              container init scripts
docker-compose.yml   local PostgreSQL
```

## Quick start

Prerequisites: Python 3.12+, Node 20+, Docker, and Tesseract OCR
(Windows: `winget install UB-Mannheim.TesseractOCR`; macOS: `brew install tesseract`).

```bash
# Database
docker compose up -d postgres

# Backend: http://127.0.0.1:8000/docs
cd backend
python -m venv .venv && .venv/Scripts/activate   # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# Frontend: http://localhost:5173
cd frontend
npm install
npm run dev
```

Sample invoices and receipts to upload are in [`backend/samples/`](backend/samples/).

## Tests

```bash
cd backend && pytest
cd frontend && npm run build   # typecheck + production build
```
