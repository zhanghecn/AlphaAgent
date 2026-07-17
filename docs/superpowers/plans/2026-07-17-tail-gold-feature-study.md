# Gold Tail Low-suction Feature Study Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recompute the D-tail leader-spell feature study on the causally known D-1 `GOLD` market-timing cohort only, without SILVER rows or a post-filtered date split.

**Architecture:** Reuse the frozen tail feature builder and cash executor. Add an internal fixed-cohort argument to the real loader so `active_direction == "GOLD"` is selected before minute paths and outcomes are built, then expose a parameter-free GOLD report command. Preserve the original five chronological block identities and report GOLD coverage by block so a missing regime/block cannot masquerade as validation.

**Tech Stack:** Python 3.11+, pandas, SQLAlchemy, existing AlphaAgent low-suction feature/report pipeline, pytest, Ruff.

---

## Frozen Contract

- The cohort is exactly `active_direction == "GOLD"` from `context_date`, the reliable D-1 close.
- `GOLD/NORMAL` and `GOLD/DANGER` are retained; every SILVER row is excluded before feature execution and outcomes.
- The parent universe remains event-recognition proxy Top3, Shanghai/Shenzhen main board, spell offsets S+1..S+4.
- The existing block numbers remain unchanged after filtering. The GOLD rows are not re-split into a more favorable 60/40 sample.
- Feature cutoff, entry and exit remain D 14:50 close, D 14:55 bar open and D+1 10:35 bar open.
- Costs, queue rejection, fixed-exit non-closure and success labels remain unchanged.
- The report includes parent direction counts, GOLD share, GOLD rows/dates by original block and all support/volume/rank profiles.
- Single-feature confirmation keeps the existing sample and double-cost gates. No combined GOLD rule is searched.
- Strict historical Top3, formal rule and formal performance remain `null`.
- No price later than `2025-11-17` is read.

### Task 1: Fixed GOLD cohort loader and report contract

**Files:**
- Modify: `alphaagent/server/services/low_suction/tail_feature_study.py`
- Create: `alphaagent/server/services/low_suction/tail_gold_feature_study.py`
- Modify: `tests/alphaagent/services/low_suction/test_tail_feature_study.py`

- [x] **Step 1: Write failing GOLD cohort tests**

Add a synthetic ledger containing GOLD and SILVER rows. Assert the GOLD report path rejects mixed rows, preserves original block IDs, states that the timing value is known at D-1 close and keeps formal metrics null.

```python
def test_gold_tail_report_requires_a_pure_d1_gold_cohort() -> None:
    features, ledger = _gold_profile_frames()
    report = build_gold_tail_feature_report(features, ledger, metadata)

    assert report["cohort_contract"]["active_direction"] == "GOLD"
    assert report["cohort_contract"]["known_at"] == "D-1 close"
    assert report["formal_metrics"] is None
    assert report["formal_rule_selected"] is False

    mixed = ledger.copy()
    mixed.loc[mixed.index[-1], "active_direction"] = "SILVER"
    with pytest.raises(ValueError, match="GOLD-only"):
        build_gold_tail_feature_report(features, mixed, metadata)
```

- [x] **Step 2: Run the focused test and confirm failure**

```bash
uv run pytest tests/alphaagent/services/low_suction/test_tail_feature_study.py -q
```

Expected: fail because `build_gold_tail_feature_report` does not exist.

- [x] **Step 3: Implement the fixed cohort**

Extend the loader with an internal keyword-only argument and apply it before the minute query and feature builder.

```python
GOLD_ACTIVE_DIRECTION = "GOLD"

def load_tail_feature_study_data(
    *,
    active_direction: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    parent_candidates = inputs.candidates.loc[
        inputs.candidates["spell_session_offset"].isin(OBSERVATION_OFFSETS)
    ].copy()
    direction_counts = parent_candidates["active_direction"].value_counts()
    candidates = parent_candidates
    if active_direction is not None:
        candidates = parent_candidates.loc[
            parent_candidates["active_direction"].eq(active_direction)
        ].copy()
```

Add a strict wrapper in `tail_gold_feature_study.py` around the shared report builder.

```python
def build_gold_tail_feature_report(
    features: pd.DataFrame,
    ledger: pd.DataFrame,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    _assert_gold_only(features, ledger)
    report = build_tail_feature_report(features, ledger, metadata)
    report["study_track"] = "tail_low_suction_gold_feature_discovery"
    report["cohort_contract"] = {
        "active_direction": GOLD_ACTIVE_DIRECTION,
        "known_at": "D-1 close",
        "filter_before_minute_outcomes": True,
        "parent_direction_counts_read": True,
        "silver_candidate_feature_or_trade_rows": 0,
    }
    return report

def run_gold_tail_feature_study() -> dict[str, Any]:
    return build_gold_tail_feature_report(
        *load_tail_feature_study_data(active_direction=GOLD_ACTIVE_DIRECTION)
    )
```

Coverage must include `parent_candidate_rows`, `parent_direction_candidate_counts`, `cohort_candidate_share_pct`, `block_feature_rows` and `block_dates`.

- [x] **Step 4: Run focused tests and Ruff**

```bash
uv run pytest tests/alphaagent/services/low_suction/test_tail_feature_study.py -q
uvx ruff check alphaagent/server/services/low_suction/tail_feature_study.py alphaagent/server/services/low_suction/tail_gold_feature_study.py tests/alphaagent/services/low_suction/test_tail_feature_study.py
```

Expected: all pass.

### Task 2: Parameter-free GOLD CLI and auditable rendering

**Files:**
- Modify: `alphaagent/server/services/low_suction/cli.py`
- Modify: `alphaagent/server/services/low_suction/tail_feature_study.py`
- Modify: `alphaagent/server/services/low_suction/tail_gold_feature_study.py`
- Modify: `tests/alphaagent/services/low_suction/test_tail_feature_study.py`

- [x] **Step 1: Write failing CLI and Markdown tests**

```python
def test_gold_tail_cli_has_no_cohort_or_threshold_switches() -> None:
    args = build_parser().parse_args(
        ["v2-tail-gold-feature-study", "--format", "json"]
    )
    assert args.command == "v2-tail-gold-feature-study"
    for name in ("active_direction", "regime", "threshold", "feature"):
        assert not hasattr(args, name)

def test_gold_tail_markdown_discloses_block_coverage() -> None:
    markdown = render_tail_feature_markdown(gold_report)
    assert "金手指龙头尾盘低吸" in markdown
    assert "D-1 close" in markdown
    assert "原始时间块覆盖" in markdown
```

- [x] **Step 2: Register the fixed command**

Register `v2-tail-gold-feature-study` with only `--format` and `--output`. Dispatch it to `run_gold_tail_feature_study`; reuse the existing JSON/Markdown renderers.

- [x] **Step 3: Render cohort and block disclosure**

Use `cohort_contract` to select the GOLD title and add the parent direction counts, GOLD share and original block rows/dates to the coverage section. If a block has no GOLD rows, render zero rather than omitting it.

- [x] **Step 4: Run focused tests and Ruff**

```bash
uv run pytest tests/alphaagent/services/low_suction/test_tail_feature_study.py -q
uvx ruff check alphaagent/server/services/low_suction/tail_feature_study.py alphaagent/server/services/low_suction/cli.py tests/alphaagent/services/low_suction/test_tail_feature_study.py
```

Expected: all pass.

### Task 3: Real GOLD evidence, durable state and verification

**Files:**
- Create: `memory/06_backtests/low_suction_tail_gold_feature_study_20260717.json`
- Create: `memory/06_backtests/low_suction_tail_gold_feature_study_20260717.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`
- Modify: `docs/superpowers/plans/2026-07-17-tail-gold-feature-study.md`

- [x] **Step 1: Generate both reports from the existing database**

```bash
uv run python -m alphaagent.server.services.low_suction.cli \
  v2-tail-gold-feature-study --format json \
  --output memory/06_backtests/low_suction_tail_gold_feature_study_20260717.json
uv run python -m alphaagent.server.services.low_suction.cli \
  v2-tail-gold-feature-study --format markdown \
  --output memory/06_backtests/low_suction_tail_gold_feature_study_20260717.md
```

- [x] **Step 2: Audit GOLD coverage and results**

Check parent GOLD/SILVER candidate counts, GOLD share, every original block, ledger conservation, development/validation baselines, all support states, all 51 single-feature groups and winner/loser cases. Explicitly report whether validation contains both blocks 4 and 5.

- [x] **Step 3: Update durable memory**

Replace the current tail-study next step with the GOLD-only conclusion. Record the report links and JSON SHA256. Do not rewrite the all-regime report as if it were GOLD-only.

- [x] **Step 4: Run complete verification**

```bash
uv run pytest tests/alphaagent/services/low_suction -q
uv run pytest tests/alphaagent/test_data_sync_schedule.py -q
uvx ruff check alphaagent/server/services/low_suction tests/alphaagent/services/low_suction
uv run python -m compileall -q alphaagent/server/services/low_suction
uv run python -m json.tool memory/06_backtests/low_suction_tail_gold_feature_study_20260717.json >/dev/null
git diff --check
```

Expected: all pass. Do not commit, push, restart the API/PostgreSQL containers or read prices after `2025-11-17`.

## Self-Review

- GOLD is selected from D-1 context before D features and D+1 outcomes.
- SILVER cannot enter features, ledger, profiles or case tables.
- Original block IDs remain unchanged and empty GOLD blocks stay visible.
- More GOLD candidates is reported as coverage, not treated as evidence of higher win rate.
- The full-regime evidence remains intact and independently reproducible.
- Formal Top3 identity, rule and metrics remain `null`.
