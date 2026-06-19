# Youzi Method Quant Mapping Addendum

Date: 2026-06-19

## Purpose

This note maps a small set of public short-term / youzi-style trading ideas to
AlphaAgent's measurable factors and latest experiment evidence. It is not a
claim that any seat label is authentic and it is not a trading rule.

External materials are used only as market-experience references. The strategy
must still be validated by full-range backtests, market-regime splits and
anti-future-function checks before any rule can become default.

## External References Reviewed

- TaoGuBa repost of "养家心法" emphasizes market emotion, risk/reward, main
  hotspots, crowd attention, and dynamic decisions. Source:
  https://www.tgb.cn/follow/1P01ngeOMBa_1PatOBA1xpQ_1
- TaoGuBa mobile repost summarizes mainline / secondary / non-mainline handling:
  mainline can be traded repeatedly, non-mainline should be short-lived and
  fast. Source: https://m.tgb.cn/a/2mLq5dhLU53
- Tianyun Fupan repost stresses hotspot quality, money-making effect, mainline
  confirmation, and not selling a real mainline opportunity too early. Source:
  https://www.ttyfp.com/chaogu/23209.html

These are public reposts and summaries, not primary exchange data. They are
useful for hypothesis generation only.

## Core Mapping

| Youzi-style idea | Quant proxy in AlphaAgent | Current evidence |
| --- | --- | --- |
| Mainline first, individual stock second | dynamic market regime, sector/mainline score, stock relative strength, top-candidate audit excluding strong markets | Market context is still audit-only. Historical sector scores and sector fund-flow are incomplete. |
| Buy divergence, sell consensus | controlled pullback, MA5/MA10/MA20 support, reclaim/weak-to-strong; sell-side distribution and high-MFE giveback audit | Entry side is partly implemented. Sell side must remain path-aware; broad giveback and early-exit rules failed. |
| Strong market: choose strong / trend leader | return_20d/60d, large-bull/near-limit-up count, liquidity capacity, trend trailing | Baseline winners come from a few trend extensions; experiments that miss them collapse return. |
| Weak market: low absorption after panic | weak/crash market bucket, selloff exhaustion, low base, MA support, lower-risk position sizing | Not yet a trading rule. Needs market/sector context and better data coverage. |
| Mainline can be traded repeatedly; non-mainline is fast | setup + market-regime + theme alignment, holding/trailing logic | Product currently cannot fully prove theme alignment because historical sector data is incomplete. |
| Avoid pure K-line superstition | require factor stack and global validation, not one-stock visual rules | Supported by failed experiments `#195-#201`; single intuitive rules repeatedly hurt global return. |

## Comparison With Current Strategy Evidence

The latest experiments support one strong conclusion: youzi ideas should become
context labels and validation gates before they become buy/sell rules.

- `#195` mid-profit giveback stop helped a focused example but cut trend winners
  and returned only `+56.10%`.
- `#196` low-suction launch confirmation hard gate returned only `+65.69%`.
- `#198` repeated dragon hard reject returned only `+33.90%`.
- `#199/#200` launch quality score/penalty both destroyed portfolio return.
- `#201` three-day failed-launch early exit returned only `+60.67%`, missed large
  trend winners and did not reduce `support_stop` loss.

This matches the external-method lesson: a mainline/leader system must preserve
large payoff tails. It cannot optimize only average loser shape.

## Next Quant Hypotheses

### 1. Mainline / Market Gate Should Stay Audit-first

Hypothesis:

- In `narrow_theme_bull` or `strong_broad`, do not tighten exits aggressively
  if a held stock has positive early/path MFE and still belongs to the active
  theme.
- In `weak_defensive` or crash-like buckets, only low-suction/panic absorption
  should be allowed, and only after reclaim.

Current blocker:

- Historical sector/mainline coverage is not strong enough. `stock_fund_flows_partial`
  is only a local leaderboard fallback.

Next measurable work:

- Add a read-only `market_mainline_trade_context` summary for closed trades:
  market bucket, stock relative strength bucket, sector score availability,
  and whether the trade was a trend winner, support stop, or rebound stop.

### 2. Rebound-prone Support Stop Should Be Review Marker First

Hypothesis:

- A support stop with prior MFE, early follow-through and a wide panic sell bar
  may be a shakeout rather than final breakdown.

Evidence:

- `2026-06-19_rebound_prone_support_stop_audit.md` found `48 / 125` support stops
  followed by a 10-day rebound, but simple visible classifiers are too weak for
  a trading rule.

Next measurable work:

- Add a read-only `rebound_prone_support_stop_review` marker and compare it by
  market/sector bucket before any default-off experiment.

### 3. Replacement Quality Is Mandatory For Any Early Exit

Hypothesis:

- Early exit can only help if the freed slot buys a better candidate; otherwise
  it sacrifices trend winners or churns into weaker names.

Evidence:

- `#201` removed `41` baseline trades with about `+266,883` PnL and added `46`
  experiment trades with only about `+46,342` PnL.

Next measurable work:

- Any future sell experiment should log replacement trade quality:
  removed trade PnL/MFE, added trade PnL/MFE, setup, market bucket and rank.

### 4. Low-suction Should Remain A Setup, Not A Quota

Hypothesis:

- Low-suction confidence can build over multiple days, but only the launch/reclaim
  row should be executable. Forcing slots or hard gates hurts.

Evidence:

- Current `0.1.21/#194` keeps low-suction inside one public strategy and still
  returns `+82.99%`.
- Hard low-suction gate `#196` underperformed.

Next measurable work:

- Improve explanation and market-context review, not quota.

## Practical Product Rule

The UI can stay simple:

- one public strategy;
- candidate score and reason;
- backtest split by year, market regime, top candidates and path diagnostics;
- optional read-only warnings such as "当前大盘/主线转弱", "疑似支撑止损后反弹风险",
  or "替换质量不足".

The internal system can stay complex, but every complexity layer should be an
audit marker until a full persisted experiment beats `#194`.

## Decision

Do not add a new default buy/sell rule from external youzi methods yet. The next
engineering step should be read-side context markers:

1. `rebound_prone_support_stop_review`
2. `market_mainline_trade_context`
3. replacement-quality attribution for sell experiments

Only after these markers show stable separation across year/market buckets should
we run another default-off trading experiment.
