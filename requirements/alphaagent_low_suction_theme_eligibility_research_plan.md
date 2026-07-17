# AlphaAgent Low-suction Theme Eligibility Research Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` inline after strict historical membership is available. Steps use checkbox (`- [ ]`) syntax for tracking. Do not dispatch subagents. Do not commit unless the user explicitly requests it.

**Goal:** Derive and lock a reproducible rule that separates tradable narrative themes from mechanical event, style, report, industry, and region boards before low-suction Top3 candidates are generated.

**Architecture:** Treat official board type, historical membership dynamics, and deterministic mechanical-board reference cohorts as separate evidence blocks. Select thresholds only on the chronological development segment, require explicit validation constraints, and preserve every excluded board as a control cohort; no strategy returns are used to choose taxonomy thresholds.

**Tech Stack:** Python 3.11+, pandas, NumPy, PostgreSQL, pytest, existing low-suction time split and reporting modules.

---

## Preconditions

- Do not execute this plan until `historical_concept_membership` has at least 720 strict sessions and a 1,095-day span.
- Input sector IDs must be exact Eastmoney `BKxxxx`; industry and region rows are rejected through `dc_index.idx_type` before feature calculation.
- Eligibility is selected without entry/exit returns. This prevents the board taxonomy from being optimized against the same P&L it later evaluates.
- Boards without enough history remain `insufficient_history`; they do not silently pass.

### Task 1: Build Pure Membership-dynamics Features

**Files:**
- Create: `alphaagent/server/services/low_suction/theme_eligibility.py`
- Create: `tests/alphaagent/services/low_suction/test_theme_eligibility.py`

- [x] **Step 1: Write event, theme, and stable-style fixtures**

```python
def test_jaccard_separates_rotating_event_but_not_stable_style() -> None:
    features = build_theme_features(
        daily_members=_daily_fixture(
            rotating_event=[{"A", "B"}, {"C", "D"}, {"E", "F"}],
            stable_theme=[{"A", "B", "C"}, {"A", "B", "C"}, {"A", "B", "C"}],
            stable_style=[{"D", "E"}, {"D", "E"}, {"D", "E"}],
        ),
        board_types={
            "EVENT": "概念板块",
            "THEME": "概念板块",
            "STYLE": "概念板块",
        },
    )
    assert features.loc["EVENT", "median_jaccard"] == 0.0
    assert features.loc["THEME", "median_jaccard"] == 1.0
    assert features.loc["STYLE", "median_jaccard"] == 1.0
```

- [x] **Step 2: Implement one feature row per board and cutoff**

Use only memberships known by the cutoff. Compute trailing 20-session median and p10 Jaccard,
daily add/remove rate, member-count coefficient of variation, active sessions, median member count,
and the share of sessions with a complete membership scope. Return `insufficient_history` before
20 complete sessions.

- [x] **Step 3: Add no-lookahead tests**

Mutating membership after cutoff D must not change D features. A missing daily scope must reduce
scope coverage and cannot be treated as an empty member set.

- [x] **Step 4: Run focused tests**

```bash
uv run --group server pytest \
  tests/alphaagent/services/low_suction/test_theme_eligibility.py -q
```

### Task 2: Define An Auditable Exact-ID Board Manifest Without Using Returns

**Files:**
- Create: `alphaagent/server/services/low_suction/theme_reference_cohorts.py`
- Modify: `tests/alphaagent/services/low_suction/test_theme_eligibility.py`

- [x] **Step 1a: Add exact-ID seed manifest records**

Each record contains `sector_id`, observed name, class, evidence reason, and first verified date.
Seed the mechanical event cohort with the locally verified boards `BK1630`, `BK1645`, `BK0817`,
`BK1631`, `BK0816`, `BK0815`, `BK1050`, `BK1051`, `BK1632`, and `BK1633`. Seed stable-style
controls with `BK1714`, `BK1682`, `BK1681`, `BK1680`, `BK1679`, `BK1678`, `BK1677`, `BK1665`,
`BK1663`, and `BK1662`. Seed narrative-theme references with `BK0490`, `BK0800`, `BK0899`,
`BK0963`, `BK0968`, `BK1090`, `BK1106`, `BK1134`, `BK1166`, and `BK1184`.

The 30 seed records are implemented and versioned. The live inventory currently contains
498 active concepts, so 468 exact IDs remain deliberately `unlabeled` until strict historical
membership can supply their dynamics evidence.

- [ ] **Step 1b: Classify every active development-range board**

Classify every exact BK code active in the development range as `narrative_theme`,
`mechanical_event`, `style_universe`, `report_event`, or `ambiguous`. Each non-ambiguous record
requires an official board type/name plus a membership-dynamics evidence summary. The manifest
validation fails when its ID set differs from the active development inventory; no active board
may inherit a class by default.

- [x] **Step 2: Reject name-only production classification**

Tests must prove that changing a board name cannot change its class without a new versioned
reference record, and an unknown ID remains `unlabeled` rather than inheriting a fuzzy name match.

- [x] **Step 3: Preserve manifest classes as evaluation data**

Manifest classes train and audit the dynamics rule. The production result records both the exact
manifest class and the dynamics decision; `ambiguous` and missing IDs fail closed. The resulting
manifest and rule versions are recorded separately so either change creates a new research run.

### Task 3: Select The Simplest Rule On Development Data Only

**Files:**
- Create: `alphaagent/server/services/low_suction/theme_eligibility_research.py`
- Create: `tests/alphaagent/services/low_suction/test_theme_eligibility_research.py`

- [x] **Step 1: Write chronological split tests**

Use the existing 60/20/20 split. Assert that threshold selection receives development rows only,
validation evaluates the frozen choice, and locked holdout is not exposed until the rule is frozen.

- [x] **Step 2: Implement a bounded grid**

Evaluate median-Jaccard floors `{0.30, 0.40, 0.50, 0.60, 0.70, 0.80}` and complete-scope floors
`{0.90, 0.95, 1.00}`. Official non-concept types and manifest mechanical/style/report/ambiguous
boards are always excluded before the grid. Select the lowest-complexity pair that satisfies both development
constraints:

```text
mechanical_or_style_false_eligibility_rate <= 5%
narrative_theme_retention_rate >= 70%
```

If no pair passes, return `no_qualified_taxonomy`; do not choose the best failing pair.

- [x] **Step 3: Require validation stability**

The frozen rule passes only if both constraints also hold on the middle 20% and at least 90% of
boards keep the same class across adjacent 20-session cutoffs. Otherwise return
`taxonomy_failed_validation`.

- [x] **Step 4: Run research tests**

```bash
uv run --group server pytest \
  tests/alphaagent/services/low_suction/test_theme_eligibility_research.py -q
```

### Task 4: Produce A Board-level Audit Before Candidate Integration

**Files:**
- Modify: `alphaagent/server/services/low_suction/cli.py`
- Create after the real run: `memory/06_backtests/low_suction_theme_eligibility_YYYYMMDD.md`

- [x] **Step 1a: Add a read-only command and fail-closed report**

```text
theme-eligibility-research --start YYYY-MM-DD --end YYYY-MM-DD --format json|markdown
```

The report includes rule version, input source, data ranges, selected thresholds, reference-cohort
confusion matrices, class counts, every excluded board and reason, every ambiguous board, and
classification stability. It contains no entry/exit return or strategy metric.

- [ ] **Step 1b: Generate the complete board-level report**

This real report remains blocked until strict historical membership is available and all 498
active board IDs have an evidence-backed manifest class. The current command reports
`blocked_by_historical_membership`, `rule=null`, and `formal_metrics=null`.

- [x] **Step 2: Keep excluded boards as controls**

Persist no deletion list. The later event dataset carries `theme_eligibility_class` and
`theme_eligibility_reason` for included and excluded cohorts so performance comparisons can falsify
the taxonomy without changing the locked universe.

- [x] **Step 3: Stop if the taxonomy is not qualified**

`no_qualified_taxonomy` or `taxonomy_failed_validation` leaves low-suction research blocked and
prevents formal Top3 generation.

### Task 5: Integrate Only A Frozen Qualified Taxonomy

**Files:**
- Modify: `alphaagent/server/services/low_suction/repository.py`
- Modify: `alphaagent/server/services/low_suction/daily_discovery.py`
- Modify: `tests/alphaagent/services/low_suction/test_daily_discovery.py`

- [x] **Step 1: Write eligibility-before-ranking tests**

An event-style board with strong index returns must be removed before Top3 ranking. A qualified
narrative theme with strict D-1 members remains eligible. An ambiguous or insufficient-history
board is retained in audit output but produces no formal candidate.

- [x] **Step 2: Add the frozen taxonomy version to every event**

Candidate identity includes `theme_eligibility_version`; changing the version requires a new
research run and cannot mutate an old event cohort.

- [x] **Step 3: Run the complete low-suction suite**

```bash
uv run --group server pytest tests/alphaagent/services/low_suction -q
```

## Completion Boundary

This plan qualifies the concept universe only. It does not optimize Top3 weights, low-suction event
thresholds, exits, cash allocation, or market-timing labels. Those analyses begin only after strict
membership, strict security status, and candidate minute paths pass their independent gates.
