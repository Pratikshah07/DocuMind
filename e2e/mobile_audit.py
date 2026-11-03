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
        # Two real phone profiles plus in-between widths (small Android, tablet, small laptop).
        profiles = {
            "iPhone 13": p.devices["iPhone 13"],
            "Galaxy S9+": p.devices["Galaxy S9+"],
            "small-360": {"viewport": {"width": 360, "height": 740}, "is_mobile": True, "has_touch": True,
                          "device_scale_factor": 2},
            "tablet-768": {"viewport": {"width": 768, "height": 1024}, "is_mobile": True, "has_touch": True},
            "laptop-1024": {"viewport": {"width": 1024, "height": 768}},
        }  # fmt: skip
        for device_name, device in profiles.items():
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
            # Mobile navigation drawer (below the lg breakpoint).
            page.goto("/app/dashboard")
            if page.get_by_test_id("button-open-menu").is_visible():
                page.get_by_test_id("button-open-menu").click()
                page.wait_for_timeout(300)
                page.screenshot(path=out / f"{slug}-menu.png")
                report[f"{slug}:menu"] = page.evaluate(CHECK_JS)

            # The sticky Save/Discard bar must never cover content: scrolled to the bottom, the
            # last element of the page has to end above the bar.
            page.goto(f"/app/documents/{ids[1]}")
            page.get_by_test_id("input-field-total").fill("2195.00")
            bar = page.get_by_test_id("bar-mobile-save")
            if bar.is_visible():
                page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
                page.wait_for_timeout(300)
                covered = page.evaluate(
                    """() => {
                      const bar = document.querySelector('[data-testid=bar-mobile-save]').getBoundingClientRect();
                      const items = [...document.querySelectorAll('main button, main input, main summary, main a')]
                        .filter((el) => el.offsetParent !== null && !el.closest('[data-testid=bar-mobile-save]'));
                      const last = items.reduce((a, b) => (b.getBoundingClientRect().bottom > a.getBoundingClientRect().bottom ? b : a));
                      return Math.max(0, Math.round(last.getBoundingClientRect().bottom - bar.top));
                    }"""
                )
                report[f"{slug}:save-bar"] = {"coveredPx": covered}
                page.screenshot(path=out / f"{slug}-save-bar.png")

            token = page.evaluate("localStorage.getItem('documind-workspace-token')")
            page.request.delete("/api/documents", headers={"X-Workspace-Token": token})
            context.close()
        browser.close()

    print(json.dumps(report, indent=1))
    # Hard failures: page-level sideways scrolling, elements wider than the screen, a covering bar.
    failures = [
        key
        for key, r in report.items()
        if r.get("overflowPx", 0) > 1 or r.get("wide") or r.get("coveredPx", 0) > 0
    ]
    print(f"{len(report)} views audited; hard failures: {failures or 'none'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
