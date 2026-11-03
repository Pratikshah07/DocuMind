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
- **`RETENTION_HOURS=24`**: documents and files are deleted after a day. The
  maintenance loop sweeps every 15 minutes while the instance is awake, and at
  start-up; it also removes orphaned files and recovers interrupted jobs.
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

## Release process (keep the live site safe)

`main` is production: Render redeploys every push to it. Work happens on a feature
branch and reaches `main` only after these gates pass:

1. **Backend:** `pytest` on SQLite and on PostgreSQL, `ruff check`, `ruff format --check`,
   `alembic check`, and `python scripts/evaluate_extraction.py`.
2. **Frontend:** `npm test` and `npm run build`.
3. **Staging:** the production image, run locally under the same constraints as Render free:

   ```bash
   docker build -t documind:staging .
   # A throwaway database, first migrated to the revision production is on
   # (check its alembic_version), plus a row, so the upgrade path is tested.
   docker exec documind-postgres-1 psql -U documind -d documind -c "CREATE DATABASE documind_staging"
   (cd backend && alembic -x url=postgresql+psycopg://documind:documind@127.0.0.1:5432/documind_staging upgrade 0002)
   docker run -d --name documind-staging --memory 512m --cpus 1 -p 8090:8000 -e PORT=8000      -e DATABASE_URL=postgres://documind:documind@host.docker.internal:5432/documind_staging      -e DEMO_MODE=true -e RETENTION_HOURS=24 -e MAX_DOCUMENTS_PER_WORKSPACE=25      -e MAX_UPLOAD_SIZE=10485760 -e MAX_PAGES=10 -e MAX_CONCURRENT_JOBS=1      -e STORAGE_BACKEND=database -e TRUST_PROXY_HEADERS=true documind:staging
   python e2e/run_e2e.py http://127.0.0.1:8090
   python e2e/mobile_audit.py http://127.0.0.1:8090 --out shots/
   python e2e/benchmark_api.py http://127.0.0.1:8090   # watch `docker stats` for memory
   ```
4. **Merge** the branch into `main` (a normal merge, no history rewrite) and push.
   Render builds and deploys; the container applies migrations before serving.
5. **Verify production:** run `python e2e/run_e2e.py https://documind-klhw.onrender.com`
   and check that `/api/health` shows `database` and `ocr` as `ok`.

## Migrations

- They run automatically at container start (`alembic upgrade head`). A failed
  migration stops the deploy, so Render keeps the previous version serving.
- Every revision so far is additive (new tables, columns with server defaults,
  indexes). Each one is tested upgrading a populated database and on a down/up round trip.
- Never test a migration against the production database; use a copy or the staging
  recipe above.

## Rollback

- **Code:** in the Render dashboard, open the service, go to **Events** / **Deploys**,
  pick the last good deploy and choose **Rollback**. Alternatively, `git revert` the
  merge commit on `main` and push, which keeps history intact.
- **Schema:** migrations are additive, so the previous code version runs fine on the
  newer schema; a database rollback is normally unnecessary. If one is required,
  run `alembic downgrade <revision>` from a shell with the production `DATABASE_URL`,
  after taking a backup. Downgrading 0003 → 0002 drops the correction history
  (`extraction_edits`) and two indexes.

## Backups and data lifetime

- **The free Render PostgreSQL has no automatic backups, and Render deletes free
  databases 30 days after creation** unless upgraded. For this deployment that is
  about 30 days after the end of October 2026; check the date shown in the dashboard.
  Upgrade the database (or recreate it and redeploy) before then.
- Manual backup with the database's *External Database URL* (Render dashboard →
  database → Connect): `pg_dump --format=custom "$EXTERNAL_URL" > documind.dump`.
  Restore with `pg_restore --clean --no-owner -d "$NEW_URL" documind.dump`.
- Demo uploads expire after 24 h anyway (`RETENTION_HOURS`), and files live in the
  same database (`STORAGE_BACKEND=database`), so one dump captures everything.

## Resource notes

- **Memory:** one photo OCR peaked at about 290 MiB in a 512 MB container after D64
  (`MALLOC_ARENA_MAX=2` and `malloc_trim` after each job); before that fix it reached
  510 MiB. Keep `MAX_CONCURRENT_JOBS=1` on 512 MB. See [BENCHMARKS.md](BENCHMARKS.md).
- **Optional LLM:** it needs a separate machine or service running Ollama, with about
  4 GB RAM for a 3B model. Render free cannot host one.
  - To enable it, run Ollama on a private host and set `LLM_PROVIDER=ollama`,
    `OLLAMA_URL` and `OLLAMA_MODEL`. Expect several seconds per document on CPU.
  - Documents are sent to that host, so it must be one you control.
  - The demo leaves this off.

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
  - A restart or deploy during processing loses that job. At start-up the job is
    marked `interrupted` and the document shows a Retry button (D50).
  - Fine for a low-traffic demo; a real queue (Celery/RQ) would implement the
    existing `JobRunner` interface.
- **Single instance only:** the rate limiter is in memory and per process.
- **Free tier:** the instance sleeps when idle, so the first visit is slow, and
  the free database expires after 30 days.
- **No accounts:** workspace keys live in browser storage. Clearing site data
  loses access to that workspace (its documents expire with retention anyway).
