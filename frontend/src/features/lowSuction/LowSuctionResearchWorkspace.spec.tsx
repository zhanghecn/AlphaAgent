import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import type {
  LowSuctionCrossRegimeValidation,
  LowSuctionHistoricalOverview,
  LowSuctionStrategyOverview,
} from "@/api/lowSuction";
import { BacktestView, LowSuctionResearchWorkspace } from "./LowSuctionResearchWorkspace";

const phase = (id: string, trades: number) => ({
  id,
  closed_trades: trades,
  win_rate_pct: 70,
  mean_net_return_pct: 2,
  profit_factor: null,
  wilson_95_lower_pct: 61,
});

const validation = {
  three_phase_candidate: {
    policy_version: "causal-leader-pullback-three-phase-adaptive-v1",
    full_history: { closed_trades: 89, win_rate_pct: 76.4045, mean_net_return_pct: 3.0767, profit_factor: 4.3761 },
    cash: { closed_trades: 87, cash_win_rate_pct: 75.8621, compound_return_pct: 94.536, maximum_drawdown_pct: -4.0879 },
    development_market_phases: [phase("uptrend", 5), phase("rotation", 22), phase("warming", 23)],
    validation_market_phases: [phase("uptrend", 3), phase("rotation", 15), phase("warming", 21)],
    robustness: {
      full_history: { wilson_95_lower_pct: 66.6064, without_largest_winner_mean_pct: 2.99, leave_one_campaign_out_min_win_rate_pct: 75.8621 },
      development: { all: { wilson_95_lower_pct: 60.4468 } },
      validation: { all: { wilson_95_lower_pct: 64.466 } },
      time_block_summary: { blocks: 5, point_win_rate_above_60_blocks: 5, positive_mean_return_blocks: 5, wilson_95_lower_above_60_blocks: 2 },
      conclusion: "natural confidence remains required",
    },
    execution_contract: {},
  },
} as unknown as LowSuctionCrossRegimeValidation;

const history = {
  latest_run: {
    run_id: "run-1",
    trade_count: 89,
    built_at: "2026-07-21T14:15:34+08:00",
    metrics: {
      all_trade_quality: { trades: 89, positive_rate_pct: 76.4045, mean_net_return_pct: 3.0767, profit_factor: 4.3761 },
      two_slot_compound_backtest: { signals: 89, accepted_entries: 81, closed_trades: 81, winning_trades: 61, cash_win_rate_pct: 75.3086, compound_return_pct: 230.073, maximum_drawdown_pct: -7.889, skip_reasons: { capacity_full: 8 } },
    },
  },
  latest_strict_run: null,
  formal_strategy: false,
  exploratory_counts_toward_qualification: false,
  strict_history_available: false,
} as unknown as LowSuctionHistoricalOverview;

const strategy = {
  session: {
    trade_date: "2026-07-21",
    status: "preview_ready",
    alert_stage: "intraday_preview",
    last_scan_at: "2026-07-21T14:30:00+08:00",
    next_scan_at: "2026-07-21T14:50:00+08:00",
  },
  today_candidates: [],
  recommendations: [],
  generated_at: "2026-07-21T14:30:00+08:00",
} as unknown as LowSuctionStrategyOverview;

describe("LowSuctionResearchWorkspace", () => {
  it("uses the same primary information architecture as limit-up research", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <LowSuctionResearchWorkspace validation={validation} history={history} strategy={strategy} />
      </MemoryRouter>,
    );

    expect(html).toContain("实时推荐");
    expect(html).toContain("回测分析");
    expect(html).toContain("规则说明");
    expect(html).toContain("盘中预警");
    expect(html).toContain("下次跟踪");
    expect(html).toContain("14:50 尾盘最终确认");
    expect(html).not.toContain("前向验证");
    expect(html).not.toContain("账户权益");
    expect(html).not.toContain("持仓");
    expect(html).not.toContain("14:50 信号");
  });

  it("surfaces blocked runs instead of a silent empty state", () => {
    const blocked = {
      ...strategy,
      session: {
        ...strategy.session,
        status: "blocked",
        phases: {
          signal_preview: {
            status: "blocked",
            complete: false,
            attempted_at: "2026-07-21T13:30:00+08:00",
            candidate_count: 0,
            recommendation_count: 0,
            positions_opened: 0,
            positions_closed: 0,
            blocking_reasons: ["future_or_outcome_columns_prohibited"],
          },
        },
      },
    } as unknown as LowSuctionStrategyOverview;
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <LowSuctionResearchWorkspace validation={validation} history={history} strategy={blocked} />
      </MemoryRouter>,
    );

    expect(html).toContain("信号计算受阻");
    expect(html).toContain("输入校验未通过（防未来函数守护）");
    expect(html).not.toContain("今日暂无买入推荐");
  });

  it("never leaks a raw english session status", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <LowSuctionResearchWorkspace validation={validation} history={history} strategy={strategy} />
      </MemoryRouter>,
    );

    expect(html).not.toContain("awaiting_signal_window");
    expect(html).not.toContain("preview_ready");
  });

  it("separates two-slot compounding from all recommendation quality", () => {
    const queryClient = new QueryClient();
    const html = renderToStaticMarkup(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <BacktestView validation={validation} history={history} />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(html).toContain("两仓真实账户");
    expect(html).toContain("账户复利");
    expect(html).toContain("230.07%");
    expect(html).toContain("闭合成交");
    expect(html).toContain("81 笔");
    expect(html).toContain("全部推荐质量");
    expect(html).toContain("全部交易");
    expect(html).toContain("89 笔");
    expect(html).toContain("不受两仓已满影响");
  });

  it("orders the backtest report into numbered chapters", () => {
    const queryClient = new QueryClient();
    const html = renderToStaticMarkup(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <BacktestView validation={validation} history={history} />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    for (const chapter of ["01", "02", "03", "04", "05", "06"]) {
      expect(html).toContain(`>${chapter}<`);
    }
    expect(html).toContain("参数与口径");
    expect(html).toContain("分行情结果");
    expect(html).toContain("稳健性检查");
    expect(html).toContain("逐笔交割");
  });
});
