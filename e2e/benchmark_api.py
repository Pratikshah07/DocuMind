"""Reproducible API benchmark against a running DocuMind (local, staging container or live).

Measures, in a fresh private workspace that is deleted afterwards:
- upload → terminal status, per synthetic sample (text PDF, scanned PDF, photo), N runs each;
- list / detail / extraction / analytics request latency with the workspace filled to 25
  documents (the public demo's per-workspace cap).

    python e2e/benchmark_api.py http://127.0.0.1:8000 [--runs 3]

Numbers depend on the machine and its load; report them with the environment, and do not
read them as production guarantees.
"""

import argparse
import base64
import os
import platform
import statistics
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

SAMPLES = Path(__file__).resolve().parents[1] / "backend" / "samples"
TIMED = {
    "text PDF (01, 1 page)": ("01_invoice_standard.pdf", "application/pdf"),
    "text PDF (05, 2 pages)": ("05_invoice_multi_page.pdf", "application/pdf"),
    "scanned PDF (12, OCR)": ("12_scanned_invoice.pdf", "application/pdf"),
    "phone photo (13, OCR + cleanup)": ("13_invoice_photo.jpg", "image/jpeg"),
}
FILLER = [f"{i:02d}_" for i in range(2, 12)]  # text samples used to fill the workspace


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url")
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    token = base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")

    with sync_playwright() as p:
        api = p.request.new_context(
            base_url=args.base_url.rstrip("/"), extra_http_headers={"X-Workspace-Token": token}, timeout=300_000
        )

        def upload(name: str, mime: str) -> str:
            body = {"file": {"name": name, "mimeType": mime, "buffer": (SAMPLES / name).read_bytes()}}
            response = api.post("/api/documents/upload?allow_duplicate=true", multipart=body)
            assert response.status == 202, response.text()
            return response.json()["id"]

        def wait(document_id: str) -> str:
            while True:
                status = api.get(f"/api/documents/{document_id}/status").json()["status"]
                if status in ("COMPLETED", "NEEDS_REVIEW", "FAILED"):
                    return status
                time.sleep(0.1)

        print(f"Target: {args.base_url}  client: {platform.platform()}, Python {platform.python_version()}")
        print("\n| Document | Runs | Median s | Min s | Max s | Server job ms (median) | Result |")
        print("|---|---|---|---|---|---|---|")
        ids = []
        for label, (name, mime) in TIMED.items():
            wall, job = [], []
            for _ in range(args.runs):
                started = time.perf_counter()
                document_id = upload(name, mime)
                result = wait(document_id)
                wall.append(time.perf_counter() - started)
                job.append(api.get(f"/api/documents/{document_id}/status").json()["job"]["duration_ms"])
                ids.append(document_id)
            print(
                f"| {label} | {args.runs} | {statistics.median(wall):.2f} | {min(wall):.2f} | {max(wall):.2f} "
                f"| {int(statistics.median(job))} | {result} |"
            )

        fillers = sorted(p.name for p in SAMPLES.glob("*.pdf") if p.name[:3] in FILLER)
        while len(ids) < 25:
            ids.append(upload(fillers[len(ids) % len(fillers)], "application/pdf"))
        for document_id in ids:
            wait(document_id)

        endpoints = {
            "GET /documents (list)": "/api/documents?limit=50",
            "GET /documents/{id}": f"/api/documents/{ids[0]}",
            "GET /documents/{id}/extraction": f"/api/documents/{ids[0]}/extraction",
            "GET /analytics/overview": "/api/analytics/overview",
            "GET /analytics/quality": "/api/analytics/quality",
        }
        print(f"\nWorkspace: {len(ids)} documents. 20 requests per endpoint after one warm-up.\n")
        print("| Endpoint | Median ms | p95 ms |")
        print("|---|---|---|")
        for label, path in endpoints.items():
            api.get(path)
            times = []
            for _ in range(20):
                started = time.perf_counter()
                assert api.get(path).ok
                times.append((time.perf_counter() - started) * 1000)
            times.sort()
            print(f"| {label} | {statistics.median(times):.0f} | {times[18]:.0f} |")

        api.delete("/api/documents")
        api.dispose()


if __name__ == "__main__":
    main()
