import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router-dom";

import type { LimitUpDrawdownDiagnostics } from "@/api/limitUp";
import { BacktestDrawdownPanel } from "./BacktestDrawdownPanel";

const diagnostics = {
  diagnostics_version: "limit-up-drawdown-diagnostics-v1",
  status: "ready",
  scope_explanation: "账户回撤按两仓真实到达顺序计算；全量推荐曲线不受持仓上限约束。",
  longest_losing_streak: {
    count: 4,
    start_date: "2025-12-03",
    end_date: "2025-12-18",
    first_entry_date: "2025-12-02",
    compound_return_pct: -4.5318,
    trades: [],
  },
  maximum_drawdown_episode: {
    peak_date: "2025-10-17",
    trough_date: "2025-11-26",
    recovery_date: "2025-12-22",
    drawdown_pct: -8.3083,
    duration_trade_days: 28,
    recovery_trade_days: 18,
    principal_losses: [
      {
        vt_symbol: "001267.SZSE",
        name: "汇绿生态",
        lane: "two_to_three",
        entry_date: "2025-10-22",
        exit_date: "2025-10-23",
        return_pct: -9.5464,
        net_pnl: -5635.07,
        d_board_status: "failed",
      },
    ],
  },
  execution_filter: {
    all: {
      executed: { count: 99, win_count: 69, win_rate: 69.697, average_return_pct: 2.1796 },
      skipped: { count: 71, win_count: 35, win_rate: 49.2958, average_return_pct: -0.1909 },
    },
    time_validation: {
      start: "2026-04-14",
      end: "2026-07-15",
      executed: { count: 43, win_count: 29, win_rate: 67.4419, average_return_pct: 2.094 },
      skipped: { count: 68, win_count: 32, win_rate: 47.0588, average_return_pct: -0.2994 },
    },
    latest_entry_month: {
      month: "2026-07",
      executed: { count: 9, win_count: 7, win_rate: 77.7778, average_return_pct: 3.4344 },
      skipped: { count: 28, win_count: 5, win_rate: 17.8571, average_return_pct: -3.8932 },
    },
  },
  board_outcome_attribution: {
    actionability: "outcome_only_not_entry_filter",
    note: "最终封板或炸板只能用于收盘后归因，买入时尚不可知。",
    groups: [
      { status: "sealed", count: 79, win_count: 57, win_rate: 72.1519, average_return_pct: 2.766, hard_loss_count: 3 },
      { status: "failed", count: 20, win_count: 12, win_rate: 60, average_return_pct: -0.1367, hard_loss_count: 6 },
    ],
    hard_loss_count: 9,
    hard_loss_failed_count: 6,
    hard_loss_failed_share_pct: 66.6667,
  },
  stock_gene_calibration: {
    field: "stock_gene_combined_win_rate",
    selection_action: "do_not_add_static_threshold",
    design_sample: [],
    time_validation: [
      { bucket: "30%-40%", count: 43, win_rate: 62.7907, average_return_pct: 1.2053 },
      { bucket: "40%-50%", count: 41, win_rate: 51.2195, average_return_pct: 0.0306 },
      { bucket: ">=50%", count: 22, win_rate: 40.9091, average_return_pct: -0.2445 },
    ],
    validation_monotonic: false,
  },
  causes: [
    {
      code: "late_arrival_regime_decay",
      finding: "验证段后排未成交推荐显著弱于两仓实际成交。",
      implication: "两仓和真实到达顺序正在隔离退潮期后排票。",
    },
  ],
  exit_research: {
    research_version: "first-board-causal-exit-research-v1",
    status: "blocked_by_execution_price_coverage",
    formal_strategy_changed: false,
    formal_policy: {
      policy_version: "limit-up-core-abc-v1",
      mode: "D+1 close",
      decision_time: "D0 signal time",
      execution_time: "D+1 15:00",
    },
    withdrawn_policy: {
      policy_version: "first-board-auction-take-profit-shadow-v1",
      status: "invalidated_same_price_decision_fill_lookahead",
      invalidated_on: "2026-07-18",
      published_metrics_withdrawn: true,
      published_metrics: null,
      reason_codes: [
        { code: "final_open_used_as_decision_signal", detail: "09:25 最终开盘价被用于决定是否卖出。" },
        { code: "same_open_used_as_fill_price", detail: "决策后又按已经形成的同一个官方开盘价成交。" },
        { code: "retrospective_threshold_selection", detail: "2% 阈值来自已查看的历史开盘与收盘结果，不能作为前向证据。" },
      ],
    },
    d0_open_benchmark: {
      policy_version: "first-board-d0-open-benchmark-v1",
      status: "rejected_below_frozen_baseline",
      rule: "D0 收盘后无条件决定：首板全部在 D+1 开盘卖出；二进三仍在 D+1 收盘卖出。",
      decision_time: "D0 after close",
      price_source: "official_daily_open_proxy",
      baseline_summary: { trade_count: 99, win_rate: 69.697, total_return_pct: 171.7614, max_drawdown_pct: -8.3083 },
      summary: { trade_count: 116, win_rate: 59.4828, total_return_pct: 70.4296, max_drawdown_pct: -8.7967 },
      return_delta_pct_points: -101.3318,
      win_rate_delta_pct_points: -10.2142,
    },
    precommitted_limit_research: {
      policy_version: "first-board-d0-contingent-limit-readiness-v1",
      status: "blocked_by_auction_fill_evidence",
      rule: "D0 预先提交固定止盈限价单；仅当 D+1 集合竞价真实撮合该订单时退出，否则撤单并继续持有至收盘。",
      decision_time: "D0 after close",
      selected_threshold_pct: null,
      coverage: {
        required_pair_count: 84,
        snapshot_covered_pair_count: 4,
        strict_complete_pair_count: 0,
        unmatched_volume_pair_count: 0,
        strict_coverage_pct: 0,
        minimum_strict_coverage_pct: 95,
        coverage_passed: false,
      },
      account_performance: null,
      account_performance_reason: "缺少竞价未匹配量、委托优先级和严格撮合证据，不能假定预挂单成交。",
    },
    post_auction_research: {
      policy_version: "first-board-0925-signal-0931-fill-v1",
      status: "blocked_by_execution_price_coverage",
      signal_time: "D+1 09:25 after opening auction",
      execution_time: "D+1 09:30 continuous auction",
      execution_price_proxy: "09:31 one-minute bar open",
      metric_scope: "covered_baseline_trades_signal_diagnostic",
      selected_threshold_pct: null,
      coverage: {
        required_pair_count: 84,
        covered_pair_count: 41,
        missing_pair_count: 43,
        coverage_pct: 48.8095,
        minimum_coverage_pct: 95,
        coverage_passed: false,
      },
      baseline_covered_sample: { count: 41, win_count: 29, win_rate: 70.7317, average_return_pct: 2.2367 },
      all_post_auction_exit_sample: { count: 41, win_count: 26, win_rate: 63.4146, average_return_pct: 1.3044 },
      threshold_rows: [
        { threshold_pct: 0, trigger_count: 26, sample_count: 41, win_rate: 80.4878, average_return_pct: 1.816, average_return_delta_vs_close_pct_points: -0.4207 },
        { threshold_pct: 2, trigger_count: 16, sample_count: 41, win_rate: 75.6098, average_return_pct: 1.9822, average_return_delta_vs_close_pct_points: -0.2545 },
        { threshold_pct: 5, trigger_count: 4, sample_count: 41, win_rate: 73.1707, average_return_pct: 2.4768, average_return_delta_vs_close_pct_points: 0.2401 },
      ],
      account_performance: null,
      account_performance_reason: "09:31 成交代理覆盖不足，不能重放完整资金账户。",
    },
  },
} as unknown as LimitUpDrawdownDiagnostics;

describe("BacktestDrawdownPanel", () => {
  it("separates account drawdown from the unconstrained recommendation curve", () => {
    const html = renderPanel();

    expect(html).toContain("账户回撤与全量推荐不是同一条曲线");
    expect(html).toContain("-8.3083%");
    expect(html).toContain("2025-10-17 → 2025-11-26");
    expect(html).toContain("2025-12-22 修复");
    expect(html).toContain("连续亏损 4 笔");
  });

  it("shows why position limits protected the validation and latest cohorts", () => {
    const html = renderPanel();

    expect(html).toContain("时间验证段");
    expect(html).toContain("成交 43 笔");
    expect(html).toContain("67.4419%");
    expect(html).toContain("跳过 68 笔");
    expect(html).toContain("2026-07");
    expect(html).toContain("-3.8932%");
  });

  it("labels failed-board evidence as hindsight rather than an entry rule", () => {
    const html = renderPanel();

    expect(html).toContain("收盘后归因，不能作为当天买入条件");
    expect(html).toContain("炸板");
    expect(html).toContain("6 / 9");
    expect(html).toContain("汇绿生态");
    expect(html).toContain("-9.5464%");
  });

  it("withdraws the invalid shadow and blocks incomplete causal replay", () => {
    const html = renderPanel();

    expect(html).toContain("旧竞价影子已撤回");
    expect(html).toContain("同价决策成交泄漏");
    expect(html).toContain("171.7614%");
    expect(html).toContain("70.4296%");
    expect(html).toContain("D0 预挂条件限价单");
    expect(html).toContain("竞价快照覆盖");
    expect(html).toContain("覆盖 41 / 84 笔");
    expect(html).toContain("账户复利不发布");
    expect(html).not.toContain("181.8349%");
    expect(html).not.toContain("73.7864%");
  });
});

function renderPanel() {
  return renderToStaticMarkup(
    <MemoryRouter>
      <BacktestDrawdownPanel diagnostics={diagnostics} />
    </MemoryRouter>,
  );
}
