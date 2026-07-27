import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { LimitUpStrategyGuide } from "@/api/limitUp";
import { GuideView } from "./GuideView";

const guide: LimitUpStrategyGuide = {
  guide_version: "limit-up-strategy-guide-v4",
  strategy: {
    live_version: "limit-up-core-abc-v1",
    history_version: "limit-up-core-abc-v1",
    selection_no_lookahead: true,
    selection_contract: "limit-up-core-abc-v1",
    preboard_research_contract: "limit-up-preboard-decision-v1",
    entry_windows: ["10:00-11:30", "13:00-14:30"],
    entry_mode: "sweep",
    exit_mode: "next_close",
    max_positions: 2,
    live_actionable_limit: null,
  },
  core_quality: {
    contract_version: "limit-up-core-abc-v1",
    prior_limit_window_days: 126,
    minimum_prior_limit_count: 2,
    maximum_prior_limit_count: 6,
    a_tier_industry_turnover_ratio_5d: 1,
    b_tier_is_actionable: true,
    b_first_board_minimum_time: "10:30",
    c_tier_is_actionable: true,
    c_daily_limit: 1,
    c_evidence_status: "historical_proxy_pass_forward_unconfirmed",
    priority_rule: "同一时点A优先于C、C优先于B；跨时点按真实到达顺序",
    frozen_evidence: {
      status: "historical_proxy_pass_forward_unconfirmed",
      live_equivalent: false,
      date_start: "2025-07-10",
      date_end: "2026-07-23",
      closed_count: 143,
      win_count: 99,
      win_rate_pct: 69.2308,
      average_net_return_pct: 2.1203,
      max_drawdown_pct: -21.0357,
      hard_loss_rate_pct: 6.993,
      a_tier: { closed_count: 41, win_count: 35, win_rate_pct: 85.3659 },
      c_tier: { closed_count: 72, win_count: 46, win_rate_pct: 63.8889 },
      b_tier: { closed_count: 30, win_count: 18, win_rate_pct: 60 },
      single_position: { closed_count: 80, win_count: 57, win_rate_pct: 71.25, total_return_pct: 457.7327, max_drawdown_pct: -19.4234 },
      two_positions: { closed_count: 96, win_count: 72, win_rate_pct: 75, total_return_pct: 226.6771, max_drawdown_pct: -8.8039 },
      report: "memory/06_backtests/limit_up_abc_formal_replay_20260727.md",
    },
    forward_status: {
      start_date: "2026-07-27",
      closed_count: 0,
      win_count: 0,
      win_rate_pct: null,
      minimum_closed_count: 15,
      minimum_trade_days: 10,
      status: "collecting_forward",
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
    formal_baseline: "正式合同仅为limit-up-core-abc-v1；板前概率当前只作研究观察",
  },
  field_groups: [
    { key: "intraday", label: "盘中实时字段", selection_allowed: true, fields: ["当前价", "概念launch"] },
    { key: "outcome", label: "事后结果字段", selection_allowed: false, fields: ["D+1官方收盘价"] },
  ],
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
    expect(html).toContain("limit-up-core-abc-v1");
    expect(html).toContain("涨停 2 到");
    expect(html).toContain("规则保证不偷看未来数据");
  });

  it("渲染唯一 A+B+C 合同的七步流程", () => {
    const html = renderToStaticMarkup(<GuideView {...baseProps} />);

    expect(html).toContain("aria-label=\"选股规则流程图\"");
    expect(html).toContain("选股到成交，一共七步");
    expect(html).toContain("锁定唯一正式合同");
    expect(html).toContain("通过原基础质量门");
    expect(html).toContain("建立 A/B 辨识度基座");
    expect(html).toContain("输出全部 A+B+C 买点");
  });

  it("默认节点显示唯一合同和所用数据", () => {
    const html = renderToStaticMarkup(<GuideView {...baseProps} />);

    expect(html).toContain("成立条件");
    expect(html).toContain("关键门槛");
    expect(html).toContain("正式合同");
    expect(html).toContain("缺失字段");
    expect(html).toContain("失败关闭");
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

  it("展示 A+B+C 冻结证据和自然前向状态", () => {
    const html = renderToStaticMarkup(<GuideView {...baseProps} />);

    expect(html).toContain("143 笔");
    expect(html).toContain("99 胜 · 44 负");
    expect(html).toContain("69.2308%");
    expect(html).toContain("+2.1203%");
    expect(html).toContain("自然前向验证");
    expect(html).toContain("2026-07-27");
    expect(html).toContain("当前闭合 0 笔");
    expect(html).toContain("待产生样本");
    expect(html).toContain("10 个新交易日和 15 笔闭合交易");
    expect(html).toContain("绝不反过来参与当天的选股");
    expect(html).not.toContain("limit_up_signal_snapshots");
    expect(html).not.toContain("只读审计");
  });

  it("只展示唯一正式 A+B+C 核心质量门", () => {
    const html = renderToStaticMarkup(<GuideView {...baseProps} />);

    expect(html).toContain("唯一正式 A+B+C 质量合同");
    expect(html).toContain("A · 优先");
    expect(html).toContain("B · 保留");
    expect(html).toContain("C · 补位");
    expect(html).toContain("35/41 · 85.3659%");
    expect(html).toContain("46/72 · 63.8889%");
    expect(html).toContain("18/30 · 60.0000%");
    expect(html).toContain("正式 A+B+C 买入");
  });

  it("allows the long evidence report path to wrap on mobile", () => {
    const html = renderToStaticMarkup(<GuideView {...baseProps} />);

    expect(html).toMatch(
      /<p class="[^"]*break-all[^"]*">A\+B\+C 正式回放报告：memory\/06_backtests\/limit_up_abc_formal_replay_20260727\.md<\/p>/,
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
    expect(html).toContain("两仓尚无 A 时只使用一个非 A 仓");
  });
});
