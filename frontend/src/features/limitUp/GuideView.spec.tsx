import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { LimitUpStrategyGuide } from "@/api/limitUp";
import { GuideView } from "./GuideView";

const guide: LimitUpStrategyGuide = {
  guide_version: "limit-up-strategy-guide-v2",
  strategy: {
    live_version: "limit-up-live-v15",
    history_version: "limit-up-history-v15",
    selection_no_lookahead: true,
    selection_contract: "limit-up-live-v15",
    preboard_research_contract: "limit-up-preboard-decision-v1",
    entry_windows: ["10:00-11:30", "13:00-14:30"],
    entry_mode: "sweep",
    exit_mode: "next_close",
    max_positions: 2,
    live_actionable_limit: null,
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
    portfolio_gate: "两仓组合要求前序样本",
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
    formal_baseline: "当前limit-up-live-v15封板/回封扫板买点保持不变，未来板前层只能补充",
  },
  field_groups: [
    { key: "intraday", label: "盘中实时字段", selection_allowed: true, fields: ["当前价", "概念launch"] },
    { key: "outcome", label: "事后结果字段", selection_allowed: false, fields: ["D+1官方收盘价"] },
  ],
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
    expect(html).toContain("买入即将涨停或刚涨停的强势股");
    expect(html).toContain("规则保证不偷看未来数据");
  });

  it("渲染唯一板前合同的七步流程", () => {
    const html = renderToStaticMarkup(<GuideView {...baseProps} />);

    expect(html).toContain("aria-label=\"选股规则流程图\"");
    expect(html).toContain("选股到成交，一共七步");
    expect(html).toContain("先固定正式策略边界");
    expect(html).toContain("先过高质量首板母池");
    expect(html).toContain("双晋级后补充正式板前买点");
  });

  it("默认节点显示正式基线、不变边界和所用数据", () => {
    const html = renderToStaticMarkup(<GuideView {...baseProps} />);

    expect(html).toContain("成立条件");
    expect(html).toContain("关键门槛");
    expect(html).toContain("正式首板");
    expect(html).toContain("v15 扫板保持");
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
    expect(html).toContain("行动后的第一条严格低于涨停价的新报价");
    expect(html).toContain("涨停价排队明细");
    expect(html).not.toContain("没有 Tick/L2");
  });

  it("shows the frozen dataset metrics and marks D+1 close as outcome-only", () => {
    const html = renderToStaticMarkup(<GuideView {...baseProps} />);

    expect(html).toContain("limit_up_signal_snapshots");
    expect(html).toContain("643 帧");
    expect(html).toContain("11 只 · 7 胜");
    expect(html).toContain("63.6364%");
    expect(html).toContain("+2.9050%");
    expect(html).toContain("绝不反过来参与当天的选股");
    expect(html).toContain("800日历史候选代理");
    expect(html).toContain("62.1951%");
    expect(html).toContain("70.1031%");
  });

  it("只展示高质量母池内的板前概率合同", () => {
    const html = renderToStaticMarkup(<GuideView {...baseProps} />);

    expect(html).toContain("板前概率观察与正式买点边界");
    expect(html).toContain("高质量首板达到 3%");
    expect(html).toContain("3分钟触板概率、当日最终触板概率");
    expect(html).toContain("limit-up-preboard-decision-v1");
    expect(html).toContain("板前 C 买入");
    expect(html).toContain("行动后第一条严格低于涨停价的新报价");
    expect(html).toContain("正式 v15 买入");
    expect(html).toContain("20–60 秒内第一条保存报价");
    expect(html).toContain("历史暂不能按同一可知时点复现");
    expect(html).not.toContain("5%正式合同");
    expect(html).not.toContain("建议3%合同");
    expect(html).not.toContain("相同 known_at");
  });

  it("allows the long evidence report path to wrap on mobile", () => {
    const html = renderToStaticMarkup(<GuideView {...baseProps} />);

    expect(html).toMatch(
      /<p class="[^"]*break-all[^"]*">详细回测报告：memory\/06_backtests\/limit_up_sector_quality_v15_20260717\.md<\/p>/,
    );
  });

  it("明确 3% 只是观察，不是买点", () => {
    const html = renderToStaticMarkup(<GuideView {...baseProps} />);

    expect(html).toContain("3% 不是买点");
    expect(html).toContain("封板/回封扫板买点保持不变");
    expect(html).toContain("未来板前层只能补充");
  });

  it("区分不限数量的实时买点列表和两仓资金组合", () => {
    const html = renderToStaticMarkup(<GuideView {...baseProps} />);

    expect(html).toContain("实时全量买点列表不限制数量");
    expect(html).toContain("两仓资金组合");
    expect(html).not.toContain("才整体替换正式首板");
  });
});
