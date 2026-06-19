# Low-Suction Launch Semantics And Baseline Guard Audit

Date: 2026-06-19

## Scope

- Strategy: `mainline_dragon_pullback / 0.1.21`
- Product baseline range: `2025-03-26` to `2026-06-18`
- Execution model: `legacy_next_open`
- Portfolio: BUY execution pool top `20`, max positions `10`

This note closes the follow-up around low-suction launch semantics, old candidate evidence schemas, and the `601179.SSE` early dragon-pullback sample.

## What Changed

### Candidate Evidence Schema Gate

Current persisted screening evidence uses:

- `signal_evidence_schema_version = 2026-06-19.1`

New candidate and recommendation reads require the current evidence schema for user-facing latest candidates. If no current-schema run exists, the candidate endpoint returns an empty/refresh-needed state instead of silently falling back to stale explanation fields.

This is a display/data-quality guard. It does not change historical scoring, portfolio execution, or default buy/sell rules.

### Actual BUY Order Evidence

Actual BUY orders now carry the entry evidence used by the strategy, not just the fill payload. This lets stock detail and audit views explain an actual trade with fields such as:

- `entry_setup`
- `low_suction_days`
- `ma_convergence_pct`
- `latest_change_pct`
- `close_location_in_range`
- `candidate_execution`

The read side also backfills the read-only diagnostic `early_dragon_pullback_risk` for old persisted order/trade raw payloads when the required visible fields are present. This does not write the database and does not affect return, score, ranking or sell logic.

### Baseline Guard

`#204` was created after locally refreshing the `2026-06-12` candidate cache. That changed the last portfolio path by replacing the 2026-06-15 buys:

- Baseline path `#203/#194`: `002384.SZSE`, `002436.SZSE`
- Diagnostic path `#204`: `603002.SSE`, `601066.SSE`

The resulting `#204` return was about `+80.42%`, below the product baseline `+82.99%`, but it is not a valid strategy-regression conclusion because it mixed a localized candidate refresh into an otherwise cached full-history run.

`#204` is explicitly marked:

- `params.exclude_from_product_baseline = true`
- `params.baseline_exclusion_reason = diagnostic_run_after_2026_06_12_candidate_refresh`

`GET /api/backtests?run_type=portfolio&strategy=mainline_dragon_pullback&baseline_only=true&limit=5` now returns `#203` and `#194`, not `#204`.

## Focus Sample: `601179.SSE`

User concern:

- `2026-02-03` was too early.
- `2026-02-24` looked like longer low-suction buildup.
- `2026-02-25` looked more like the first reclaim/trigger.

Current audit result on `#204` confirms why the early entry is suspicious:

- BUY execution date: `2026-02-03`
- Signal date: `2026-02-02`
- Entry setup: `dragon_pullback`
- `low_suction_days = 0`
- `ma_convergence_pct = 22.9143`
- `latest_change_pct = 7.5862`
- `close_location_in_range = 0.6237`
- `early_dragon_pullback_risk = true`
- Exit: `2026-02-06`, `support_stop`
- Closed return: about `-9.68%`

Interpretation: this is an early classic dragon-pullback entry with wide MA spread and no low-suction buildup, not the later low-suction launch pattern the user wanted. The current implementation exposes this as a diagnostic risk tag, but does not turn it into a hard rejection because previous broad repeated/early dragon-pullback hard gates harmed global performance.

## Current Product Baseline

The current product baseline remains:

| Run | Return | Max DD | Buy / Sell / Open | Status |
| --- | ---: | ---: | --- | --- |
| `#203` | `+82.9854%` | `-15.5904%` | `224 / 214 / 10` | Current API baseline item |
| `#194` | `+82.9854%` | `-15.5904%` | `224 / 214 / 10` | Same metrics, prior persisted baseline |
| `#204` | `+80.4157%` | `-15.5904%` | `224 / 214 / 10` | Diagnostic only; excluded from baseline |

Do not compare future strategy work against `#204` as the product baseline.

## Decision

- Keep unconfirmed low-suction as `WATCH` / observation semantics in user-facing candidates.
- Keep low-suction launch confirmation as evidence/ranking context, not a hard default gate.
- Keep `early_dragon_pullback_risk` as a read-only diagnostic for samples like `601179.SSE`.
- Do not force low-suction to take portfolio slots; it must compete by score/opportunity ranking.
- Do not let localized candidate refreshes become product baseline runs.

## Verification

- `uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q`: `314 passed, 1 warning`
- `uv run pytest tests/alphaagent/test_data_sync_schedule.py tests/alphaagent/test_akshare_adapter.py -q`: `60 passed, 1 warning`
- `uv run python -m compileall alphaagent/server/services/quant alphaagent/server/services/backtest alphaagent/server/api alphaagent/data_sources alphaagent/server/db`: passed
- `pnpm --dir frontend run build`: passed, with existing large chunk warnings
- `git diff --check`: passed
- `docker compose up -d --build alphaagent-api`: rebuilt and healthy
- API check: `baseline_only=true` returns `#203/#194`, not `#204`
- API check: `/api/backtests/204/symbols/601179.SSE` shows `early_dragon_pullback_risk: true` on the 2026-02-03 entry raw payload
