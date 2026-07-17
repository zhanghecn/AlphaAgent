# True Leader Wave Identification Study Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Identify the real leading stocks for each observable A-share concept emotion cycle, label their first/second/third main-rise waves, test whether the stock led and was followed by its concept index, and validate a point-in-time Top3 leader algorithm on actual local history before any new low-suction rule is studied.

**Architecture:** Keep four ledgers physically and semantically separate: point-in-time concept cycles, point-in-time stock features/ranks, retrospective wave truth labels, and descriptive post-protocol reference cases. The broad identity comparison uses only the frozen discovery period and a static current-membership proxy because historical memberships are absent; the already-viewed 2026 examples are quarantined as contaminated descriptive audits and never used to select features or report formal out-of-sample performance.

**Tech Stack:** Python 3.13, pandas, NumPy, SQLAlchemy/PostgreSQL, existing AlphaAgent low-suction cycle research, pytest, Ruff, Docker Compose.

---

## Fixed Research Contract

- Concept-cycle unit: an existing `breakout_trend` cycle start, already derived without stock outcomes.
- Emotion-cycle qualification at the cycle-start close:
  - concept cross-sectional `relative_percentile >= 0.80`;
  - 3 to 300 complete current-member proxy stocks;
  - at least three distinct stocks had a `>= 5%` close-to-close day during the last three sessions;
  - those recently ignited stocks represent at least 5% of complete members.
- Stock universe: Shanghai/Shenzhen main boards only; exclude current names containing ST or delisting warnings. Historical security status is absent, so every result remains `current_membership_and_security_proxy`.
- Point-in-time candidate: a member with at least one `>= 5%` day in the ten sessions through the cycle-start close and complete MA/turnover history.
- Causal rank uses only data through the cycle-start close, in this frozen lexicographic order:
  - live main-rise structure (`close >= MA5 > MA10 > MA20`);
  - stock ignition strictly before concept-cycle start;
  - earlier first ignition within the ten-session lookback;
  - more `>= 5%` sessions in the lookback;
  - larger stock-minus-concept ten-session return;
  - closer distance to the prior 20-session high;
  - larger trailing 20-session median turnover;
  - stable symbol tie-break.
- Baseline rank: ten-session stock-minus-concept return descending, then symbol.
- Wave truth is never a buy feature. A campaign starts at a fixed ignition date. Wave 1 exists at ignition; a later wave is confirmed only by the ordered daily sequence `record peak -> later >=5% pullback -> later higher record high`. Same-day high/low order cannot confirm a wave.
- An unresolved final pullback is retained. It is `terminal_failure_observed` only when a causal structural-break condition occurred and no later higher high exists by the observation boundary; otherwise it is censored/open.
- Broad identity truth horizon: 40 sessions after a cycle start. A row is complete only with all 40 sessions available.
- Retrospective truth Top3 order:
  - confirmed wave count in the 40-session horizon descending;
  - future 40-session maximum stock-minus-concept return descending;
  - future 20-session close stock-minus-concept return descending;
  - stable symbol tie-break.
- Evaluation reports causal Top1 exact match, causal Top3 capture of truth Top1, and Top3 overlap against the same metrics for the baseline. Use five chronological non-overlapping blocks and never use future labels to alter the frozen rank order.
- Reference campaigns are descriptive only:
  - `600170.SSE`, anchor `2025-09-15`;
  - `002636.SZSE`, anchor `2026-01-15`;
  - `600183.SSE`, anchor `2026-05-13`.
- The old outer holdout is considered contaminated because its stock paths were already inspected. This study reports `formal_metrics=null`, `strict_top3_claim=false`, and starts no trading or low-suction backtest.
- Repository instruction overrides the skill's commit cadence: do not run `git commit` or `git push`.

## File Structure

- Create `alphaagent/server/services/low_suction/reason_relations.py`: deterministic, auditable reason-token normalization used only by the new evidence ledger.
- Create `alphaagent/server/services/low_suction/leader_waves.py`: pure daily wave/campaign state machine with no database dependency.
- Create `alphaagent/server/services/low_suction/true_leader_study.py`: broad discovery loader, point-in-time ranking, future truth attachment, evaluation, reference-case audit and report rendering.
- Modify `alphaagent/server/services/low_suction/cli.py`: add one read-only `v2-true-leader-wave-study` command.
- Create three focused test files under `tests/alphaagent/services/low_suction/`.
- Create JSON and Markdown evidence under `memory/06_backtests/`; update the index and current decision summary in place.

### Task 1: Auditable Event-reason Relations

**Files:**
- Create: `alphaagent/server/services/low_suction/reason_relations.py`
- Create: `tests/alphaagent/services/low_suction/test_reason_relations.py`

- [x] **Step 1: Write failing normalization tests**

```python
def test_reason_suffix_normalization_maps_pcb_concept_to_pcb() -> None:
    events = pd.DataFrame([_event(reason="覆铜板+PCB概念", symbol="002636.SZSE")])
    concepts = pd.DataFrame([{"sector_id": "BK0877", "concept_name": "PCB"}])
    rows = build_normalized_reason_relations(events, concepts)
    assert rows.loc[0, "reason_token"] == "PCB概念"
    assert rows.loc[0, "relation_method"] == "normalized_suffix_exact"


def test_reason_normalization_does_not_invent_semantic_aliases() -> None:
    events = pd.DataFrame([_event(reason="覆铜板", symbol="002636.SZSE")])
    concepts = pd.DataFrame([{"sector_id": "BK0877", "concept_name": "PCB"}])
    assert build_normalized_reason_relations(events, concepts).empty


def test_ambiguous_normalized_concept_name_is_rejected() -> None:
    concepts = pd.DataFrame([
        {"sector_id": "A", "concept_name": "机器人"},
        {"sector_id": "B", "concept_name": "机器人概念"},
    ])
    with pytest.raises(ValueError, match="ambiguous normalized concept"):
        build_normalized_reason_relations(_events(), concepts)
```

- [x] **Step 2: Run the focused test and confirm import failure**

```bash
uv run pytest tests/alphaagent/services/low_suction/test_reason_relations.py -q
```

Expected: collection fails because `reason_relations.py` does not exist.

- [x] **Step 3: Implement deterministic normalization**

Expose:

```python
def normalize_reason_name(value: object) -> str:
    """Normalize whitespace/case and one trailing 概念/龙头/板块 suffix."""


def build_normalized_reason_relations(
    events: pd.DataFrame,
    concepts: pd.DataFrame,
) -> pd.DataFrame:
    """Return exact or suffix-normalized relations without semantic aliases."""
```

Preserve `event_id`, `source_date`, `vt_symbol`, `stock_name`, original reason token, concept ID/name and `relation_method`. Exact matches take precedence. Reject duplicate concept IDs, duplicate names and normalized-name collisions.

- [x] **Step 4: Run tests and Ruff**

```bash
uv run pytest tests/alphaagent/services/low_suction/test_reason_relations.py -q
uvx ruff check alphaagent/server/services/low_suction/reason_relations.py tests/alphaagent/services/low_suction/test_reason_relations.py
```

Expected: all checks pass.

### Task 2: Ordered Main-rise Wave State Machine

**Files:**
- Create: `alphaagent/server/services/low_suction/leader_waves.py`
- Create: `tests/alphaagent/services/low_suction/test_leader_waves.py`

- [x] **Step 1: Write failing first/second/third-wave tests**

```python
def test_wave_chain_requires_peak_then_later_pullback_then_later_higher_high() -> None:
    rows = build_leader_wave_ledger(_three_wave_bars(), anchor_date=date(2025, 1, 2))
    assert rows["wave_number"].tolist() == [1, 2, 3]
    assert rows.iloc[0]["resolution_status"] == "continued_to_higher_high"
    assert rows.iloc[1]["resolution_status"] == "continued_to_higher_high"


def test_same_day_high_low_cannot_confirm_a_new_wave() -> None:
    rows = build_leader_wave_ledger(_same_day_range_bars(), anchor_date=date(2025, 1, 2))
    assert len(rows) == 1


def test_unresolved_final_pullback_is_preserved() -> None:
    rows = build_leader_wave_ledger(_terminal_bars(), anchor_date=date(2025, 1, 2))
    assert rows.iloc[-1]["resolution_status"] == "terminal_failure_observed"
    assert pd.notna(rows.iloc[-1]["trough_date"])
```

- [x] **Step 2: Run the focused test and confirm failure**

```bash
uv run pytest tests/alphaagent/services/low_suction/test_leader_waves.py -q
```

Expected: collection fails because `leader_waves.py` does not exist.

- [x] **Step 3: Implement the pure wave ledger**

```python
def build_leader_wave_ledger(
    daily_bars: pd.DataFrame,
    *,
    anchor_date: date,
    observation_end: date | None = None,
    minimum_pullback_pct: float = 5.0,
) -> pd.DataFrame:
    """Label ordered record-high waves from one fixed ignition anchor."""
```

Require unique ordered daily OHLCV rows. Compute MA5/MA10/MA20 from the full supplied history but emit only rows at/after the anchor. Pullback and higher-high dates must be strictly later than the preceding event. Every row preserves peak/trough prices and dates, recovery sessions, peak-to-trough drawdown, trough volume ratio, trough MA distances, deepest tested support and whether the close reclaimed MA5/MA10.

For the final unresolved pullback, causal structural break means either two consecutive closes below MA10 with `MA5 <= MA10`, or a close below MA20. It becomes terminal only because no later higher high exists by the supplied boundary; otherwise label it `unresolved_pullback_censored`. An advance with no qualifying pullback is `open_at_observation_end`.

- [x] **Step 4: Add causal snapshot invariance tests and helper**

```python
def build_causal_wave_snapshot(
    daily_bars: pd.DataFrame,
    *,
    anchor_date: date,
    cutoff_date: date,
) -> dict[str, object]:
    """Summarize only wave events confirmed by cutoff_date."""
```

Mutating every bar after the cutoff must not change the snapshot. The snapshot reports confirmed wave number, current record high, pullback state, structural state and feature cutoff.

- [x] **Step 5: Run tests and Ruff**

```bash
uv run pytest tests/alphaagent/services/low_suction/test_leader_waves.py -q
uvx ruff check alphaagent/server/services/low_suction/leader_waves.py tests/alphaagent/services/low_suction/test_leader_waves.py
```

Expected: all checks pass.

### Task 3: Causal Concept-cycle Leader Ranking

**Files:**
- Create: `alphaagent/server/services/low_suction/true_leader_study.py`
- Create: `tests/alphaagent/services/low_suction/test_true_leader_study.py`

- [x] **Step 1: Write failing feature and emotion-cycle tests**

```python
def test_emotion_cycle_gate_uses_only_cycle_start_and_earlier_rows() -> None:
    qualified = build_emotion_cycle_candidates(_cycle_starts(), _members(), _features())
    assert qualified["cycle_id"].nunique() == 1
    assert qualified["feature_cutoff_date"].eq(pd.Timestamp("2025-01-10")).all()


def test_emotion_cycle_gate_rejects_broad_or_weak_proxy_universes() -> None:
    rows = build_emotion_cycle_candidates(_broad_cycles(), _members(), _features())
    assert rows.empty


def test_non_main_board_and_current_st_names_are_excluded() -> None:
    rows = build_emotion_cycle_candidates(_cycle_starts(), _mixed_members(), _features())
    assert set(rows["vt_symbol"]) == {"600001.SSE", "002001.SZSE", "600002.SSE"}
```

- [x] **Step 2: Implement stock feature and cycle-candidate builders**

```python
def build_point_in_time_stock_features(stock_bars: pd.DataFrame) -> pd.DataFrame:
    """Build trailing stock features without shifting future values backward."""


def build_emotion_cycle_candidates(
    cycle_starts: pd.DataFrame,
    memberships: pd.DataFrame,
    stock_features: pd.DataFrame,
) -> pd.DataFrame:
    """Return qualified current-membership proxy candidates at each cycle start."""
```

The feature panel contains daily return, first/last strong-day distance in ten sessions, strong-day counts, MA structure, prior-20-day high distance, trailing turnover, ten-day return and a feature-complete reason. The cycle builder applies the exact frozen breadth, relative-strength, member-count and universe gates above.

- [x] **Step 3: Write failing causal rank tests**

```python
def test_causal_rank_prefers_live_preleading_repeat_strength() -> None:
    ranked = rank_causal_cycle_leaders(_qualified_candidates())
    assert ranked.loc[ranked["causal_rank"].eq(1), "vt_symbol"].item() == "600001.SSE"
    assert ranked.groupby("cycle_id")["causal_top3"].sum().eq(3).all()


def test_causal_rank_is_invariant_to_future_labels() -> None:
    baseline = rank_causal_cycle_leaders(_qualified_candidates())
    changed = rank_causal_cycle_leaders(
        _qualified_candidates().assign(future_40d_max_excess_pct=[999.0, -999.0, 0.0])
    )
    pd.testing.assert_series_equal(baseline["causal_rank"], changed["causal_rank"])


def test_causal_rank_rejects_future_columns_in_feature_input() -> None:
    with pytest.raises(ValueError, match="future"):
        rank_causal_cycle_leaders(_qualified_candidates_with_future_column())
```

- [x] **Step 4: Implement causal and baseline ranks**

```python
def rank_causal_cycle_leaders(candidates: pd.DataFrame) -> pd.DataFrame:
    """Freeze causal and ten-day-excess baseline ranks for each cycle."""
```

Reject `future_`, `truth_`, outcome, exit, MFE and MAE fields. Require at least three complete ignited candidates. Emit the exact rank components, `causal_rank`, `causal_top1`, `causal_top3`, `baseline_rank`, `baseline_top1`, `baseline_top3`, `rank_known_at` and `feature_cutoff_date`.

- [x] **Step 5: Run tests and Ruff**

```bash
uv run pytest tests/alphaagent/services/low_suction/test_true_leader_study.py -q
uvx ruff check alphaagent/server/services/low_suction/true_leader_study.py tests/alphaagent/services/low_suction/test_true_leader_study.py
```

Expected: all checks pass.

### Task 4: Retrospective Truth and Time-block Validation

**Files:**
- Modify: `alphaagent/server/services/low_suction/true_leader_study.py`
- Modify: `tests/alphaagent/services/low_suction/test_true_leader_study.py`

- [x] **Step 1: Write failing truth-boundary tests**

```python
def test_truth_labels_are_attached_only_after_ranks_are_frozen() -> None:
    labels = build_cycle_leader_truth(_ranks(), _stock_bars(), _concept_bars(), horizon=40)
    assert labels["truth_rank"].notna().all()
    assert labels.loc[labels["truth_rank"].eq(1), "future_wave_count"].item() == 3


def test_incomplete_future_horizon_remains_censored() -> None:
    labels = build_cycle_leader_truth(_ranks_near_end(), _stock_bars(), _concept_bars())
    assert labels["truth_status"].eq("censored_incomplete_40d").all()
    assert labels["truth_rank"].isna().all()


def test_truth_top3_does_not_rewrite_causal_rank() -> None:
    labels = build_cycle_leader_truth(_ranks(), _stock_bars(), _concept_bars())
    assert labels["causal_rank"].tolist() == _ranks()["causal_rank"].tolist()
```

- [x] **Step 2: Implement downstream truth labels**

```python
def build_cycle_leader_truth(
    frozen_ranks: pd.DataFrame,
    stock_bars: pd.DataFrame,
    concept_bars: pd.DataFrame,
    *,
    trading_dates: Sequence[date],
    horizon: int = 40,
) -> pd.DataFrame:
    """Attach retrospective wave and excess-return labels to frozen ranks."""
```

Use the ordered wave state machine from Task 2. Future return denominators are the cycle-start closes. Keep full candidate rows, future availability, future wave count, 20/40-session excess returns, maximum excess, truth rank and truth Top1/Top3 flags.

- [x] **Step 3: Write failing block-metric tests**

```python
def test_identity_metrics_compare_causal_and_baseline_on_same_cycles() -> None:
    metrics = evaluate_true_leader_identity(_labeled_cycles())
    pooled = metrics.loc[metrics["segment"].eq("all")].set_index("mode")
    assert pooled.loc["causal_leadership", "qualified_cycles"] == 5
    assert pooled.loc["ten_day_excess_baseline", "qualified_cycles"] == 5


def test_block_assignment_is_chronological_and_deterministic() -> None:
    first = assign_true_leader_blocks(_labeled_cycles(), block_count=5)
    second = assign_true_leader_blocks(_labeled_cycles().sample(frac=1, random_state=9), block_count=5)
    pd.testing.assert_frame_equal(first.sort_values("cycle_id"), second.sort_values("cycle_id"))
```

- [x] **Step 4: Implement evaluation without promotion**

```python
def evaluate_true_leader_identity(labels: pd.DataFrame) -> pd.DataFrame:
    """Compare causal and baseline identity accuracy in pooled and five blocks."""
```

Report qualified cycles, exact Top1 accuracy, Top3 capture of truth Top1, mean Top3 truth overlap, selected-versus-rest future wave-count difference and selected-versus-rest future maximum-excess difference. Return a descriptive comparison only; `formal_selected_mode` remains null even when causal ranking wins.

- [x] **Step 5: Run tests and Ruff**

Run the Task 3 commands. Expected: all checks pass.

### Task 5: Real-data Loader, Reference Cases and Reports

**Files:**
- Modify: `alphaagent/server/services/low_suction/true_leader_study.py`
- Modify: `alphaagent/server/services/low_suction/cli.py`
- Modify: `tests/alphaagent/services/low_suction/test_true_leader_study.py`

- [x] **Step 1: Write failing report and CLI tests**

```python
def test_report_keeps_proxy_and_formal_claims_separate() -> None:
    report = build_true_leader_report(_study_inputs())
    assert report["strict_top3_claim"] is False
    assert report["formal_metrics"] is None
    assert report["old_holdout_status"] == "contaminated_not_reusable"


def test_reference_case_report_preserves_real_stock_identity() -> None:
    cases = build_reference_campaign_audit(_reference_bars())
    assert {row["vt_symbol"] for row in cases} == {
        "600170.SSE", "002636.SZSE", "600183.SSE"
    }


def test_cli_registers_true_leader_wave_study() -> None:
    args = build_parser().parse_args(["v2-true-leader-wave-study"])
    assert args.command == "v2-true-leader-wave-study"
```

- [x] **Step 2: Implement one-pass database loading**

```python
def load_true_leader_study_inputs() -> TrueLeaderStudyInputs:
    """Load discovery cycles, current proxy membership and required daily bars once."""
```

Reuse `load_cycle_research_inputs()` and `build_cycle_candidates()`. Load current theme memberships, current stock names and only relevant daily stock bars. Broad ranks/truth stop at the frozen discovery boundary. Separately load only the three reference stocks through the latest complete local daily date. Record row counts, dates, sources and SHA256 frame fingerprints.

- [x] **Step 3: Implement reference campaign audit**

```python
def build_reference_campaign_audit(reference_bars: pd.DataFrame) -> list[dict[str, Any]]:
    """Audit the three user-raised cases without using them to tune broad ranks."""
```

For each stock report every wave peak, trough, next higher high, support classification and final unresolved/terminal state. Include `used_for_model_selection=false` and `evidence_scope=contaminated_descriptive_reference`.

- [x] **Step 4: Implement report and CLI rendering**

Expose `run_true_leader_wave_study`, `render_true_leader_study_json` and `render_true_leader_study_markdown`. Add CLI command `v2-true-leader-wave-study` with only `--format` and `--output`.

The report contains contract, coverage, relation-normalization audit, cycle cases, full identity metrics, Top/bottom mismatch cases, reference campaigns, limitations, fingerprints and exact reproduction command. It must state that person-named hot-money formulas are unsupported; the algorithm only encodes observable principles of early ignition, market recognition, divergence, repeated higher highs and structural failure.

- [x] **Step 5: Run focused tests and CLI help**

```bash
uv run pytest tests/alphaagent/services/low_suction/test_reason_relations.py tests/alphaagent/services/low_suction/test_leader_waves.py tests/alphaagent/services/low_suction/test_true_leader_study.py -q
uv run python -m alphaagent.server.services.low_suction.cli --help
uvx ruff check alphaagent/server/services/low_suction/reason_relations.py alphaagent/server/services/low_suction/leader_waves.py alphaagent/server/services/low_suction/true_leader_study.py alphaagent/server/services/low_suction/cli.py tests/alphaagent/services/low_suction/test_reason_relations.py tests/alphaagent/services/low_suction/test_leader_waves.py tests/alphaagent/services/low_suction/test_true_leader_study.py
```

Expected: all checks pass.

### Task 6: Execute Actual Study and Preserve Evidence

**Files:**
- Create: `memory/06_backtests/low_suction_true_leader_wave_study_20260717.json`
- Create: `memory/06_backtests/low_suction_true_leader_wave_study_20260717.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`

- [x] **Step 1: Make the new research code visible inside the one-off API container**

Use the existing API image with the workspace bind-mounted at `/workspace`; rebuild only when the
image dependencies changed. This study only added project source, so the bind mount is sufficient:

```bash
docker compose run --rm --no-deps \
  -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli --help
```

Expected: CLI help succeeds without restarting the healthy long-running services.

- [x] **Step 2: Generate JSON and Markdown from one frozen database snapshot**

```bash
docker compose run --rm --no-deps \
  -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli \
  v2-true-leader-wave-study --format json \
  --output memory/06_backtests/low_suction_true_leader_wave_study_20260717.json

docker compose run --rm --no-deps \
  -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli \
  v2-true-leader-wave-study --format markdown \
  --output memory/06_backtests/low_suction_true_leader_wave_study_20260717.md
```

Expected: both reports share the same input fingerprints and metric values.

- [x] **Step 3: Inspect conclusions before updating memory**

Record actual sample counts, causal versus baseline block metrics, whether early ignition led concept start, successful versus terminal wave support distributions, and the exact wave ledgers for the three references. Do not claim a winning low-suction strategy or formal Top3.

- [x] **Step 4: Update durable memory in place**

Link both artifacts from `memory/06_backtests/README.md`. Replace the stale next-work entry in `memory/09_decisions/decisions.md` with the current identity result, historical-membership limitation and next valid stage: low-suction entry research only after identity evidence is accepted.

- [x] **Step 5: Run final verification**

```bash
uv run pytest tests/alphaagent/services/low_suction -q
uvx ruff check alphaagent/server/services/low_suction tests/alphaagent/services/low_suction
uv run python -m compileall -q alphaagent/server/services/low_suction
uv run python -m json.tool memory/06_backtests/low_suction_true_leader_wave_study_20260717.json >/dev/null
git diff --check
```

Expected: all checks pass. Do not commit, push, authorize a holdout, create a production strategy or restart the healthy API.

## Self-Review

- The plan identifies stock campaigns before studying an entry; it does not filter old losing trades until a rule looks profitable.
- Future higher highs only construct retrospective truth and terminal labels. Causal rank code rejects those fields.
- The broad sample includes all qualified current-member proxy stocks, not only event winners or hand-picked examples.
- Current membership and current ST filters are never represented as historical point-in-time truth.
- The 2026 examples are visibly quarantined because they have already been inspected.
- The algorithm does not attribute a formula to a forum identity, brokerage seat or unverified natural person.
- A first-wave leader can rank as truth even without a second wave; second/third waves require ordered higher-high confirmation.
- Shanghai Construction remains a terminal counterexample instead of being deleted from the sample.
- No low-suction win rate, return, compounding or production Top3 is emitted by this identity-only stage.
