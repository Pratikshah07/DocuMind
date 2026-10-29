"""Mobile layout audit: screenshots + automatic checks on phone-sized viewports.

Uploads a few synthetic samples into a fresh workspace, then visits every page on
emulated phones and reports horizontal overflow, elements wider than the screen,
tap targets smaller than 40 px, and text smaller than 11 px. Cleans up afterwards.

    python e2e/mobile_audit.py http://127.0.0.1:8000 --out DIR
"""

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "backend" / "samples"

CHECK_JS = """
() => {
  const vw = window.innerWidth;
  const issues = { overflowPx: document.documentElement.scrollWidth - vw, wide: [], smallTargets: [], tinyText: 0 };
  const label = (el) => (el.getAttribute('data-testid') || el.getAttribute('aria-label') || el.textContent || el.tagName).trim().slice(0, 40);
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    const style = getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none') continue;
    // Elements sticking out of the viewport (ignore ones inside an intentional horizontal scroller).
    let scroller = false;
    for (let p = el.parentElement; p; p = p.parentElement) {
      const o = getComputedStyle(p).overflowX;
      if (o === 'auto' || o === 'scroll' || o === 'hidden') { scroller = true; break; }
    }
    if (!scroller && (r.right > vw + 1 || r.left < -1) && issues.wide.length < 8) issues.wide.push(`${label(el)} [${Math.round(r.left)}..${Math.round(r.right)}]`);
    const interactive = el.matches('a, button, input, select, textarea, [role=switch]');
    if (interactive && r.top < document.documentElement.scrollHeight && (r.height < 40 || r.width < 40) && el.type !== 'file' && !el.classList.contains('sr-only') && issues.smallTargets.length < 15) {
      issues.smallTargets.push(`${label(el)} ${Math.round(r.width)}x${Math.round(r.height)}`);
    }
    if (el.childNodes.length && [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()) && parseFloat(style.fontSize) < 11) issues.tinyText++;
  }
  return issues;
}
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = {}

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for device_name in ("iPhone 13", "Galaxy S9+"):
            device = p.devices[device_name]
            context = browser.new_context(**device, base_url=args.base_url.rstrip("/"))
            page = context.new_page()
            page.set_default_timeout(60_000)

            # Seed this workspace with real processed documents.
            ids = []
            for name in ("01_invoice_standard.pdf", "07_totals_dont_add_up.pdf", "02_receipt_coffee.pdf"):
                page.goto("/app/upload")
                page.get_by_test_id("input-upload-files").set_input_files(str(SAMPLES / name))
                link = page.locator('[data-testid^="link-open-"]').first
                link.wait_for()
                ids.append((link.get_attribute("data-testid") or "").removeprefix("link-open-"))
                page.wait_for_selector('[data-testid="status-completed"], [data-testid="status-needs_review"]', timeout=120_000)

            pages = {
                "landing": "/",
                "dashboard": "/app/dashboard",
                "documents": "/app/documents",
                "upload": "/app/upload",
                "detail": f"/app/documents/{ids[0]}",
                "detail-review": f"/app/documents/{ids[1]}",
                "analytics": "/app/analytics",
                "settings": "/app/settings",
                "chat": "/app/chat",
            }
            slug = device_name.replace(" ", "").replace("+", "plus")
            for key, path in pages.items():
                page.goto(path)
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(1200)  # let charts finish animating
                report[f"{slug}:{key}"] = page.evaluate(CHECK_JS)
                page.screenshot(path=out / f"{slug}-{key}.png", full_page=True)
            # Mobile navigation drawer.
            page.goto("/app/dashboard")
            page.get_by_test_id("button-open-menu").click()
            page.wait_for_timeout(300)
            page.screenshot(path=out / f"{slug}-menu.png")
            report[f"{slug}:menu"] = page.evaluate(CHECK_JS)

            token = page.evaluate("localStorage.getItem('documind-workspace-token')")
            page.request.delete("/api/documents", headers={"X-Workspace-Token": token})
            context.close()
        browser.close()

    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
