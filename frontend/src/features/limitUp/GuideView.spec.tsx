import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { LimitUpStrategyGuide } from "@/api/limitUp";
import { GuideView } from "./GuideView";

const guide: LimitUpStrategyGuide = {
  guide_version: "limit-up-strategy-guide-v3",
  strategy: {
    live_version: "limit-up-core-ab-v1",
    history_version: "limit-up-core-ab-v1",
    selection_no_lookahead: true,
    selection_contract: "limit-up-core-ab-v1",
    preboard_research_contract: "limit-up-preboard-decision-v1",
    entry_windows: ["10:00-11:30", "13:00-14:30"],
    entry_mode: "sweep",
    exit_mode: "next_close",
    max_positions: 2,
    live_actionable_limit: null,
  },
  core_quality: {
    contract_version: "limit-up-core-ab-v1",
    prior_limit_window_days: 126,
    minimum_prior_limit_count: 2,
    maximum_prior_limit_count: 6,
    a_tier_industry_turnover_ratio_5d: 1,
    b_tier_is_actionable: true,
    priority_rule: "A优先，B保留；行业量能不作为剔除B的硬门",
    frozen_evidence: {
      status: "historical_pass_forward_not_passed",
      live_equivalent: false,
      date_start: "2025-07-10",
      date_end: "2026-07-23",
      closed_count: 78,
      win_count: 56,
      win_rate_pct: 71.7949,
      average_net_return_pct: 2.2512,
      max_drawdown_pct: -14.5416,
      hard_loss_rate_pct: 8.9744,
      a_tier: { closed_count: 41, win_count: 35, win_rate_pct: 85.3659 },
      b_tier: { closed_count: 37, win_count: 21, win_rate_pct: 56.7568 },
      report: "memory/06_backtests/limit_up_quality_reconstruction_20260726.md",
    },
    recent_snapshot_check: {
      date_start: "2026-07-20",
      date_end: "2026-07-24",
      closed_count: 24,
      win_count: 12,
      win_rate_pct: 50,
      average_net_return_pct: -0.2351,
      no_action_date: "2026-07-24",
      entry: "旧保存快照的首次正式报价代理",
      live_equivalent: false,
      status: "below_60_requires_natural_forward",
    },
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
    first_board_primary: "同股D+1预期净收益降序",
    first_board_secondary: "D+1胜率、3分钟/最终触板概率、封板率依次降序",
    historical_win_rate_formula: "封停成功率 × D+1收盘净赚钱率",
    history_cutoff: "result_date < signal_date",
    ranking_only: true,
    portfolio_gate: "全量正式首板要求前序样本",
  },
  preboard_decision: {
    decision_version: "limit-up-preboard-decision-v1",
    observation_min_change_pct: 3,
    observation_is_buy_signal: false,
    quality_pool_rule: "先通过正式同源首板质量门，再由涨幅达到3%激活观察",
    probability_outputs: ["3分钟触板概率", "当日最终触板概率"],
    ranking_order: [
      "同股D+1预期净收益",
      "同股D+1胜率",
      "3分钟触板概率",
      "最终触板概率",
      "触板后封板率",
      "首板承接分",
    ],
    promotion_rule: "历史严格板前账户通过后仅进入影子；独立前向账户再次通过后才补充正式板前买点",
    formal_baseline: "正式合同仅为limit-up-core-ab-v1；板前概率当前只作研究观察",
  },
  field_groups: [
    { key: "intraday", label: "盘中实时字段", selection_allowed: true, fields: ["当前价", "概念launch"] },
    { key: "outcome", label: "事后结果字段", selection_allowed: false, fields: ["D+1官方收盘价"] },
  ],
  dataset: {
    name: "旧v15保存快照（只读审计）",
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
    entry: "第一次规则通过的保存快照，盘中 sweep 价格代理",
    exit: "D+1官方日线close_price",
    costs: "双边各10bp滑点、万三佣金、最低5元、万0.1过户、卖出万五印花税",
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

const baseProps = {
  guide,
  loading: false,
  error: null,
  onRetry: () => undefined,
};

describe("GuideView", () => {
  it("用一句话说清策略，并承诺不偷看未来", () => {
    const html = renderToStaticMarkup(<GuideView {...baseProps} />);

    expect(html).toContain("这是一个什么策略");
    expect(html).toContain("唯一正式合同是");
    expect(html).toContain("limit-up-core-ab-v1");
    expect(html).toContain("涨停 2 到");
    expect(html).toContain("规则保证不偷看未来数据");
  });

  it("渲染唯一 A+B 合同的七步流程", () => {
    const html = renderToStaticMarkup(<GuideView {...baseProps} />);

    expect(html).toContain("aria-label=\"选股规则流程图\"");
    expect(html).toContain("选股到成交，一共七步");
    expect(html).toContain("锁定唯一正式合同");
    expect(html).toContain("通过原基础质量门");
    expect(html).toContain("检查 126 日市场辨识度");
    expect(html).toContain("输出全部 A+B 买点");
  });

  it("默认节点显示唯一合同和所用数据", () => {
    const html = renderToStaticMarkup(<GuideView {...baseProps} />);

    expect(html).toContain("成立条件");
    expect(html).toContain("关键门槛");
    expect(html).toContain("正式合同");
    expect(html).toContain("旧规则回退");
    expect(html).toContain("用到的数据");
  });

  it("讲解防未来函数三机制和字段分组", () => {
    const html = renderToStaticMarkup(<GuideView {...baseProps} />);

    expect(html).toContain("怎么做到不偷看未来");
    expect(html).toContain("每个点时单独冻结");
    expect(html).toContain("历史只看已收盘");
    expect(html).toContain("先选股，后算账");
    expect(html).toContain("允许参与选股");
    expect(html).toContain("禁止参与选股");
    expect(html).toContain("事后才知道的结果");
    expect(html).toContain("当前仅作诊断的盘中环境");
  });

  it("成交边界用人话讲清排队不确定性，不出现裸 Tick/L2 英文", () => {
    const html = renderToStaticMarkup(<GuideView {...baseProps} />);

    expect(html).toContain("关于成交的诚实说明");
    expect(html).toContain("正式触发时保存的价格代理");
    expect(html).toContain("涨停价排队明细");
    expect(html).not.toContain("没有 Tick/L2");
  });

  it("shows A+B evidence and marks old datasets read-only", () => {
    const html = renderToStaticMarkup(<GuideView {...baseProps} />);

    expect(html).toContain("limit_up_signal_snapshots");
    expect(html).toContain("78 笔");
    expect(html).toContain("56 胜 · 22 负");
    expect(html).toContain("71.7949%");
    expect(html).toContain("+2.2512%");
    expect(html).toContain("12 胜，胜率 50.00%");
    expect(html).toContain("尚未通过 60% 自然前向门");
    expect(html).toContain("旧v15保存快照（只读审计）");
    expect(html).toContain("绝不反过来参与当天的选股");
    expect(html).toContain("800日历史候选代理");
    expect(html).toContain("62.1951%");
    expect(html).not.toContain("70.1031%");
  });

  it("只展示唯一正式 A+B 核心质量门", () => {
    const html = renderToStaticMarkup(<GuideView {...baseProps} />);

    expect(html).toContain("唯一正式核心质量门");
    expect(html).toContain("A · 优先");
    expect(html).toContain("B · 保留");
    expect(html).toContain("35/41 · 85.3659%");
    expect(html).toContain("21/37 · 56.7568%");
    expect(html).toContain("正式 A+B 买入");
    expect(html).not.toContain("板前 C 买入");
  });

  it("allows the long evidence report path to wrap on mobile", () => {
    const html = renderToStaticMarkup(<GuideView {...baseProps} />);

    expect(html).toMatch(
      /<p class="[^"]*break-all[^"]*">A\+B 冻结研究报告：memory\/06_backtests\/limit_up_quality_reconstruction_20260726\.md<\/p>/,
    );
  });

  it("明确板前概率不是正式合同", () => {
    const html = renderToStaticMarkup(<GuideView {...baseProps} />);

    expect(html).toContain("3% 板前观察和触板概率目前只是研究");
    expect(html).toContain("不会生成正式买点");
  });

  it("明确全量列表不限每天一笔", () => {
    const html = renderToStaticMarkup(<GuideView {...baseProps} />);

    expect(html).toContain("实时列表展示全部合格信号");
    expect(html).toContain("同一交易日可以有多笔");
    expect(html).not.toContain("两仓资金组合");
  });
});
