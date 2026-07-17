# Low-Suction Research Direction V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Project policy forbids subagent dispatch and forbids commits unless the user explicitly requests them.

**Goal:** Build a no-lookahead research pipeline that discovers executable intraday pullback rules from all main-rise concept Top3 state transitions, independently validates leader identity and public hot-money cases, and returns either one qualified rule or `no_qualified_strategy`.

**Architecture:** V1 family-based modules remain readable only as archived evidence. V2 freezes a versioned protocol, then studies concept cycles, leader identity, intraday state transitions, outcomes, exits, and portfolio constraints in that order. Every stage consumes immutable artifacts from the prior stage; the last 20% holdout is inaccessible until one complete strategy package is frozen.

**Tech Stack:** Python 3.11+, pandas, NumPy, scikit-learn `DecisionTreeRegressor`, SQLAlchemy Core, PostgreSQL 16, pytest, existing `services.execution.cash_ledger`.

---

## File Structure

New files have one responsibility each:

- `research_protocol.py`: protocol version, research stages, data fingerprint, rolling splits, holdout lock.
- `concept_cycles.py`: three main-rise definitions, cycle hysteresis, definition-only evaluation.
- `leader_identity.py`: three non-weighted Top3 identity rules and rank-stability evaluation.
- `v2_repository.py`: strict as-of reads and daily research bundles; no current-member fallback.
- `v2_minute_manifest.py`: exact Top3/date minute coverage and provider gap requests.
- `intraday_panel.py`: point-in-time continuous minute state features, without outcomes.
- `state_observations.py`: neutral block identities and inverse-block weights for all minute states.
- `state_transitions.py`: first false-to-true occurrence of a frozen discovered predicate.
- `v2_outcomes.py`: next-minute fills, fixed exits, MFE/MAE and cost stress, isolated from features.
- `response_surface.py`: train-only quantile bins and deterministic response cells.
- `candidate_discovery.py`: shallow-tree suggestion, readable rule extraction, five-candidate cap.
- `hot_money_cases.py`: source quality, case identity, matched controls and rejection reasons.
- `experiment_ledger.py`: every attempted complete pipeline and immutable configuration hash.
- `pipeline_validation.py`: rolling validation, block bootstrap, concentration gates and one-shot holdout.
- `portfolio_research.py`: fixed-exit cash compounding and frozen 1/2/3/4-position comparison.
- `v2_reporting.py`: deterministic JSON/Markdown artifacts and the three allowed conclusions.

Existing V1 files such as `events.py`, `daily_discovery.py`, `leader_rank.py` and
`proxy_reporting.py` are not imported by V2.

## Fixed Protocol

```python
PROTOCOL_VERSION = "low-suction-research-v2"
CYCLE_CONTRACT_VERSION = "entry-gate-common-trend-sustain-v1"
HOLDOUT_FRACTION = 0.20
ROLLING_FOLDS = 5
EMBARGO_TRADE_DAYS = 5
MAX_DISCOVERY_RULES = 5
TREE_MAX_DEPTH = 2
TREE_MIN_EPISODES_PER_LEAF = 100
MIN_VALIDATION_EPISODES = 100
MIN_HOLDOUT_TRADES = 300
MIN_HOLDOUT_WIN_RATE_PCT = 60.0
MIN_HOLDOUT_COMPOUNDED_RETURN_PCT = 60.0
MAX_DRAWDOWN_PCT = -10.0
MAX_CONTRIBUTION_SHARE = 0.20
MIN_MATERIAL_REGIME_DAYS = 20
MIN_REGIME_CLOSED_TRADES = 30
MIN_REGIME_WIN_RATE_PCT = 60.0
MIN_TRADED_REGIMES = 2
SLIPPAGE_BPS = 10.0
```

No task in this plan adds frontend UI, alerts, simulation, positions, or order routing.

### Task 1: Archive V1 Selection And Freeze The V2 Protocol

**Files:**
- Create: `alphaagent/server/services/low_suction/research_protocol.py`
- Create: `tests/alphaagent/services/low_suction/test_research_protocol.py`
- Modify: `alphaagent/server/services/low_suction/cli.py`
- Modify: `requirements/alphaagent_low_suction_research_implementation_plan.md`

- [x] **Step 1: Write protocol and holdout-lock tests**

```python
def test_outer_holdout_is_not_returned_to_discovery_stage() -> None:
    protocol = default_protocol()
    split = build_protocol_split(_dates(100), protocol)
    assert len(split.discovery_dates) == 80
    assert len(split.holdout_dates) == 20
    assert set(split.discovery_dates).isdisjoint(split.holdout_dates)


def test_holdout_requires_one_frozen_pipeline_hash() -> None:
    lock = HoldoutLock.create("sha256:pipeline-a")
    lock.authorize("sha256:pipeline-a")
    with pytest.raises(HoldoutAccessError, match="frozen pipeline hash"):
        lock.authorize("sha256:pipeline-b")
```

- [x] **Step 2: Run the tests and verify failure**

Run:

```bash
uv run --group server pytest tests/alphaagent/services/low_suction/test_research_protocol.py -q
```

Expected: import failure for `research_protocol`.

- [x] **Step 3: Implement immutable protocol objects**

```python
class ResearchStage(StrEnum):
    COVERAGE = "coverage"
    CYCLE_SELECTION = "cycle_selection"
    LEADER_SELECTION = "leader_selection"
    STATE_DISCOVERY = "state_discovery"
    PIPELINE_VALIDATION = "pipeline_validation"
    LOCKED_HOLDOUT = "locked_holdout"


@dataclass(frozen=True)
class ResearchProtocol:
    version: str = "low-suction-research-v2"
    cycle_contract_version: str = "entry-gate-common-trend-sustain-v1"
    holdout_fraction: float = 0.20
    rolling_folds: int = 5
    embargo_trade_days: int = 5
    max_discovery_rules: int = 5
    tree_max_depth: int = 2
    tree_min_episodes_per_leaf: int = 100
    min_holdout_win_rate_pct: float = 60.0
    min_holdout_compounded_return_pct: float = 60.0
    min_material_regime_days: int = 20
    min_regime_closed_trades: int = 30
    min_regime_win_rate_pct: float = 60.0
    min_traded_regimes: int = 2


@dataclass(frozen=True)
class RollingFold:
    train_dates: tuple[date, ...]
    validation_dates: tuple[date, ...]


@dataclass(frozen=True)
class ProtocolSplit:
    discovery_dates: tuple[date, ...]
    holdout_dates: tuple[date, ...]
    rolling_folds: tuple[RollingFold, ...]


class HoldoutAccessError(RuntimeError):
    pass


@dataclass
class HoldoutLock:
    frozen_pipeline_hash: str
    access_count: int = 0

    @classmethod
    def create(cls, frozen_pipeline_hash: str) -> "HoldoutLock":
        return cls(frozen_pipeline_hash=frozen_pipeline_hash)

    def authorize(self, candidate_hash: str) -> None:
        if candidate_hash != self.frozen_pipeline_hash:
            raise HoldoutAccessError("candidate does not match frozen pipeline hash")
        if self.access_count:
            raise HoldoutAccessError("locked holdout has already been evaluated")
        self.access_count += 1


def default_protocol() -> ResearchProtocol:
    return ResearchProtocol()


def build_protocol_split(
    values: Sequence[date],
    protocol: ResearchProtocol,
) -> ProtocolSplit:
    dates = tuple(sorted(set(values)))
    if len(dates) < 100:
        raise ValueError("at least 100 unique dates are required")
    holdout_size = max(1, math.ceil(len(dates) * protocol.holdout_fraction))
    discovery_dates = dates[:-holdout_size]
    holdout_dates = dates[-holdout_size:]
    boundaries = np.linspace(
        0,
        len(discovery_dates),
        protocol.rolling_folds + 2,
        dtype=int,
    )
    folds = []
    for index in range(1, protocol.rolling_folds + 1):
        validation_start = int(boundaries[index])
        validation_end = int(boundaries[index + 1])
        training_end = validation_start - protocol.embargo_trade_days
        if training_end <= 0 or validation_end <= validation_start:
            raise ValueError("rolling fold is empty after embargo")
        folds.append(
            RollingFold(
                train_dates=discovery_dates[:training_end],
                validation_dates=discovery_dates[validation_start:validation_end],
            )
        )
    return ProtocolSplit(discovery_dates, holdout_dates, tuple(folds))
```

`build_protocol_split()` sorts unique dates, assigns the final 20% to holdout, creates five expanding
training/validation folds inside the first 80%, and removes five embargo dates before each validation
window. Reject fewer than 100 unique dates. Implement it by computing `holdout_size = ceil(n * 0.20)`,
splitting the discovery dates into six ordered boundaries with `numpy.linspace`, and creating folds 1-5
whose training range starts at date zero and whose validation range is the next boundary segment after
removing the final five training dates as embargo.

The implemented `HoldoutLock` additionally persists canonical JSON plus an atomically created `.used`
marker. Restarting or crashing the process cannot reset a consumed holdout authorization.

- [x] **Step 4: Mark V1 CLI output archived**

Keep `proxy-discovery` reproducible, but add these immutable fields to its output:

```python
{
    "status": "archived_membership_proxy",
    "selectable_for_v2": False,
    "superseded_by": "low-suction-research-v2",
}
```

Add a `v2-protocol --format json` command that prints only the protocol and date split; it performs
no database writes.

- [x] **Step 5: Run focused tests and diff check**

```bash
uv run --group server pytest tests/alphaagent/services/low_suction/test_research_protocol.py tests/alphaagent/services/low_suction/test_reporting.py -q
git diff --check
```

Expected: all selected tests pass and diff check is silent.

### Task 2: Research Main-Rise Cycles Without Stock Trade Returns

**Files:**
- Create: `alphaagent/server/services/low_suction/concept_cycles.py`
- Create: `tests/alphaagent/services/low_suction/test_concept_cycles.py`
- Create: `memory/06_backtests/low_suction_v2_cycle_study_20260716.md`
- Modify: `alphaagent/server/services/low_suction/cli.py`

- [x] **Step 1: Write no-lookahead and outcome-isolation tests**

```python
def test_future_concept_bar_does_not_change_prior_cycle_state() -> None:
    original = build_cycle_candidates(_concept_bars(), _market_returns())
    mutated = build_cycle_candidates(_concept_bars(future_close=9999), _market_returns())
    pd.testing.assert_frame_equal(
        original.loc[original.trade_date <= "2026-06-30"],
        mutated.loc[mutated.trade_date <= "2026-06-30"],
    )


def test_cycle_research_rejects_stock_outcome_columns() -> None:
    bars = _concept_bars().assign(net_return_pct=10.0)
    with pytest.raises(ValueError, match="outcome columns"):
        build_cycle_candidates(bars, _market_returns())
```

Also test sparse concept dates, a one-day MA break inside hysteresis, a three-day break ending a cycle,
same-day relative ranks remaining unchanged by future dates, common sustain behavior and holdout-value rejection.

- [x] **Step 2: Implement the three candidate definitions**

```python
class CycleDefinition(StrEnum):
    TREND_ORDER = "trend_order"
    BREAKOUT_TREND = "breakout_trend"
    RELATIVE_TREND = "relative_trend"


def build_cycle_candidates(
    concept_bars: pd.DataFrame,
    market_returns: pd.DataFrame,
) -> pd.DataFrame:
    prohibited = {"net_return_pct", "mfe_pct", "mae_pct"} & set(concept_bars)
    if prohibited:
        raise ValueError(f"outcome columns are not allowed: {sorted(prohibited)}")
    frame = concept_bars.sort_values(["sector_id", "trade_date"]).copy()
    grouped_close = frame.groupby("sector_id", sort=False)["close_price"]
    frame["ma10"] = grouped_close.transform(lambda values: values.rolling(10).mean())
    frame["ma20"] = grouped_close.transform(lambda values: values.rolling(20).mean())
    frame["ma10_shift_5"] = frame.groupby("sector_id", sort=False)["ma10"].shift(5)
    frame["ma20_shift_5"] = frame.groupby("sector_id", sort=False)["ma20"].shift(5)
    frame["high20"] = grouped_close.transform(lambda values: values.rolling(20).max())
    frame = frame.merge(market_returns, on="trade_date", how="left", validate="many_to_one")
    frame["relative_10d"] = (
        grouped_close.pct_change(10) - frame["market_return_10d"]
    )
    frame["relative_percentile"] = frame.groupby("trade_date")["relative_10d"].rank(pct=True)
    trend = (
        (frame["close_price"] > frame["ma10"])
        & (frame["ma10"] > frame["ma20"])
        & (frame["ma10"] > frame["ma10_shift_5"])
        & (frame["ma20"] > frame["ma20_shift_5"])
    )
    definitions = {
        CycleDefinition.TREND_ORDER: trend,
        CycleDefinition.BREAKOUT_TREND: trend & (frame["close_price"] >= frame["high20"]),
        CycleDefinition.RELATIVE_TREND: trend & (frame["relative_percentile"] >= 0.80),
    }
    rows = []
    for definition, entry_qualifies in definitions.items():
        candidate = frame.assign(
            definition=definition.value,
            qualifies=entry_qualifies,
            entry_qualifies=entry_qualifies,
            sustain_qualifies=trend,
        )
        rows.append(apply_three_day_hysteresis(candidate))
    return pd.concat(rows, ignore_index=True)


def evaluate_cycle_definitions(
    candidates: pd.DataFrame,
    *,
    evaluation_dates: Sequence[date],
) -> pd.DataFrame:
    # Use exact calendar-position joins, not row shifts across missing dates.
    # Persistence contributes once per cycle start, never once per active day.
    ...
```

Return definition, state, globally unique cycle ID, state age, cycle-start 1/3-day persistence,
false-start outcome and completed duration. Do not accept stock bars, stock returns or low-suction outcomes.

- [x] **Step 3: Implement deterministic cycle hysteresis**

A cycle enters on the first definition-specific `entry_qualifies` day. All three definitions then use
the common `trend_order` value in `sustain_qualifies`; the exit is effective on its third consecutive
sustain miss and never rewritten by later data. This prevents stricter entry gates from being unfairly
reused as stricter exits. `false_start` is written only on a completed exit row when fewer than three
common sustain days occurred; prior point-in-time state rows remain null.

- [x] **Step 4: Add rolling-fold selection**

For each protocol fold, rank definitions by:

```text
three_day_persistence_rate DESC
false_start_rate ASC
median_cycle_days DESC
definition_name ASC
```

The selected definition must win at least three of five folds; otherwise return
`no_stable_main_rise_definition` and stop downstream research.

The corrected real run selected `breakout_trend` in five of five folds. Its discovery-stage 3-day
cycle persistence is `98.53%`, false-start rate `5.35%`, and median completed cycle length 12 days.
These are concept-state metrics, not stock-trade win rate or return. The first daily-qualifier-as-exit
run was rejected as definitionally biased and is not a selectable experiment.

- [x] **Step 5: Verify**

```bash
uv run --group server pytest tests/alphaagent/services/low_suction/test_concept_cycles.py -q
```

### Task 3: Replace Weighted Top3 With Leader Identity Research

**Files:**
- Create: `alphaagent/server/services/low_suction/leader_identity.py`
- Create: `tests/alphaagent/services/low_suction/test_leader_identity.py`

- [x] **Step 1: Write identity and timestamp tests**

```python
def test_lexicographic_rank_does_not_sum_arbitrary_weights() -> None:
    ranked = rank_leader_identities(_leader_features(), mode="market_recognition_lexicographic")
    assert ranked.loc[0, "vt_symbol"] == "000001.SZSE"
    assert "leader_score" not in ranked.columns


def test_d_plus_one_prices_cannot_change_d_top3() -> None:
    before = rank_leader_identities(_leader_features(), mode="cycle_relative_strength")
    after = rank_leader_identities(_leader_features(future_return=99), mode="cycle_relative_strength")
    pd.testing.assert_frame_equal(before, after)
```

Test strict membership validity at D 09:25, current-member rejection, main-board filtering, capacity
tie-breaks and deterministic symbol ties.

- [x] **Step 2: Implement three leader modes**

```python
class LeaderIdentityMode(StrEnum):
    CYCLE_RELATIVE_STRENGTH = "cycle_relative_strength"
    MARKET_RECOGNITION = "market_recognition_lexicographic"
    RECOGNITION_CONSENSUS = "recognition_consensus"


def rank_leader_identities(
    features: pd.DataFrame,
    *,
    mode: LeaderIdentityMode | str,
) -> pd.DataFrame:
    frame = features.copy()
    group = ["trade_date", "sector_id"]
    selected_mode = LeaderIdentityMode(mode)
    if selected_mode == LeaderIdentityMode.CYCLE_RELATIVE_STRENGTH:
        order = ["cycle_relative_return", "turnover_median_20d", "vt_symbol"]
        ascending = [False, False, True]
        ranked = frame.sort_values([*group, *order], ascending=[True, True, *ascending])
    else:
        order = [
            "strong_day_count_cycle",
            "sessions_since_strong",
            "cycle_relative_return",
            "turnover_median_20d",
            "vt_symbol",
        ]
        ascending = [False, True, False, False, True]
        ranked = frame.sort_values([*group, *order], ascending=[True, True, *ascending])
        if selected_mode == LeaderIdentityMode.RECOGNITION_CONSENSUS:
            ranked = ranked.loc[
                (ranked["relative_strength_rank"] <= 5)
                & (ranked["market_recognition_rank"] <= 5)
            ]
    ranked["rank"] = ranked.groupby(group, sort=False).cumcount() + 1
    ranked["is_top3"] = ranked["rank"] <= 3
    ranked["identity_mode"] = selected_mode.value
    return ranked.reset_index(drop=True)
```

`MARKET_RECOGNITION` sorts by strong-day count descending, sessions since strong ascending, cycle
relative return descending, turnover median descending, then symbol ascending. `CONSENSUS` takes rows
ranked at most five by both first modes and applies the market-recognition order.

- [x] **Step 3: Evaluate identity without low-suction PnL**

```python
def evaluate_leader_identity(ranks: pd.DataFrame) -> pd.DataFrame:
    return (
        ranks.groupby("identity_mode", as_index=False)
        .agg(
            ranked_days=("trade_date", "nunique"),
            next_day_top3_retention=("retained_top3_next_day", "mean"),
            strong_event_lead_sessions=("sessions_to_next_strong_event", "median"),
            capacity_pass_rate=("capacity_passed", "mean"),
        )
        .sort_values("identity_mode")
        .reset_index(drop=True)
    )
```

Select a mode by next-day Top3 retention, then strong-event lead time and capacity. Require the same
winner in at least three rolling folds. If no mode is stable, stop with `no_stable_top3_identity`.

The three algorithms and rolling selector are implemented. They reject current membership, incomplete
scope, evidence known after D 09:25, non-strict security history and unsupported boards. The current
database has zero strict membership dates and zero strict security dates, so `selected_mode=null`; no
proxy winner is allowed.

- [x] **Step 4: Verify and prove V2 does not import V1 ranker**

```bash
uv run --group server pytest tests/alphaagent/services/low_suction/test_leader_identity.py -q
rg -n "from .*leader_rank|import leader_rank" alphaagent/server/services/low_suction/leader_identity.py
```

Expected: tests pass; `rg` returns no matches.

### Task 4: Add Strict Daily Bundles And Candidate Minute Manifests

**Files:**
- Create: `alphaagent/server/services/low_suction/v2_repository.py`
- Create: `alphaagent/server/services/low_suction/v2_minute_manifest.py`
- Create: `tests/alphaagent/services/low_suction/test_v2_repository.py`
- Create: `tests/alphaagent/services/low_suction/test_v2_minute_manifest.py`
- Modify: `alphaagent/server/services/low_suction/cli.py`

- [ ] **Step 1: Test fail-closed source selection**

```python
def test_v2_repository_never_falls_back_to_current_members() -> None:
    source = Path("alphaagent/server/services/low_suction/v2_repository.py").read_text()
    assert "low_suction_concept_membership_history" in source
    assert "low_suction_concept_membership_scopes" in source
    assert "stock_sector_memberships" not in source


def test_missing_scope_blocks_daily_bundle() -> None:
    with pytest.raises(StrictBundleUnavailable, match="membership scope"):
        load_strict_day_bundle(date(2026, 7, 16))
```

- [ ] **Step 2: Implement `StrictDayBundle`**

```python
class StrictBundleUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class StrictDayBundle:
    trade_date: date
    source_trade_date: date
    concept_bars: pd.DataFrame
    memberships: pd.DataFrame
    security_status: pd.DataFrame
    stock_daily_bars: pd.DataFrame
    stock_minute_bars: pd.DataFrame
    timing_labels: pd.DataFrame
    fingerprint: str
```

The repository validates source date earlier than trade date, scope coverage at least 90%, strict
security rows for every evaluated symbol, canonical concept bars and exact minute uniqueness.

- [ ] **Step 3: Build minute manifests from frozen Top3 spells**

```python
def build_v2_minute_manifest(
    leader_spells: pd.DataFrame,
    existing_minutes: pd.DataFrame,
) -> pd.DataFrame:
    pairs = leader_spells[["trade_date", "vt_symbol"]].drop_duplicates()
    counts = (
        existing_minutes.groupby(["trade_date", "vt_symbol"])
        .agg(
            existing_minutes=("bar_time", "nunique"),
            raw_rows=("bar_time", "size"),
            first_minute=("bar_time", "min"),
            last_minute=("bar_time", "max"),
            provider=("source", lambda values: ",".join(sorted(set(values)))),
        )
        .reset_index()
    )
    result = pairs.merge(counts, on=["trade_date", "vt_symbol"], how="left")
    result["required_minutes"] = 240
    result["existing_minutes"] = result["existing_minutes"].fillna(0).astype(int)
    result["raw_rows"] = result["raw_rows"].fillna(0).astype(int)
    result["duplicate_count"] = result["raw_rows"] - result["existing_minutes"]
    result["status"] = np.select(
        [
            result["duplicate_count"] > 0,
            result["existing_minutes"] == 0,
            result["existing_minutes"] < result["required_minutes"],
        ],
        ["invalid", "missing", "incomplete"],
        default="complete",
    )
    return result.sort_values(["trade_date", "vt_symbol"]).reset_index(drop=True)
```

Each row includes date, symbol, required `09:30-15:00` minutes, existing count, duplicate count,
first/last minute, provider and status `complete/incomplete/missing/invalid`. The manifest contains
Top3 and Rank 4-10 controls only, never the full market.

- [ ] **Step 4: Add read-only CLI commands**

```text
v2-audit --format json
v2-minute-manifest --start YYYY-MM-DD --end YYYY-MM-DD --format json
```

On the current database, `v2-audit` must return `blocked_by_data_quality`, zero strict historical
membership dates, zero strict security-history dates and `formal_metrics=null`. It must separately return
`cycle_stage=ready` because canonical concept indices already cover 800 reliable dates, while
`leader_stage/state_stage/validation_stage=blocked`.

`v2-audit` is implemented and also exposes the strict `>60%` overall win/compound targets and material
market-regime gates. `v2-minute-manifest` remains pending until a strict Top3 mode can be selected.

- [ ] **Step 5: Verify**

```bash
uv run --group server pytest tests/alphaagent/services/low_suction/test_v2_repository.py tests/alphaagent/services/low_suction/test_v2_minute_manifest.py -q
docker compose exec -T alphaagent-api python -m alphaagent.server.services.low_suction.cli v2-audit --format json
```

### Task 5: Build The Outcome-Free Intraday State Panel

**Files:**
- Create: `alphaagent/server/services/low_suction/intraday_panel.py`
- Create: `tests/alphaagent/services/low_suction/test_intraday_panel.py`

- [ ] **Step 1: Write point-in-time feature tests**

```python
def test_vwap_at_1000_uses_only_bars_through_1000() -> None:
    panel = build_intraday_state_panel(_bundle(), _leaders())
    row = panel.loc[panel.bar_time == "2026-06-01 10:00:00"].iloc[0]
    assert row.vwap == pytest.approx(_manual_vwap(end="10:00"))


def test_future_low_and_outcomes_are_rejected() -> None:
    bars = _minute_bars().assign(session_final_low=1.0)
    with pytest.raises(ValueError, match="future or outcome"):
        build_intraday_state_panel(_bundle(minutes=bars), _leaders())
```

Test ATR using D-1 and earlier daily bars, known supports from D-1, lunch gaps, zero turnover, missing
concept minutes, preopen versus dynamic rank mode, and all board exclusions.

- [ ] **Step 2: Define the exact feature schema**

```python
STATE_FEATURE_COLUMNS = (
    "drawdown_from_session_high_pct",
    "drawdown_from_cycle_high_atr",
    "distance_to_previous_close_pct",
    "distance_to_open_pct",
    "distance_to_vwap_pct",
    "distance_to_previous_high_pct",
    "distance_to_ma5_pct",
    "distance_to_ma10_pct",
    "return_1m_pct",
    "return_3m_pct",
    "return_5m_pct",
    "volume_ratio_same_minute_20d",
    "relative_to_concept_3m_pct",
    "relative_to_other_top3_3m_pct",
    "concept_rise_ratio",
    "concept_diffusion_change_3m",
    "concept_state_age",
    "minutes_from_open",
)
```

Identity columns include protocol, cycle, leader spell, concept, symbol, bar time, membership source,
rank mode and evidence level. Timing labels are context columns, not features used in base discovery.

- [ ] **Step 3: Implement chunked daily calculation**

`iter_intraday_state_panels()` yields one trading day at a time. It never concatenates the full
three-year minute set in memory. All rolling calculations are grouped by symbol and sorted by time.

- [ ] **Step 4: Verify**

```bash
uv run --group server pytest tests/alphaagent/services/low_suction/test_intraday_panel.py -q
```

### Task 6: Create Neutral State Observations Without Shape Filters

**Files:**
- Create: `alphaagent/server/services/low_suction/state_observations.py`
- Create: `tests/alphaagent/services/low_suction/test_state_observations.py`

- [ ] **Step 1: Test neutral block identity and weights**

```python
def test_every_minute_state_is_retained_before_discovery() -> None:
    observations = build_state_observations(_panel(rows=240))
    assert len(observations) == 240
    assert observations[STATE_FEATURE_COLUMNS].notna().all().all()


def test_each_date_cycle_block_has_total_weight_one() -> None:
    observations = build_state_observations(_panel_with_correlated_leaders())
    totals = observations.groupby("independence_block_id")["sample_weight"].sum()
    assert np.allclose(totals.to_numpy(), 1.0)
```

Also test that non-main-rise rows, non-Top3 rows, invalid minute rows and duplicate symbol/minute rows are
rejected rather than silently removed. No return or outcome column is accepted.

- [ ] **Step 2: Implement all-state observation rows**

```python
def build_state_observations(panel: pd.DataFrame) -> pd.DataFrame:
    prohibited = {"net_return_pct", "mfe_pct", "mae_pct"} & set(panel)
    if prohibited:
        raise ValueError(f"outcomes are not allowed in observations: {sorted(prohibited)}")
    identity = ["trade_date", "concept_cycle_id", "leader_spell_id", "bar_time", "vt_symbol"]
    if panel.duplicated(identity).any():
        raise ValueError("state observation identity must be unique")
    frame = panel.loc[panel["main_rise"] & panel["is_top3"] & panel["minute_valid"]].copy()
    frame["independence_block_id"] = (
        frame["trade_date"].astype(str) + ":" + frame["concept_cycle_id"].astype(str)
    )
    size = frame.groupby("independence_block_id")["bar_time"].transform("size")
    frame["sample_weight"] = 1.0 / size
    frame["observed_at"] = frame["bar_time"]
    frame["observation_id"] = (
        frame["leader_spell_id"].astype(str) + ":" + frame["bar_time"].astype(str)
    )
    return frame.sort_values(identity).reset_index(drop=True)
```

This step deliberately keeps every valid Top3 minute state. The inverse-block weight prevents one busy
concept day from dominating discovery, while later bootstrap still samples whole date/cycle blocks.

- [ ] **Step 3: Add deterministic chunk output**

Yield observations one date at a time and include the source bundle fingerprint. The runner aggregates
response cells and model inputs incrementally; it does not write a second raw minute database.

- [ ] **Step 4: Verify V1 family and transition names are absent**

```bash
uv run --group server pytest tests/alphaagent/services/low_suction/test_state_observations.py -q
rg -n "first_divergence|break_repair|second_wave|vwap_reclaim|support_reclaim" \
  alphaagent/server/services/low_suction/state_observations.py
```

Expected: tests pass and `rg` returns no matches.

### Task 7: Label Next-Minute Execution And Fixed Outcomes

**Files:**
- Create: `alphaagent/server/services/low_suction/v2_outcomes.py`
- Create: `tests/alphaagent/services/low_suction/test_v2_outcomes.py`
- Reuse without modifying behavior: `alphaagent/server/services/execution/cash_ledger.py`

- [ ] **Step 1: Write execution tests**

```python
def test_signal_fills_at_next_minute_open_with_costs() -> None:
    outcomes = label_v2_outcomes(_observation(observed_at="10:00"), _minutes(), _daily_bars())
    row = outcomes.loc[outcomes.exit_key == "d1_1430"].iloc[0]
    assert row.entry_time == Timestamp("2026-06-01 10:01:00")
    assert row.entry_price > _raw_open("10:01")


def test_same_day_exit_is_not_available_under_t_plus_one() -> None:
    with pytest.raises(ValueError, match="T\+1"):
        label_v2_outcomes(
            _observation(),
            _minutes(),
            _daily_bars(),
            exit_keys=("d0_close",),
        )
```

Cover suspension, no next bar, zero volume, limit-up rejection, limit-down exit lock, lunch, 14:55
signal cutoff, 100-share lots, minimum commission and double-cost mode.

- [ ] **Step 2: Implement isolated outcome labels**

```python
V2_EXIT_KEYS = ("d1_1000", "d1_1430", "d1_close", "d3_close", "d5_close")


def label_v2_outcomes(
    observations: pd.DataFrame,
    minute_bars: pd.DataFrame,
    daily_bars: pd.DataFrame,
    *,
    exit_keys: Sequence[str] = V2_EXIT_KEYS,
    cost_multiplier: float = 1.0,
) -> pd.DataFrame:
    minute_index = minute_bars.sort_values("bar_time").set_index(["vt_symbol", "bar_time"])
    daily_index = daily_bars.set_index(["vt_symbol", "trade_date"])
    records = []
    for observation in observations.sort_values(["observed_at", "observation_id"]).to_dict("records"):
        later = minute_bars.loc[
            (minute_bars["vt_symbol"] == observation["vt_symbol"])
            & (minute_bars["trade_date"] == observation["trade_date"])
            & (minute_bars["bar_time"] > observation["observed_at"])
        ].sort_values("bar_time")
        if later.empty:
            records.extend(
                rejected_outcome_rows(observation, exit_keys, "missing_next_minute_bar")
            )
            continue
        entry_bar = later.iloc[0]
        records.extend(
            execute_fixed_exits(
                observation,
                entry_bar,
                minute_index,
                daily_index,
                exit_keys=exit_keys,
                cost_multiplier=cost_multiplier,
            )
        )
    return pd.DataFrame.from_records(records)
```

Output includes raw and net return, MFE/MAE, entry/exit status and rejection reason. It contains no
feature-generation function and cannot be imported by `intraday_panel.py` or `state_transitions.py`.
Implement `rejected_outcome_rows()` as one rejection row per exit key. Implement
`execute_fixed_exits()` with `cash_ledger.calculate_buy_execution()` and
`cash_ledger.calculate_sell_execution()`, mapping the five exit keys to exact D+1/D+3/D+5 timestamps;
it rejects same-day exits, missing bars, suspension and locked limit prices before calculating MFE/MAE.

- [ ] **Step 3: Add import-boundary test**

```python
def test_feature_modules_do_not_import_outcomes() -> None:
    for path in (
        "intraday_panel.py",
        "state_observations.py",
        "state_transitions.py",
        "leader_identity.py",
    ):
        source = (LOW_SUCTION_DIR / path).read_text()
        assert "v2_outcomes" not in source
```

- [ ] **Step 4: Verify**

```bash
uv run --group server pytest tests/alphaagent/services/low_suction/test_v2_outcomes.py -q
```

### Task 8: Build Train-Only Response Surfaces And Candidate Discovery

**Files:**
- Create: `alphaagent/server/services/low_suction/response_surface.py`
- Create: `alphaagent/server/services/low_suction/candidate_discovery.py`
- Create: `alphaagent/server/services/low_suction/state_transitions.py`
- Create: `tests/alphaagent/services/low_suction/test_response_surface.py`
- Create: `tests/alphaagent/services/low_suction/test_candidate_discovery.py`
- Create: `tests/alphaagent/services/low_suction/test_state_transitions.py`

- [ ] **Step 1: Test train-only bins**

```python
def test_validation_extreme_does_not_change_training_quantiles() -> None:
    fitted = fit_response_bins(_development_rows())
    transformed = apply_response_bins(_validation_rows(extreme=999), fitted)
    assert fitted.edges == fit_response_bins(_development_rows()).edges
    assert transformed.iloc[0].drawdown_bin == "above_q80"
```

Test empty cells, fewer than 30 independent date/cycle blocks, grouped counts and deterministic cell ordering.

- [ ] **Step 2: Implement fixed two-dimensional surfaces**

Produce exactly these surfaces using only the `d1_close` discovery label:

```python
SURFACES = (
    ("drawdown_from_session_high_pct", "relative_to_concept_3m_pct"),
    ("distance_to_vwap_pct", "volume_ratio_same_minute_20d"),
    ("concept_diffusion_change_3m", "relative_to_other_top3_3m_pct"),
    ("minutes_from_open", "drawdown_from_cycle_high_atr"),
)


@dataclass(frozen=True)
class FittedResponseBins:
    edges: dict[str, tuple[float, ...]]


def fit_response_bins(development: pd.DataFrame) -> FittedResponseBins:
    features = sorted({feature for surface in SURFACES for feature in surface})
    edges = {
        feature: tuple(
            float(value)
            for value in development[feature].quantile([0.2, 0.4, 0.6, 0.8]).to_numpy()
        )
        for feature in features
    }
    return FittedResponseBins(edges=edges)


def apply_response_bins(frame: pd.DataFrame, fitted: FittedResponseBins) -> pd.DataFrame:
    result = frame.copy()
    labels = ("q00_q20", "q20_q40", "q40_q60", "q60_q80", "above_q80")
    for feature, edges in fitted.edges.items():
        result[f"{feature}_bin"] = pd.cut(
            result[feature],
            bins=(-np.inf, *edges, np.inf),
            labels=labels,
            include_lowest=True,
        )
    return result
```

Each cell reports independent date/cycle blocks, raw observations, win rate, mean/median net return, profit factor, 5% tail,
MFE and MAE. No surface is declared a strategy.

- [ ] **Step 3: Test bounded shallow-tree discovery**

```python
def test_discovery_tree_is_bounded_and_not_a_signal_object() -> None:
    result = discover_candidate_rules(_development_dataset())
    assert result.model.get_depth() <= 2
    assert len(result.candidates) <= 5
    assert all(len(rule.conditions) <= 2 for rule in result.candidates)
    assert not hasattr(result.model, "generate_orders")


def test_non_discovery_exits_cannot_change_entry_candidates() -> None:
    original = discover_candidate_rules(_development_dataset())
    mutated = discover_candidate_rules(_development_dataset(d3_close_return=999.0))
    assert original.candidates == mutated.candidates


def test_predicate_true_at_first_minute_is_not_a_transition() -> None:
    rule = _candidate_rule(condition=("distance_to_vwap_pct", ">", 0.0))
    signals = materialize_rule_transitions(_panel(predicate_true_from_open=True), rule)
    assert signals.empty
```

- [ ] **Step 4: Implement deterministic discovery**

Use `DecisionTreeRegressor(max_depth=2, min_samples_leaf=100, random_state=0)` on the `d1_close`
net log return only. Pass `sample_weight` so each date/cycle block has total weight one. Fit one tree on
development folds only. Convert positive leaves into these immutable objects:

```python
@dataclass(frozen=True)
class RuleCondition:
    feature: str
    operator: str
    threshold: float


@dataclass(frozen=True)
class CandidateRule:
    rule_id: str
    conditions: tuple[RuleCondition, ...]


def materialize_rule_transitions(
    panel: pd.DataFrame,
    rule: CandidateRule,
) -> pd.DataFrame:
    frame = panel.sort_values(["leader_spell_id", "bar_time"]).copy()
    predicate = pd.Series(True, index=frame.index)
    operators = {
        "<=": lambda values, threshold: values <= threshold,
        ">": lambda values, threshold: values > threshold,
    }
    for condition in rule.conditions:
        predicate &= operators[condition.operator](frame[condition.feature], condition.threshold)
    prior = predicate.groupby(frame["leader_spell_id"], sort=False).shift(1)
    signals = frame.loc[
        predicate & prior.eq(False) & frame["main_rise"] & frame["is_top3"]
    ].copy()
    signals["observed_at"] = signals["bar_time"]
    signals["observation_id"] = (
        rule.rule_id + ":" + signals["leader_spell_id"].astype(str) + ":" + signals["bar_time"].astype(str)
    )
    return (
        signals.sort_values(["leader_spell_id", "trade_date", "bar_time"])
        .drop_duplicates(["leader_spell_id", "trade_date"], keep="first")
        .reset_index(drop=True)
    )
```

Recompute each candidate from the full source panel using the first false-to-true predicate transition,
then keep at most five ordered by rolling-development mean log return. This step does not assign names
such as VWAP reclaim, support reclaim, first divergence or second wave.

- [ ] **Step 5: Record all attempted candidates**

The result includes rejected leaves, sample counts, independent-block counts, thresholds, exit keys and
rejection reasons. A leaf with fewer than 100 independent date/cycle blocks, non-positive mean, or profit
factor at most 1 is rejected.

- [ ] **Step 6: Verify**

```bash
uv run --group server pytest tests/alphaagent/services/low_suction/test_response_surface.py tests/alphaagent/services/low_suction/test_candidate_discovery.py tests/alphaagent/services/low_suction/test_state_transitions.py -q
```

### Task 9: Build A Verifiable Hot-Money Case-Control Study

**Files:**
- Create: `alphaagent/server/services/low_suction/hot_money_cases.py`
- Create: `tests/alphaagent/services/low_suction/test_hot_money_cases.py`
- Create only when generated from verified rows: `memory/06_backtests/low_suction_hot_money_case_control_v2.md`
- Read: `memory/06_backtests/low_suction_hot_money_method_evidence.md`

- [ ] **Step 1: Test source quality and identity separation**

```python
def test_method_article_without_trade_identity_is_rejected_as_case() -> None:
    result = normalize_hot_money_case(_article_only_source())
    assert result.status == "rejected"
    assert result.reason == "missing_verifiable_trade_identity"


def test_seat_name_is_not_promoted_to_natural_person() -> None:
    case = normalize_hot_money_case(_dragon_tiger_row(seat_name="某营业部"))
    assert case.actor_kind == "public_seat_label"
    assert case.natural_person_verified is False
```

- [ ] **Step 2: Implement the case contract**

```python
@dataclass(frozen=True)
class HotMoneyCase:
    case_id: str
    trade_date: date
    vt_symbol: str
    direction: str
    source_url: str
    publication_date: date
    accessed_on: date
    source_grade: str
    actor_label: str | None
    actor_kind: str
    natural_person_verified: bool
    known_at: datetime


@dataclass(frozen=True)
class RejectedHotMoneyCase:
    status: str
    reason: str
    source_url: str
```

Require a date, stock, direction, source URL and known-at time. Existing S1-S7 methodology sources
without a specific auditable trade are recorded as rejected methodology evidence, not silently dropped.

- [ ] **Step 3: Build matched controls**

```python
def match_case_controls(
    cases: pd.DataFrame,
    leader_states: pd.DataFrame,
    *,
    controls_per_case: int = 5,
) -> pd.DataFrame:
    records = []
    context_columns = [
        "trade_date",
        "vt_symbol",
        "main_rise_definition",
        "concept_age_bucket",
        "leader_rank",
        "turnover_quintile",
    ]
    enriched_cases = cases.merge(
        leader_states[context_columns].drop_duplicates(["trade_date", "vt_symbol"]),
        on=["trade_date", "vt_symbol"],
        how="left",
        validate="many_to_one",
    )
    for case in enriched_cases.sort_values("case_id").to_dict("records"):
        eligible = leader_states.loc[
            (leader_states["trade_date"] == case["trade_date"])
            & (leader_states["main_rise_definition"] == case["main_rise_definition"])
            & (leader_states["concept_age_bucket"] == case["concept_age_bucket"])
            & (leader_states["leader_rank"] == case["leader_rank"])
            & (leader_states["turnover_quintile"] == case["turnover_quintile"])
            & (leader_states["vt_symbol"] != case["vt_symbol"])
        ].sort_values("vt_symbol")
        selected = eligible.head(controls_per_case)
        if len(selected) < 3:
            records.append({**case, "match_status": "unmatched", "control_vt_symbol": None})
            continue
        for control in selected.to_dict("records"):
            records.append(
                {
                    **case,
                    "match_status": "matched",
                    "control_vt_symbol": control["vt_symbol"],
                }
            )
    return pd.DataFrame.from_records(records)
```

Match on trade date, main-rise definition, concept-state age bucket, leader rank and turnover quintile.
Never match on future return. If fewer than three controls exist, mark the case `unmatched`.

- [ ] **Step 4: Compare behavior, not identity alpha**

Report transition frequencies, drawdown, relative strength, volume state and environment for cases versus
controls. Do not calculate a named person's win rate and do not use actor labels in candidate discovery.

- [ ] **Step 5: Verify**

```bash
uv run --group server pytest tests/alphaagent/services/low_suction/test_hot_money_cases.py -q
```

### Task 10: Add The Experiment Ledger And Rolling Pipeline Validation

**Files:**
- Create: `alphaagent/server/services/low_suction/experiment_ledger.py`
- Create: `alphaagent/server/services/low_suction/pipeline_validation.py`
- Create: `tests/alphaagent/services/low_suction/test_experiment_ledger.py`
- Create: `tests/alphaagent/services/low_suction/test_pipeline_validation.py`
- Create on first protocol run: `memory/06_backtests/low_suction_v2_experiment_ledger.json`

- [ ] **Step 1: Test immutable attempt accounting**

```python
def test_failed_candidate_is_kept_in_ledger() -> None:
    ledger = ExperimentLedger(protocol_version="low-suction-research-v2")
    ledger = ledger.record(_attempt(status="rejected", reason="negative_double_cost"))
    assert ledger.attempts[0].reason == "negative_double_cost"


def test_same_configuration_has_same_hash() -> None:
    assert pipeline_hash(_pipeline()) == pipeline_hash(_pipeline())
```

- [ ] **Step 2: Define one complete pipeline package**

```python
@dataclass(frozen=True)
class ExperimentAttempt:
    pipeline_hash: str
    status: str
    reason: str | None
    metrics: dict[str, float | int | None]


@dataclass(frozen=True)
class ExperimentLedger:
    protocol_version: str
    attempts: tuple[ExperimentAttempt, ...] = ()

    def record(self, attempt: ExperimentAttempt) -> "ExperimentLedger":
        return replace(self, attempts=(*self.attempts, attempt))


@dataclass(frozen=True)
class FrozenPipeline:
    protocol_version: str
    main_rise_definition: str
    leader_identity_mode: str
    rule_id: str
    conditions: tuple[RuleCondition, ...]
    exit_key: str
    position_count: int
    cost_multiplier: float = 1.0


@dataclass(frozen=True)
class PipelineMetrics:
    closed_trades: int
    win_rate_pct: float
    compounded_return_pct: float
    maximum_drawdown_pct: float
    profit_factor: float
    mean_net_return_pct: float


@dataclass(frozen=True)
class BootstrapInterval:
    mean_lower_bound: float
    mean_median: float
    mean_upper_bound: float
    compound_lower_bound: float
    compound_median: float
    compound_upper_bound: float


def pipeline_hash(pipeline: FrozenPipeline) -> str:
    payload = json.dumps(asdict(pipeline), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

The hash uses canonical JSON with sorted keys. Any changed condition, exit or position count produces a
new attempt and cannot reuse a prior holdout result. Save the complete immutable ledger as canonical JSON
through a temporary file plus `Path.replace()`; loading rejects a protocol-version or data-fingerprint
mismatch. The holdout authorization checks this persisted ledger so restarting the process cannot reset
the one-shot audit count.

The frozen package also includes one regime exposure table. All traded regimes share the same entry
predicate; the table can only choose `trade` or `cash`, never separate GOLD/SILVER entry thresholds.

- [ ] **Step 3: Implement rolling validation gates**

For every fold, rebuild cycle selection, ranks, bins and candidate thresholds using training dates only.
Validation requires at least 100 aggregate independent date/cycle blocks, positive net mean, profit factor above 1,
positive double-cost mean, consistent positive direction in at least four of five folds and concentration
share at most 20% for stock, concept and month.

- [ ] **Step 4: Implement grouped bootstrap**

Sample blocks by `(trade_date, concept_cycle_id)` with replacement, 2,000 deterministic resamples and
`random_state=0`. Report the 2.5/50/97.5 percentiles of net mean and compound return.

- [ ] **Step 5: Verify ledger, fold gates and bootstrap**

```bash
uv run --group server pytest tests/alphaagent/services/low_suction/test_experiment_ledger.py tests/alphaagent/services/low_suction/test_pipeline_validation.py -q
```

### Task 11: Evaluate Fixed Exits And Cash Positions Only After Entry Freeze

**Files:**
- Create: `alphaagent/server/services/low_suction/portfolio_research.py`
- Create: `tests/alphaagent/services/low_suction/test_portfolio_research.py`

- [ ] **Step 1: Write cash and ordering tests**

```python
def test_same_concept_cannot_hold_two_positions() -> None:
    result = simulate_v2_portfolio(_two_same_concept_signals(), position_count=2)
    assert result.metrics.closed_trades == 1
    assert result.rejections[0].reason == "same_concept_position_exists"


def test_position_search_rejects_unfrozen_entry_rule() -> None:
    with pytest.raises(ValueError, match="entry rule must be frozen"):
        compare_position_counts(_unfrozen_pipeline(), _outcomes())
```

Cover signal-time ordering, cash availability after actual sells, no leverage, lots, skipped signals,
simultaneous ties by expected rule strength then symbol, and double-cost parity.

- [ ] **Step 2: Implement fixed-exit comparison**

```python
@dataclass(frozen=True)
class PortfolioRejection:
    observation_id: str
    reason: str


@dataclass(frozen=True)
class PortfolioRun:
    metrics: PipelineMetrics
    trades: pd.DataFrame
    equity_curve: pd.DataFrame
    rejections: tuple[PortfolioRejection, ...]


def materialize_pipeline_signals(
    pipeline: FrozenPipeline,
    holdout: pd.DataFrame,
) -> pd.DataFrame:
    rule = CandidateRule(rule_id=pipeline.rule_id, conditions=pipeline.conditions)
    signals = materialize_rule_transitions(holdout, rule)
    return signals.assign(exit_key=pipeline.exit_key)
```

Compare the five V2 exits inside rolling training folds only. Freeze the exit with highest median fold
compound return among exits whose drawdown is at least `-10%` and double-cost compound return is positive.
Tie-break by lower drawdown, higher profit factor, then shorter holding period.

- [ ] **Step 3: Implement position-count comparison**

After exit freeze, compare 1/2/3/4 positions under identical signals. Apply the same eligibility and
tie-break order. The selected count becomes part of `FrozenPipeline` before validation and holdout.

- [ ] **Step 4: Enforce the one-shot holdout after portfolio implementation**

```python
@dataclass(frozen=True)
class HoldoutResult:
    conclusion: str
    normal: PipelineMetrics
    stressed: PipelineMetrics
    interval: BootstrapInterval


def evaluate_locked_holdout(
    pipeline: FrozenPipeline,
    holdout: pd.DataFrame,
    lock: HoldoutLock,
) -> HoldoutResult:
    lock.authorize(pipeline_hash(pipeline))
    signals = materialize_pipeline_signals(pipeline, holdout)
    normal_run = simulate_v2_portfolio(
        signals,
        position_count=pipeline.position_count,
        cost_multiplier=1.0,
    )
    stressed_run = simulate_v2_portfolio(
        signals,
        position_count=pipeline.position_count,
        cost_multiplier=2.0,
    )
    normal = normal_run.metrics
    stressed = stressed_run.metrics
    interval = grouped_bootstrap(normal_run.trades, samples=2_000, random_state=0)
    qualified = (
        normal.closed_trades >= 300
        and normal.win_rate_pct > 60.0
        and normal.compounded_return_pct > 60.0
        and normal.maximum_drawdown_pct >= -10.0
        and normal.profit_factor > 1.0
        and stressed.compounded_return_pct > 0
        and interval.mean_lower_bound > 0
        and regime_adaptation.qualified
    )
    return HoldoutResult(
        conclusion="qualified_research_rule" if qualified else "no_qualified_strategy",
        normal=normal,
        stressed=stressed,
        interval=interval,
    )
```

The function accepts one `FrozenPipeline`, never a list. A failed holdout returns
`no_qualified_strategy`; the caller cannot reopen the same `HoldoutLock` with revised conditions.

- [ ] **Step 5: Verify portfolio and holdout**

```bash
uv run --group server pytest tests/alphaagent/services/low_suction/test_portfolio_research.py tests/alphaagent/services/low_suction/test_pipeline_validation.py -q
```

### Task 12: Add Deterministic V2 Reports And Stage CLI

**Files:**
- Create: `alphaagent/server/services/low_suction/v2_reporting.py`
- Create: `tests/alphaagent/services/low_suction/test_v2_reporting.py`
- Modify: `alphaagent/server/services/low_suction/cli.py`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`

- [ ] **Step 1: Test conclusion exclusivity**

```python
@pytest.mark.parametrize(
    "status",
    ("blocked_by_data_quality", "no_qualified_strategy", "qualified_research_rule"),
)
def test_report_has_exactly_one_allowed_conclusion(status: str) -> None:
    report = build_v2_report(_stage_result(status=status))
    assert report["conclusion"] == status
    assert report["formal_metrics"] is None or status == "qualified_research_rule"
```

Test deterministic key order, input fingerprint, protocol hash, attempted-rule count, rejected candidates,
fold boundaries, locked-holdout access count and exact reproduction command.

- [ ] **Step 2: Add stage commands**

```text
v2-audit
v2-cycle-study
v2-leader-study
v2-state-study
v2-case-study
v2-validate
```

Each command requires the prior-stage artifact hash. `v2-validate` accepts one frozen pipeline JSON, not a
parameter grid. Output paths are restricted to `memory/06_backtests/`.

- [ ] **Step 3: Generate the current real report**

```bash
docker compose exec -T alphaagent-api python -m alphaagent.server.services.low_suction.cli v2-audit --format markdown
```

Expected current conclusion: `blocked_by_data_quality`, with strict historical membership and security
status still blocking formal metrics. Run `v2-cycle-study` when `cycle_stage=ready` and run the source-only
portion of `v2-case-study`; do not run leader, state, matched-control or validation stages while their
individual readiness fields are blocked.

- [ ] **Step 4: Update durable memory**

Replace stale statements that call a V1 family the preferred rule. Link the V2 protocol, current audit,
and exact next blocker. Keep historical proxy tables only under archived evidence.

- [ ] **Step 5: Verify**

```bash
uv run --group server pytest tests/alphaagent/services/low_suction/test_v2_reporting.py tests/alphaagent/services/low_suction/test_reporting.py -q
git diff --check
```

### Task 13: Run The Full Research Safety Gate

**Files:**
- Modify only when facts changed: `memory/06_backtests/README.md`
- Modify only when decisions changed: `memory/09_decisions/decisions.md`
- Modify: `requirements/README.md`

- [ ] **Step 1: Run all low-suction tests**

```bash
uv run --group server pytest tests/alphaagent/services/low_suction -q
```

Expected: all V1 archival and V2 tests pass.

- [ ] **Step 2: Run static verification**

```bash
uv run ruff check alphaagent/server/services/low_suction tests/alphaagent/services/low_suction
uv run python -m compileall alphaagent/server/services/low_suction
git diff --check
```

Expected: all commands succeed with no diagnostics.

- [ ] **Step 3: Verify forbidden dependencies and product scope**

```bash
rg -n "services\.(quant|backtest|portfolio|simulation)" alphaagent/server/services/low_suction
rg -n "first_divergence|first_bearish_or_break_repair|second_wave_pullback" \
  alphaagent/server/services/low_suction/{research_protocol,concept_cycles,leader_identity,intraday_panel,state_observations,state_transitions,response_surface,candidate_discovery,pipeline_validation}.py
rg -n "low.suction" frontend/src
```

Expected: all three searches return no matches. V1 archival files may still contain old family names but
none of the listed V2 files may import or emit them. No low-suction UI is added.

- [ ] **Step 4: Record the only honest current result**

Until strict historical membership, security status and candidate minute paths pass, record:

```json
{
  "protocol_version": "low-suction-research-v2",
  "conclusion": "blocked_by_data_quality",
  "formal_metrics": null,
  "frozen_pipeline": null
}
```

Do not execute a holdout or produce a strategy winner from proxy inputs.

## Completion Boundary

This plan completes when V2 can reproducibly stop at the correct data gate or evaluate exactly one frozen
pipeline on strict locked holdout data. It does not promise that a qualified strategy exists. UI, alerts,
simulation and trading require a separate user-approved plan after `qualified_research_rule` and forward
validation.
