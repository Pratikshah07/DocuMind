# DocuMind

**Turn Documents Into Data.** DocuMind is a full-stack document processing app.
You upload invoices and receipts, and it extracts structured fields with
confidence scores, validates them, stores the results, shows analytics, and
answers questions about your documents with retrieval-augmented generation.

> 🚧 **Work in progress.** The project is being built in phases (see
> [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)).
>
> **Working now:** the React frontend (running on local sample data), and a
> FastAPI backend skeleton with configuration, structured logging, PostgreSQL,
> Alembic and a health endpoint.
>
> **Coming next:** uploads and storage, OCR, extraction, analytics, and RAG chat.

## Stack

| Layer | Tech |
|---|---|
| Frontend | React 19, TypeScript, Vite, Tailwind CSS, shadcn/ui, TanStack Query, Recharts, wouter |
| Backend | Python, FastAPI, Pydantic, SQLAlchemy 2, Alembic |
| Database | PostgreSQL |
| Planned | PyMuPDF, OpenCV, Tesseract OCR, Sentence Transformers, ChromaDB, Ollama |

## Project structure

```
frontend/            React SPA
backend/             FastAPI service (see backend/README.md)
docker/              container init scripts
docker-compose.yml   local PostgreSQL
```

## Quick start

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

## Tests

```bash
cd backend && pytest
cd frontend && npm run build   # typecheck + production build
```
