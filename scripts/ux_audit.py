"""UX audit — systematically screenshot and capture state of every page."""

from __future__ import annotations
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path("/root/project/ai/vnpy/.playwright-cli")
OUT.mkdir(exist_ok=True)


def audit():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()

        # Collect console errors
        console_errors: list[str] = []
        page.on("console", lambda msg: console_errors.append(f"[{msg.type}] {msg.text}") if msg.type in ("error", "warning") else None)

        # Collect failed network requests
        failed_requests: list[dict] = []
        page.on("requestfailed", lambda req: failed_requests.append({"url": req.url, "failure": req.failure}))

        # ── Page 1: Home / Market Overview ──
        print("=== 1. Home Page ===")
        page.goto("http://localhost:5173/", wait_until="networkidle", timeout=20000)
        page.screenshot(path=str(OUT / "audit-home.png"), full_page=True)
        home_html = page.content()
        home_text = page.locator("body").inner_text()
        print(f"  Title: {page.title()}")
        print(f"  Body text length: {len(home_text)}")
        print(f"  Console errors so far: {len(console_errors)}")

        # ── Page 2: Stocks ──
        print("\n=== 2. Stocks Page ===")
        page.goto("http://localhost:5173/stocks", wait_until="networkidle", timeout=20000)
        page.screenshot(path=str(OUT / "audit-stocks.png"), full_page=True)
        stocks_text = page.locator("body").inner_text()
        print(f"  Body text (first 300): {stocks_text[:300]}")
        # Check if there's a search input
        search_inputs = page.locator("input").all()
        print(f"  Input fields: {len(search_inputs)}")
        for i, inp in enumerate(search_inputs):
            placeholder = inp.get_attribute("placeholder") or ""
            print(f"    input[{i}]: placeholder='{placeholder}'")

        # ── Page 3: Stock Detail (浦发银行 600000.SSE) ──
        print("\n=== 3. Stock Detail 600000.SSE ===")
        page.goto("http://localhost:5173/stocks/600000.SSE", wait_until="networkidle", timeout=20000)
        page.wait_for_timeout(3000)  # Wait for charts to render
        page.screenshot(path=str(OUT / "audit-stock-detail.png"), full_page=True)
        detail_text = page.locator("body").inner_text()
        print(f"  Body text (first 500): {detail_text[:500]}")
        # Check for tabs
        tabs = page.locator("[role='tab'], button[class*='tab']").all()
        print(f"  Tab buttons found: {len(tabs)}")
        for t in tabs:
            print(f"    tab: '{t.inner_text()}'")

        # ── Page 4: Sectors ──
        print("\n=== 4. Sectors Page ===")
        page.goto("http://localhost:5173/sectors", wait_until="networkidle", timeout=20000)
        page.screenshot(path=str(OUT / "audit-sectors.png"), full_page=True)
        sectors_text = page.locator("body").inner_text()
        print(f"  Body text (first 500): {sectors_text[:500]}")

        # Try searching for "半导体"
        search_input = page.locator("input").first
        if search_input.is_visible():
            search_input.fill("半导体")
            page.wait_for_timeout(2000)
            page.screenshot(path=str(OUT / "audit-sectors-search.png"), full_page=True)
            results_text = page.locator("body").inner_text()
            print(f"  After search '半导体' (first 500): {results_text[:500]}")
        else:
            print("  No search input visible")

        # ── Page 5: Data Status ──
        print("\n=== 5. Data Status ===")
        page.goto("http://localhost:5173/data", wait_until="networkidle", timeout=20000)
        page.screenshot(path=str(OUT / "audit-data.png"), full_page=True)
        data_text = page.locator("body").inner_text()
        print(f"  Body text (first 300): {data_text[:300]}")

        # ── Page 6: Data Sync ──
        print("\n=== 6. Data Sync ===")
        page.goto("http://localhost:5173/data-sync", wait_until="networkidle", timeout=20000)
        page.screenshot(path=str(OUT / "audit-data-sync.png"), full_page=True)
        sync_text = page.locator("body").inner_text()
        print(f"  Body text (first 300): {sync_text[:300]}")

        # ── Page 7: Test stock that might have issues ──
        print("\n=== 7. Stock Detail 999999 (edge case) ===")
        page.goto("http://localhost:5173/stocks/999999.SSE", wait_until="networkidle", timeout=20000)
        page.screenshot(path=str(OUT / "audit-stock-invalid.png"), full_page=True)
        invalid_text = page.locator("body").inner_text()
        print(f"  Body text (first 300): {invalid_text[:300]}")

        # ── Collect all errors ──
        print("\n=== Console Errors/Warnings ===")
        for e in console_errors:
            print(f"  {e}")

        print(f"\n=== Failed Requests ({len(failed_requests)}) ===")
        for r in failed_requests:
            print(f"  {r['url']} -> {r['failure']}")

        # Save full error log
        (OUT / "audit-console.log").write_text("\n".join(console_errors))
        (OUT / "audit-failed-requests.json").write_text(json.dumps(failed_requests, indent=2, ensure_ascii=False))

        browser.close()
        print("\nDone! Screenshots saved to .playwright-cli/")


if __name__ == "__main__":
    audit()
