# AlphaAgent Limit-Up History Replay Implementation Plan

**Goal:** Add auditable trade-date navigation, historical Top5 outcomes, and factor-bucket diagnostics to the existing limit-up research MVP.

**Architecture:** Reuse the current read-only limit-up dataset and extract one historical-day replay builder shared by dashboard and proxy backtest. Keep final event fields in the outcome layer only. Add typed REST query parameters and a compact React date toolbar.

**Tech Stack:** FastAPI, SQLAlchemy Core, pytest, React 18, TypeScript, TanStack Query, Vite.

## Tasks

1. Add failing service and route tests for available dates, exact-date selection, missing dates, no-lookahead ranking, D+1 outcomes, and navigation metadata.
2. Implement date extraction and a historical-day replay builder in the limit-up service; expose `/dates` and the dashboard `date` query parameter.
3. Add factor buckets to both conservative and optimistic backtest scenarios with explicit minimum-sample status.
4. Extend the TypeScript API contracts and add previous/date/next controls; bind sentiment-cycle queries to the selected date.
5. Display historical outcome and D+1 return columns in the Top5 table, and factor buckets in the backtest panel.
6. Run targeted pytest, frontend build, API smoke checks, and Playwright desktop/mobile validation.
7. Update the backtest evidence and durable project memory with verified coverage and limitations.

No git commit or push is included because repository instructions require explicit user authorization.
