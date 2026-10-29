# Deploying DocuMind

DocuMind ships as **one Docker image**: the FastAPI API, the built React UI (served
from the same origin, so no CORS setup) and Tesseract OCR. It needs one PostgreSQL
database. Migrations run automatically when the container starts.

## Render (free tier): the reference deployment

`render.yaml` is a Render Blueprint that creates:

| Resource | Plan | Notes |
|---|---|---|
| `documind` web service (Docker) | Free | 512 MB RAM; sleeps after 15 min idle (first request takes ~1 min to wake) |
| `documind-db` PostgreSQL | Free | 1 GB; Render deletes free databases 30 days after creation unless upgraded |

### Steps (about 5 minutes, no payment details needed for the free plan)
1. Sign in at <https://dashboard.render.com> (GitHub sign-in is simplest).
2. **New → Blueprint**, connect GitHub, and pick the `DocuMind` repository.
3. Render reads `render.yaml`. Click **Apply** (no secrets need entering; the database URL is wired automatically).
4. Wait for the first build (~6–10 minutes: Node build, Python wheels, Tesseract).
5. Open the service URL, e.g. `https://documind-xxxx.onrender.com`, and check `/api/health`
   reports `"status": "ok"` with `database` and `ocr` both `ok`.

Every push to `main` redeploys automatically (`autoDeploy: true`).

### Why these settings
- **`STORAGE_BACKEND=database`**: free instances have no persistent disk (the
  filesystem is wiped on every deploy and restart), so uploaded files and previews
  are stored in PostgreSQL. Uploads are capped at 10 MB and deleted after 24 h,
  so the table stays small.
- **`DEMO_MODE=true`**: there are no user accounts. Each browser creates a random
  workspace key; the server stores only its SHA-256 and filters every query by it.
  Visitors cannot see each other's documents. This is anonymous isolation, **not
  authentication**: whoever has a browser's key has that workspace.
- **`RETENTION_HOURS=24`**: documents and files are deleted after a day (swept
  every 15 minutes while the instance is awake, and at start-up).
- **`UPLOAD_RATE_LIMIT_PER_HOUR=20`** per client IP (taken from Render's
  `X-Forwarded-For`, hence `TRUST_PROXY_HEADERS=true`), and **`MAX_DOCUMENTS_PER_WORKSPACE=25`**.
- **`MAX_CONCURRENT_JOBS=1`, `MAX_PAGES=10`**: OCR is memory-hungry, and one job
  at a time fits 512 MB.

## Any other Docker host

```bash
docker build -t documind .
docker run -p 8000:8000 \
  -e DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DB \
  -e DEMO_MODE=true -e RETENTION_HOURS=24 -e UPLOAD_RATE_LIMIT_PER_HOUR=20 \
  -e MAX_DOCUMENTS_PER_WORKSPACE=25 -e STORAGE_BACKEND=database \
  documind
```

- `PORT` is honoured if the platform sets it (Render, Railway, Fly).
- With a persistent volume you can use `STORAGE_BACKEND=local` and mount it at
  `STORAGE_PATH` (default `/app/storage`).
- Behind a reverse proxy, set `TRUST_PROXY_HEADERS=true`; otherwise leave it false
  (clients could spoof `X-Forwarded-For`).
- To run the frontend separately (e.g. on Vercel), build it with
  `VITE_API_BASE_URL=https://your-api.example.com` and set the API's
  `CORS_ORIGINS` to the frontend's origin.

Locally, `docker compose --profile app up -d --build` runs the same image and
settings on <http://127.0.0.1:8080>.

## Smoke test after deploying

```bash
pip install -r backend/requirements-e2e.txt && playwright install chromium
python e2e/run_e2e.py https://YOUR-SERVICE.onrender.com
```

This drives the real UI in Chromium:
- uploads the synthetic samples (a text PDF, a scanned PDF and an invalid file)
- checks extraction, OCR, warnings, an edit that persists after refresh, download,
  delete, workspace isolation and the mobile layout
- deletes everything it uploaded

## Known limitations of this setup

- **Processing runs inside the web process** (FastAPI background tasks):
  - A restart or deploy during processing loses that job. The document stays
    in a processing state until the 15-minute stale timeout, then it can be
    retried from its page.
  - Fine for a low-traffic demo; a real queue (Celery/RQ) would implement the
    existing `JobRunner` interface.
- **Single instance only:** the rate limiter is in memory and per process.
- **Free tier:** the instance sleeps when idle, so the first visit is slow, and
  the free database expires after 30 days.
- **No accounts:** workspace keys live in browser storage. Clearing site data
  loses access to that workspace (its documents expire with retention anyway).
