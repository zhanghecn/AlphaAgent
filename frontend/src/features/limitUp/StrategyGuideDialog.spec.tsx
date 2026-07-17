import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { LimitUpRadarValidation, LimitUpStrategyGuide } from "@/api/limitUp";
import { StrategyGuideDialog } from "./StrategyGuideDialog";

const guide: LimitUpStrategyGuide = {
  guide_version: "limit-up-strategy-guide-v1",
  strategy: {
    live_version: "limit-up-live-v15",
    history_version: "limit-up-history-v15",
    selection_no_lookahead: true,
    selection_contract: "first_eligible_saved_snapshot",
    entry_windows: ["10:00-11:30", "13:00-14:30"],
    entry_mode: "sweep",
    exit_mode: "next_close",
    max_positions: 2,
  },
  verdict: {
    title: "选股阶段没有使用未来数据",
    detail: "按 captured_at 取第一次通过规则的保存快照。",
    execution_boundary: "没有 Tick/L2，扫板成交是价格代理。",
  },
  selection_steps: [
    { order: 1, title: "限定可交易范围", rule: "仅主板首板和二进三。", timing: "盘中已知" },
    { order: 2, title: "形成正式推荐并排序", rule: "历史胜率优先。", timing: "仅使用此前数据" },
  ],
  ranking: {
    first_board_primary: "历史胜率降序",
    first_board_secondary: "当前涨幅降序",
    historical_win_rate_formula: "封停成功率 × D+1收盘净赚钱率",
    history_cutoff: "result_date < signal_date",
    ranking_only: true,
    portfolio_gate: "两仓组合要求前序样本",
  },
  field_groups: [
    { key: "intraday", label: "盘中实时字段", selection_allowed: true, fields: ["当前价", "概念launch"] },
    { key: "outcome", label: "事后结果字段", selection_allowed: false, fields: ["D+1官方收盘价"] },
  ],
  radar_evidence: {
    status: "collecting",
    capture_min_change_pct: 3,
    formal_min_change_pct: 5,
    complete_trade_days: 0,
    target_trade_days: 60,
    minute_coverage_pct: null,
    minute_sessions: ["09:31-11:30", "13:01-15:00"],
    minute_slot_count: 240,
    entry_fill_delay_seconds: [20, 60],
    entry_fill_same_window: true,
    selected_contract: "formal_5pct",
  },
  dataset: {
    name: "v15保存快照点时反事实重放",
    kind: "saved_point_in_time_counterfactual_replay",
    table: "limit_up_signal_snapshots",
    date_start: "2026-07-15",
    date_end: "2026-07-17",
    snapshot_count: 643,
    daily_snapshot_counts: [
      { trade_date: "2026-07-15", snapshot_count: 253 },
      { trade_date: "2026-07-16", snapshot_count: 253 },
      { trade_date: "2026-07-17", snapshot_count: 137 },
    ],
    closed_through: "2026-07-15",
    closed_signal_count: 11,
    win_count: 7,
    win_rate_pct: 63.6364,
    average_net_return_pct: 2.905,
    portfolio_trade_count: 2,
    portfolio_win_count: 2,
    portfolio_return_pct: 5.7892,
    portfolio_max_drawdown_pct: -0.0309,
    entry: "第一次规则通过的保存快照",
    exit: "D+1官方日线close_price",
    costs: "双边滑点和费用",
    report: "memory/06_backtests/limit_up_sector_quality_v15_20260717.md",
    limitations: ["只有2026-07-15具备D+1官方收盘。"],
  },
  historical_reference: {
    name: "800日历史候选代理",
    kind: "historical_candidate_proxy",
    tables: ["limit_up_history_replays", "stock_daily_bars"],
    date_start: "2023-03-28",
    date_end: "2026-07-16",
    trade_day_count: 800,
    qualified_signal_count: 168,
    closed_recommendation_count: 164,
    account_trade_count: 97,
    recommendation_win_rate_pct: 62.1951,
    account_win_rate_pct: 70.1031,
    live_equivalent: false,
    purpose: "长期检验候选结构和执行口径",
    limitation: "缺少历史盘中全市场帧，不能冒充v15实盘等价收益。",
  },
};

const radarValidation: LimitUpRadarValidation = {
  validation_version: "limit-up-radar-validation-v1",
  status: "collecting",
  coverage: {
    complete_trade_days: 12,
    minute_pair_coverage_pct: 96.5,
  },
  acceptance: {
    selected_contract: "formal_5pct",
    production_contract: "formal_5pct",
    recommended_contract: "formal_5pct",
    eligible_for_activation: false,
    activation_required: false,
    production_contract_mismatch: false,
  },
};

const baseProps = {
  open: true,
  onOpenChange: () => undefined,
  guide,
  radarValidation,
  radarValidationLoading: false,
  radarValidationError: null,
  loading: false,
  error: null,
  onRetry: () => undefined,
};

describe("StrategyGuideDialog", () => {
  it("explains the causal selection order and execution boundary", () => {
    const html = renderToStaticMarkup(<StrategyGuideDialog {...baseProps} />);

    expect(html).toContain("选股阶段没有使用未来数据");
    expect(html).toContain("role=\"dialog\"");
    expect(html).toContain("aria-label=\"关闭\"");
    expect(html).toContain("captured_at");
    expect(html).toContain("result_date &lt; signal_date");
    expect(html).toContain("没有 Tick/L2");
  });

  it("shows the frozen dataset and marks D+1 close as outcome-only", () => {
    const html = renderToStaticMarkup(
      <StrategyGuideDialog {...baseProps} initialTab="dataset" />,
    );

    expect(html).toContain("limit_up_signal_snapshots");
    expect(html).toContain("643 帧");
    expect(html).toContain("11 只 · 7 胜");
    expect(html).toContain("63.6364%");
    expect(html).toContain("+2.9050%");
    expect(html).toContain("事后结果字段");
    expect(html).toContain("禁止");
    expect(html).toContain("D+1官方收盘价");
    expect(html).toContain("绝不参与当日选股");
    expect(html).toContain("800日历史候选代理");
    expect(html).toContain("不是另一套执行算法");
    expect(html).toContain("62.1951%");
    expect(html).toContain("70.1031%");
    expect(html).toContain("3%提前雷达验证");
    expect(html).toContain("3% 开始采集");
    expect(html).toContain("5% 正式推荐");
    expect(html).toContain("09:31-11:30、13:01-15:00，共 240 个去重分钟槽位");
    expect(html).toContain("同一买入窗口内 20-60 秒");
    expect(html).toContain("12 / 60 日");
    expect(html).toContain("96.5000%");
    expect(html).toContain("5%正式合同");
  });

  it("allows the long evidence report path to wrap on mobile", () => {
    const html = renderToStaticMarkup(
      <StrategyGuideDialog {...baseProps} initialTab="dataset" />,
    );

    expect(html).toMatch(
      /<p class="[^"]*break-all[^"]*">memory\/06_backtests\/limit_up_sector_quality_v15_20260717\.md<\/p>/,
    );
  });

  it("does not disguise a validation API failure as zero collected days", () => {
    const html = renderToStaticMarkup(
      <StrategyGuideDialog
        {...baseProps}
        initialTab="dataset"
        radarValidation={undefined}
        radarValidationError="验证接口不可用"
      />,
    );

    expect(html).toContain("读取失败");
    expect(html).not.toContain("0 / 60 日");
  });

  it("keeps the current contract at 5pct until an accepted 3pct contract is published", () => {
    const accepted: LimitUpRadarValidation = {
      ...radarValidation,
      status: "accepted",
      acceptance: {
        selected_contract: "formal_5pct",
        production_contract: "formal_5pct",
        recommended_contract: "early_3pct_same_rules",
        eligible_for_activation: true,
        activation_required: true,
        production_contract_mismatch: true,
      },
    };
    const html = renderToStaticMarkup(
      <StrategyGuideDialog
        {...baseProps}
        initialTab="dataset"
        radarValidation={accepted}
      />,
    );

    expect(html).toContain("5%正式合同");
    expect(html).toContain("建议3%合同");
    expect(html).toContain("已通过，待发布");
  });
});
