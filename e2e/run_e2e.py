"""DocuMind browser end-to-end test / deployment smoke test.

Drives the real UI in Chromium against a running deployment (local container or the
public URL) using the synthetic samples in backend/samples. A fresh browser context
means a fresh private workspace; everything uploaded is deleted at the end.

    pip install -r backend/requirements-e2e.txt && playwright install chromium
    python e2e/run_e2e.py http://127.0.0.1:8080 [--screenshots DIR] [--headed]
"""

import argparse
import re
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "backend" / "samples"
PROCESS_TIMEOUT = 180_000  # ms; first OCR on a cold free-tier instance can be slow

results: list[tuple[str, bool, str]] = []


def step(name: str):
    def wrap(fn):
        def run(*args, **kwargs):
            started = time.perf_counter()
            try:
                detail = fn(*args, **kwargs) or ""
                results.append((name, True, f"{detail} ({time.perf_counter() - started:.1f}s)"))
                print(f"PASS  {name}  {detail}")
            except Exception as exc:  # noqa: BLE001 - report and continue to the next step
                results.append((name, False, f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}"))
                print(f"FAIL  {name}  {type(exc).__name__}: {str(exc).splitlines()[0][:200]}")

        return run

    return wrap


def upload_and_wait(page: Page, path: Path) -> str:
    """Upload through the UI; return the document id once the server reports a terminal status."""
    page.goto("/app/upload")
    page.get_by_test_id("input-upload-files").set_input_files(str(path))
    link = page.locator('[data-testid^="link-open-"]').first
    expect(link).to_be_visible(timeout=60_000)
    document_id = (link.get_attribute("data-testid") or "").removeprefix("link-open-")
    item = page.get_by_test_id(f"upload-item-{document_id}")
    expect(item.locator('[data-testid="status-completed"], [data-testid="status-needs_review"], [data-testid="status-failed"]')).to_be_visible(timeout=PROCESS_TIMEOUT)
    return document_id


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url")
    parser.add_argument("--screenshots", default=str(Path(tempfile.gettempdir()) / "documind-e2e"))
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    shots = Path(args.screenshots)
    shots.mkdir(parents=True, exist_ok=True)
    console_errors: list[str] = []
    docs: dict[str, str] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        context = browser.new_context(base_url=args.base_url.rstrip("/"), viewport={"width": 1440, "height": 1000}, accept_downloads=True)
        page = context.new_page()
        page.set_default_timeout(30_000)
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))

        @step("1. Landing page loads")
        def landing():
            page.goto("/")
            expect(page).to_have_title(re.compile("DocuMind"))
            expect(page.get_by_role("heading", name=re.compile("Turn Documents"))).to_be_visible()
            page.screenshot(path=shots / "01-landing.png")

        @step("2. Health endpoint")
        def health():
            body = page.request.get("/api/health").json()
            assert body["status"] == "ok", body
            return f"database={body['components']['database']['status']} ocr={body['components']['ocr']['status']}"

        @step("3. Empty workspace shows empty states")
        def empty():
            page.goto("/app/dashboard")
            expect(page.get_by_test_id("state-empty")).to_be_visible()
            expect(page.get_by_test_id("status-server")).to_have_text("Connected")
            page.goto("/app/analytics")
            expect(page.get_by_text("No analytics yet")).to_be_visible()
            page.screenshot(path=shots / "03-empty-analytics.png")

        @step("4. Upload text PDF → processed")
        def text_pdf():
            docs["standard"] = upload_and_wait(page, SAMPLES / "01_invoice_standard.pdf")
            expect(page.get_by_test_id(f"upload-item-{docs['standard']}").get_by_test_id("status-completed")).to_be_visible()
            page.screenshot(path=shots / "04-upload.png")

        @step("5. Extracted fields, line items and preview shown")
        def detail():
            page.goto(f"/app/documents/{docs['standard']}")
            expect(page.get_by_test_id("input-field-invoice_number")).to_have_value("NS-1048")
            expect(page.get_by_test_id("input-field-total")).to_have_value("4,820.00")
            expect(page.get_by_test_id("input-field-vendor_name")).to_have_value("Northstar Studio LLC")
            expect(page.get_by_test_id("line-item-2")).to_be_visible()
            image = page.get_by_test_id("img-page-preview")
            expect(image).to_be_visible()
            assert image.evaluate("img => img.naturalWidth") > 0, "preview image empty"
            page.screenshot(path=shots / "05-detail.png", full_page=True)

        @step("6. Scanned PDF goes through OCR")
        def scanned():
            docs["scanned"] = upload_and_wait(page, SAMPLES / "12_scanned_invoice.pdf")
            page.goto(f"/app/documents/{docs['scanned']}")
            expect(page.get_by_text(re.compile(r"page text from OCR"))).to_be_visible()
            expect(page.get_by_test_id("input-field-invoice_number")).to_have_value("NS-1048")
            return "invoice number read via OCR"

        @step("7. Invalid file shows a useful error")
        def invalid():
            fake = Path(tempfile.gettempdir()) / "not-really.pdf"
            fake.write_bytes(b"<html>this is not a pdf</html>")
            page.goto("/app/upload")
            page.get_by_test_id("input-upload-files").set_input_files(str(fake))
            expect(page.get_by_text("File content is not a valid PDF, PNG or JPEG.")).to_be_visible()

        @step("8. NEEDS_REVIEW document shows its warning")
        def review():
            docs["mismatch"] = upload_and_wait(page, SAMPLES / "07_totals_dont_add_up.pdf")
            page.goto(f"/app/documents/{docs['mismatch']}")
            expect(page.get_by_test_id("banner-review")).to_be_visible()
            expect(page.get_by_test_id("warning-totals_mismatch")).to_contain_text("Totals don’t add up".replace("’", "'"))
            page.screenshot(path=shots / "08-review.png", full_page=True)

        @step("9. Invalid edit → 422 shown, input kept")
        def invalid_edit():
            page.goto(f"/app/documents/{docs['mismatch']}")
            field = page.get_by_test_id("input-field-invoice_date")
            field.fill("31/02/2025")
            page.get_by_test_id("button-save-document").click()
            expect(page.get_by_test_id("error-field-invoice_date")).to_contain_text("Not a valid date")
            expect(field).to_have_value("31/02/2025")

        @step("10. Edit + save → persists after refresh")
        def edit():
            page.goto(f"/app/documents/{docs['mismatch']}")
            page.get_by_test_id("input-field-total").fill("2195.00")
            page.get_by_test_id("button-save-document").click()
            expect(page.get_by_test_id("status-toast").first).to_contain_text("Saved")
            page.reload()
            expect(page.get_by_test_id("input-field-total")).to_have_value("2195.00")
            expect(page.get_by_test_id("status-completed").first).to_be_visible()
            expect(page.get_by_test_id("banner-review")).to_have_count(0)
            return "total corrected; status Ready after reload"

        @step("10a. Reprocess keeps the correction; history records it")
        def reprocess_keeps_edit():
            page.goto(f"/app/documents/{docs['mismatch']}")
            page.get_by_test_id("button-reprocess").click()
            expect(page.get_by_test_id("checkbox-discard-corrections")).not_to_be_checked()
            page.get_by_test_id("button-confirm-reprocess").click()
            expect(page.get_by_test_id("input-field-total")).to_have_value("2195.00", timeout=PROCESS_TIMEOUT)
            expect(page.get_by_test_id("status-completed").first).to_be_visible()
            history = page.get_by_test_id("section-edit-history")
            history.locator("summary").click()
            expect(history).to_contain_text("2,295.00")
            return "correction re-applied after re-extraction"

        @step("10b. Duplicate upload is detected, not stored twice")
        def duplicate():
            page.goto("/app/upload")
            page.get_by_test_id("input-upload-files").set_input_files(str(SAMPLES / "01_invoice_standard.pdf"))
            expect(page.get_by_test_id("text-duplicate")).to_be_visible(timeout=60_000)
            expect(page.get_by_test_id("link-open-existing")).to_have_attribute("href", f"/app/documents/{docs['standard']}")

        @step("11. Download original file")
        def download():
            page.goto(f"/app/documents/{docs['standard']}")
            with page.expect_download() as info:
                page.get_by_test_id("button-download-document").click()
            path = info.value.path()
            assert Path(path).read_bytes()[:5] == b"%PDF-"
            return info.value.suggested_filename

        @step("12. Dashboard, list and analytics use real records")
        def dashboards():
            page.goto("/app/documents")
            expect(page.get_by_test_id("text-document-count")).to_have_text("3 documents")
            page.goto("/app/dashboard")
            expect(page.get_by_test_id("metric-total-documents")).to_contain_text("3")
            page.goto("/app/analytics")
            expect(page.get_by_test_id("metric-total-spending")).to_contain_text("$")
            page.screenshot(path=shots / "12-analytics.png", full_page=True)

        @step("13. Chat is honestly marked as not available")
        def chat():
            page.goto("/app/chat")
            expect(page.get_by_test_id("chat-coming-soon")).to_be_visible()

        @step("14. Delete a document")
        def delete():
            page.goto(f"/app/documents/{docs['scanned']}")
            page.get_by_test_id("button-delete-document").click()
            page.get_by_test_id("button-confirm-delete").click()
            expect(page).to_have_url(re.compile(r"/app/documents$"))
            expect(page.get_by_test_id("text-document-count")).to_have_text("2 documents")
            token = page.evaluate("localStorage.getItem('documind-workspace-token')")
            gone = page.request.get(f"/api/documents/{docs['scanned']}", headers={"X-Workspace-Token": token})
            assert gone.status == 404, gone.status

        @step("15. Workspaces are private (other browser sees nothing)")
        def isolation():
            other = browser.new_context(base_url=args.base_url.rstrip("/")).new_page()
            other.goto("/app/documents")
            expect(other.get_by_test_id("text-document-count")).to_have_text("0 documents")
            other.context.close()

        @step("16. Mobile layout has no horizontal overflow")
        def mobile():
            mobile_page = context.new_page()
            mobile_page.set_viewport_size({"width": 390, "height": 844})
            for path in ("/", "/app/dashboard", f"/app/documents/{docs['standard']}", "/app/upload"):
                mobile_page.goto(path)
                mobile_page.wait_for_load_state("networkidle")
                overflow = mobile_page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
                assert overflow <= 1, f"{path} overflows by {overflow}px"
            mobile_page.screenshot(path=shots / "16-mobile-detail.png", full_page=True)
            mobile_page.close()

        @step("17. Clean up: delete all test documents")
        def cleanup():
            page.goto("/app/settings")
            page.get_by_test_id("button-delete-all").click()
            page.get_by_test_id("button-confirm-delete-all").click()
            expect(page.get_by_test_id("status-toast").last).to_contain_text("Deleted")
            page.goto("/app/documents")
            expect(page.get_by_test_id("text-document-count")).to_have_text("0 documents")

        for test in (landing, health, empty, text_pdf, detail, scanned, invalid, review, invalid_edit, edit,
                     reprocess_keeps_edit, duplicate, download,
                     dashboards, chat, delete, isolation, mobile, cleanup):
            test()
        browser.close()

    # 4xx responses we trigger on purpose show up as "Failed to load resource" console messages.
    expected = re.compile(r"Failed to load resource: the server responded with a status of (404|409|415|422)")
    unexpected = [e for e in console_errors if not expected.search(e)]
    results.append(("18. No unexpected browser console errors", not unexpected, "; ".join(unexpected[:3]) or "none"))
    print(f"{'PASS' if not unexpected else 'FAIL'}  18. No unexpected browser console errors  {unexpected[:3] or ''}")

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed. Screenshots: {shots}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
