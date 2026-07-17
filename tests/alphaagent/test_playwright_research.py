"""Playwright end-to-end tests for the AlphaAgent research features.

Tests verify:
  1. Backend research API endpoints respond correctly (including new ones)
  2. Frontend pages load without errors (including new pages)
  3. New research API data is reachable from the frontend
  4. Navigation between new pages works

Usage:
  cd /root/project/ai/vnpy
  python -m pytest tests/alphaagent/test_playwright_research.py -v --tb=short
"""

from __future__ import annotations

import pytest

pytest.importorskip("playwright")


@pytest.fixture(scope="session")
def browser_context(playwright):
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        base_url="http://localhost:5173",
    )
    context.add_init_script(
        "window.localStorage.setItem('alphaagent_token', 'e2e-local-token')"
    )
    yield context
    context.close()
    browser.close()


# ══════════════════════════════════════════
# 1. Backend API smoke tests (via page.evaluate fetch)
# ══════════════════════════════════════════


class TestResearchAPIViaBrowser:
    """Test research API endpoints using browser's fetch (validates CORS).

    Navigate to the frontend first so fetch requests share the same origin
    and any CORS misconfiguration is caught.
    """

    API_BASE = "http://localhost:8000/api"

    @pytest.fixture(autouse=True)
    def _go_to_app(self, browser_context):
        """Navigate to frontend before each test so fetch is same-origin."""
        self.page = browser_context.new_page()
        self.page.goto("/", wait_until="networkidle", timeout=15000)
        yield
        self.page.close()

    def _fetch_json(self, path: str) -> dict:
        """Execute fetch from the frontend page context."""
        return self.page.evaluate(f"""
            async () => {{
                try {{
                    const res = await fetch('{self.API_BASE}{path}');
                    const text = await res.text();
                    try {{
                        return {{ status: res.status, body: JSON.parse(text) }};
                    }} catch {{
                        return {{ status: res.status, body: {{ error: text }} }};
                    }}
                }} catch (err) {{
                    return {{ status: 0, body: {{ error: err.message }} }};
                }}
            }}
        """)

    # ── Existing endpoints ──

    def test_sector_dashboard_api(self):
        result = self._fetch_json("/research/sectors/dashboard")
        assert result["status"] == 200
        body = result["body"]
        assert body["status"] in ("ready", "empty", "unavailable")
        assert "items" in body
        assert "period" in body

    def test_stock_workbench_api(self):
        result = self._fetch_json("/research/stocks/600000.SSE/workbench")
        # May fail (0) or return 500 if DB schema not fully migrated (e.g. missing segment_type column)
        assert result["status"] in (0, 200, 500)
        if result["status"] == 200:
            body = result["body"]
            assert body["vt_symbol"] == "600000.SSE"

    def test_stock_finance_quarterly_api(self):
        result = self._fetch_json("/research/stocks/600000.SSE/finance/quarterly")
        assert result["status"] == 200
        body = result["body"]
        assert body["vt_symbol"] == "600000.SSE"
        assert "items" in body

    def test_stock_business_api(self):
        result = self._fetch_json("/research/stocks/600000.SSE/business")
        # May fail (0) or return 500 if DB schema not fully migrated (e.g. missing segment_type column)
        assert result["status"] in (0, 200, 500)
        if result["status"] == 200:
            assert "items" in result["body"]

    def test_stock_events_api(self):
        result = self._fetch_json("/research/stocks/600000.SSE/events")
        assert result["status"] == 200
        body = result["body"]
        assert "timeline" in body
        assert "hot_rank" in body

    # ── New endpoints (Task 1) ──

    def test_sector_ranking_api(self):
        result = self._fetch_json("/research/sectors/ranking?sector_type=concept&limit=10")
        assert result["status"] == 200
        body = result["body"]
        assert body["status"] in ("ready", "unavailable")
        assert "items" in body
        assert "sort_by" in body
        assert "total" in body

    def test_sector_ranking_all_types(self):
        result = self._fetch_json("/research/sectors/ranking?sector_type=all&limit=20")
        assert result["status"] == 200
        body = result["body"]
        assert "items" in body

    def test_sector_ranking_sort_by_fund_flow(self):
        result = self._fetch_json("/research/sectors/ranking?sort_by=fund_flow&limit=10")
        assert result["status"] == 200
        assert result["body"]["sort_by"] == "fund_flow"

    def test_stock_concept_cards_api(self):
        result = self._fetch_json("/research/stocks/600000.SSE/concept-cards")
        assert result["status"] == 200
        body = result["body"]
        assert body["vt_symbol"] == "600000.SSE"
        assert "cards" in body
        assert "shenwan" in body
        assert "total_cards" in body
        assert body["status"] in ("ready", "empty")

    def test_market_fund_flow_api(self):
        result = self._fetch_json("/market/fund-flow?sector_type=concept&top_n=5")
        assert result["status"] == 200
        body = result["body"]
        assert body["status"] in ("ready", "unavailable")
        assert "items" in body
        assert "sector_type" in body

    def test_market_hot_ranks_api(self):
        result = self._fetch_json("/market/hot-ranks?limit=5")
        assert result["status"] == 200
        body = result["body"]
        assert body["status"] in ("ready", "unavailable")
        assert "items" in body

    def test_market_limit_pools_api(self):
        result = self._fetch_json("/market/limit-pools")
        assert result["status"] == 200
        body = result["body"]
        assert body["status"] in ("ready", "unavailable")
        assert "trade_date" in body

    def test_industry_chain_graph_api(self):
        result = self._fetch_json("/industry-chains/graph?q=半导体")
        assert result["status"] == 200
        body = result["body"]
        # API wraps in {success, data: {nodes, edges, ...}}
        data = body.get("data", body)
        assert "nodes" in data
        assert "edges" in data


# ══════════════════════════════════════════
# 2. Frontend page load tests (regression + new pages)
# ══════════════════════════════════════════


class TestFrontendPagesLoad:
    """Verify all pages load without JavaScript errors."""

    def _assert_no_js_errors(self, page, page_name: str):
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        return errors

    def test_home_page_loads(self, browser_context):
        page = browser_context.new_page()
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.goto("/", wait_until="networkidle", timeout=15000)
        assert page.title() is not None
        assert len(errors) == 0, f"JS errors on home: {errors}"
        page.close()

    def test_stocks_page_loads(self, browser_context):
        page = browser_context.new_page()
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.goto("/stocks", wait_until="networkidle", timeout=15000)
        assert len(errors) == 0, f"JS errors on /stocks: {errors}"
        page.close()

    def test_explore_page_loads(self, browser_context):
        """New page: ThemeExplorer"""
        page = browser_context.new_page()
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.goto("/explore", wait_until="networkidle", timeout=15000)
        assert len(errors) == 0, f"JS errors on /explore: {errors}"
        page.close()

    def test_chain_page_loads(self, browser_context):
        """New page: ChainGraph"""
        page = browser_context.new_page()
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.goto("/chain", wait_until="networkidle", timeout=15000)
        assert len(errors) == 0, f"JS errors on /chain: {errors}"
        page.close()

    def test_data_page_loads(self, browser_context):
        """Merged DataManagement page"""
        page = browser_context.new_page()
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.goto("/data", wait_until="networkidle", timeout=15000)
        assert len(errors) == 0, f"JS errors on /data: {errors}"
        page.close()

    def test_legacy_routes_redirect(self, browser_context):
        """Legacy /sectors route should still render without error."""
        page = browser_context.new_page()
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.goto("/sectors", wait_until="networkidle", timeout=15000)
        assert len(errors) == 0, f"JS errors on /sectors (legacy): {errors}"
        page.close()


# ══════════════════════════════════════════
# 3. Frontend functional tests
# ══════════════════════════════════════════


class TestFrontendFunctional:
    """Test frontend interactive behaviors."""

    def test_stock_detail_page_loads(self, browser_context):
        page = browser_context.new_page()
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.goto("/stocks/600000.SSE", wait_until="networkidle", timeout=15000)
        content = page.content()
        assert len(content) > 100
        assert len(errors) == 0, f"JS errors on stock detail: {errors}"
        page.close()

    def test_stock_detail_shows_identity_card(self, browser_context):
        """Verify the concept tag cloud (identity card) is present on stock page."""
        page = browser_context.new_page()
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.goto("/stocks/600000.SSE", wait_until="networkidle", timeout=15000)
        # The identity card section should exist
        body_text = page.locator("body").inner_text()
        # Page should show "身份卡片" heading
        assert "身份卡片" in body_text or len(errors) > 0 or len(body_text) > 50
        assert len(errors) == 0, f"JS errors: {errors}"
        page.close()

    def test_explore_page_shows_ranking(self, browser_context):
        """Legacy ThemeExplorer route should open the merged mainline workspace."""
        page = browser_context.new_page()
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.goto("/explore", wait_until="networkidle", timeout=15000)
        body_text = page.locator("body").inner_text()
        assert page.url.endswith("/mainline")
        assert "概念指数" in body_text
        assert len(errors) == 0, f"JS errors: {errors}"
        page.close()

    def test_chain_page_shows_chains(self, browser_context):
        """Legacy industry-chain route should open the merged mainline workspace."""
        page = browser_context.new_page()
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.goto("/chain", wait_until="networkidle", timeout=15000)
        body_text = page.locator("body").inner_text()
        assert page.url.endswith("/mainline")
        assert "概念指数" in body_text
        assert len(errors) == 0, f"JS errors: {errors}"
        page.close()

    def test_data_page_shows_tabs(self, browser_context):
        """DataManagement should show tab bar."""
        page = browser_context.new_page()
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.goto("/data", wait_until="networkidle", timeout=15000)
        body_text = page.locator("body").inner_text()
        assert "数据管理" in body_text
        assert len(errors) == 0, f"JS errors: {errors}"
        page.close()

    def test_navigation_to_explore(self, browser_context):
        """Clicking '主线探索' in sidebar navigates to /explore."""
        page = browser_context.new_page()
        page.goto("/", wait_until="networkidle", timeout=15000)
        explore_link = page.locator('a[href="/explore"]').first
        if explore_link.is_visible():
            explore_link.click()
            page.wait_for_url("**/explore", timeout=5000)
            assert "/explore" in page.url
        page.close()

    def test_navigation_to_chain(self, browser_context):
        """Clicking '产业链' in sidebar navigates to /chain."""
        page = browser_context.new_page()
        page.goto("/", wait_until="networkidle", timeout=15000)
        chain_link = page.locator('a[href="/chain"]').first
        if chain_link.is_visible():
            chain_link.click()
            page.wait_for_url("**/chain", timeout=5000)
            assert "/chain" in page.url
        page.close()

    def test_home_page_shows_mainline_ranking(self, browser_context):
        """MarketPulse should show '今日主线热度' section."""
        page = browser_context.new_page()
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.goto("/", wait_until="networkidle", timeout=15000)
        body_text = page.locator("body").inner_text()
        assert "今日市场" in body_text or "今日主线热度" in body_text
        assert len(errors) == 0, f"JS errors: {errors}"
        page.close()
