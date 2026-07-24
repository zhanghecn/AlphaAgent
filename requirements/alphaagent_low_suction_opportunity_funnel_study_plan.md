# Low-Suction Opportunity Funnel Study Implementation Plan

> **For agentic workers:** Implement this plan task-by-task with tests before the bounded historical run.

**Goal:** Determine whether the 89 historical low-suction trades are a reasonable high-quality subset or the result of missed dynamic-leader MA5/MA10 pullback opportunities.

**Architecture:** Add one research-only attribution layer over the existing causal campaign, dynamic Top3 leader, support-state, and trade replay outputs. The layer must not recalculate leader identity or alter product strategy rules; it constructs the support-touch parent population, assigns mutually exclusive funnel outcomes, and reports D+1 and causal structural-hold results.

**Tech Stack:** Python 3.11, pandas, pytest, existing AlphaAgent low-suction causal replay and SQLite history.

---

### Task 1: Define and test the opportunity ledger

**Files:**
- Create: `alphaagent/server/services/low_suction/leader_pullback_opportunity_funnel_study.py`
- Create: `tests/alphaagent/services/low_suction/test_leader_pullback_opportunity_funnel_study.py`

- [ ] Build a fixture containing first-wave MA5 and later-wave MA10 support touches, confirmation signals, market phases, overlapping trades, and missing D+1 endpoints.
- [ ] Assert the parent population requires an active campaign, intact structure, same-day dynamic Top3 status, pullback state, and a same-day test of the wave's required MA5/MA10 support.
- [ ] Assert each parent opportunity has one stable identity and one mutually exclusive terminal funnel reason.
- [ ] Run `uv run pytest tests/alphaagent/services/low_suction/test_leader_pullback_opportunity_funnel_study.py -q` and verify the tests fail before implementation.
- [ ] Implement pure dataframe functions for parent-population extraction, outcome attachment, and funnel classification.
- [ ] Run the same test and verify it passes.

### Task 2: Add return and capacity attribution

**Files:**
- Modify: `alphaagent/server/services/low_suction/leader_pullback_opportunity_funnel_study.py`
- Modify: `tests/alphaagent/services/low_suction/test_leader_pullback_opportunity_funnel_study.py`

- [ ] Test D+1 close return, confirmation-entry structural return, non-overlap exclusion, and two-slot capacity exclusion independently.
- [ ] Reuse existing executed trade identities and `simulate_four_slot_cash(..., capacity=2)` acceptance output rather than implementing another portfolio engine.
- [ ] Report counts, symbols, dates, positive rate, mean return, median return, month, phase, support line, and empty-month attribution for every funnel layer.
- [ ] Verify all fixture tests pass and no outcome field participates in opportunity selection.

### Task 3: Run the bounded historical study

**Files:**
- Create: `memory/06_backtests/low_suction_leader_pullback_opportunity_funnel_20260721.md`

- [ ] Load the canonical causal inputs once and build stock features, concept campaigns, dynamic leader paths, prepared daily states, signals, and trades once.
- [ ] Bound the audit to `2024-08-01` through the latest closed historical session and retain only Shanghai/Shenzhen main-board symbols through the existing universe filter.
- [ ] Materialize a compact Markdown report with the `parent -> confirmed -> strong reclaim -> market phase -> non-overlap -> two slots` funnel.
- [ ] Include named evidence for 东山精密, 金安国纪, and 亨通光电 where present, plus all zero-trade months.
- [ ] State the current-membership survivorship bias and that this is an exploratory historical proxy, not untouched forward validation.

### Task 4: Verify and record the conclusion

**Files:**
- Modify only if a durable conclusion is reached: `memory/09_decisions/decisions.md`

- [ ] Run the focused funnel tests and existing causal replay tests affected by imported contracts.
- [ ] Check that no limit-up research files or product strategy rules changed.
- [ ] Decide from measured attrition whether 89 trades are scarcity, strong-reclaim filtering, market-phase filtering, overlap, or two-slot capacity.
- [ ] Record only the stable conclusion and report link in project memory; do not freeze or deploy a new trading rule from this exploratory audit.
