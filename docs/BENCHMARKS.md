# Benchmarks

Measured on 2026-11-03 on branch `feature/engineering-pass`. These are single-machine
observations to compare changes against. They are **not** production guarantees: the
Render free tier has a shared, slower CPU and sleeps when idle (about a minute to wake).

## Environment

| | |
|---|---|
| Machine | Windows 11 laptop, Intel Core (Tiger Lake, family 6 model 140) |
| Local dev server | Python 3.14.6, Tesseract 5.4, PostgreSQL 16 in Docker, local file storage |
| Staging container | the production image (`Dockerfile`, Python 3.12, Tesseract 5.5), `--memory 512m --cpus 1` to mirror Render free, `STORAGE_BACKEND=database`, `MAX_CONCURRENT_JOBS=1`, demo settings from `render.yaml` |
| Documents | synthetic samples in `backend/samples/` (1–2 pages, 2–280 KB) |

## Reproduce

```bash
python e2e/benchmark_api.py http://127.0.0.1:8090 --runs 3     # API: upload→result, endpoint latency
cd backend && python scripts/evaluate_extraction.py              # per-stage timings + quality, no HTTP
python e2e/mobile_audit.py http://127.0.0.1:8090 --out shots/   # responsive audit
docker stats documind-staging                                   # container memory while the above runs
```

`benchmark_api.py` uses a fresh private workspace and deletes it afterwards. Repeated
uploads of the same sample are flagged as duplicate invoices, so they end in
NEEDS_REVIEW. That is expected and doesn't change the timings.

## Upload → result (staging container, 1 CPU, 512 MB)

Wall time from the upload request until the status endpoint reports a final state
(includes 100 ms status polling). "Job" is the server-side processing time.

| Document | Median s | Min–max s | Job ms (median) |
|---|---|---|---|
| Text PDF, 1 page (01) | 0.90 | 0.68–1.39 | 660 |
| Text PDF, 2 pages (05) | 0.89 | 0.80–0.90 | 634 |
| Scanned PDF, OCR at 300 dpi (12) | 4.27 | 3.50–6.08 | 3,921 |
| Phone photo, cleanup + OCR (13) | 6.79 | 6.08–7.10 | 6,538 |

On the local dev server (no CPU limit) the same runs took 0.6 / 0.7 / 2.9 / 4.7 s.
OCR dominates: preprocessing plus Tesseract is 85–95% of the job time for scans and photos.

## API latency (staging, workspace with 25 documents, 20 requests each)

| Endpoint | Median ms | p95 ms |
|---|---|---|
| `GET /documents` (list) | 22 | 32 |
| `GET /documents/{id}` | 41 | 43 |
| `GET /documents/{id}/extraction` | 40 | 46 |
| `GET /analytics/overview` | 34 | 47 |
| `GET /analytics/quality` | 50 | 67 |

Analytics aggregate in SQL (D59); with the per-workspace cap of 25 documents, query time
is dominated by request overhead rather than data size.

## Memory (staging container, 512 MB limit)

| | Before | After |
|---|---|---|
| Idle after start | 138 MiB | 112 MiB |
| Peak during the benchmark | **510 MiB** (2 MiB below the limit) | **292 MiB** |
| Resident after processing finished | ~390 MiB (never released) | ~227 MiB |

The *before* run showed the API process keeping about 390 MB after the work was done.
That is glibc keeping freed image buffers in per-thread malloc arenas: jobs run on worker
threads. On a 512 MB host that leaves almost nothing for the next photo. Fix (D64):
`MALLOC_ARENA_MAX=2` in the image, plus `malloc_trim(0)` after each processing run. The
fix appears to cost about 0.1–0.2 s on a text-PDF job (median 491 → 660 ms in single
runs, which are noisy at 1 CPU). That was judged worth it for not running out of memory.

The container was not OOM-killed in any run (`docker inspect … OOMKilled=false`).

## Frontend bundle (production build; gzip sizes as reported by Vite)

| Chunk | Before | After |
|---|---|---|
| App code (`index`) | 126.7 kB | 122.7 kB |
| React, router, query (`react`) | 16.9 kB | 18.1 kB |
| Charts (Recharts) | 115.1 kB, **loaded on every page** | 111.4 kB, loaded only by Dashboard/Analytics |
| CSS | 20.0 kB | 20.0 kB |
| **First load of landing / upload / documents** | **~279 kB** | **~161 kB** |

Change (D65): the Dashboard and Analytics pages are `React.lazy` routes, so Recharts is
fetched only when a chart page opens.

## Extraction

Per-sample read/extract timings and quality are in [EVALUATION.md](EVALUATION.md).
Extraction itself (rules plus validation) takes 2–90 ms per document; reading the file
(rendering and OCR) is the cost.
