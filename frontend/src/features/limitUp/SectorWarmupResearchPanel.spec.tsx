import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { LimitUpSectorWarmupReport } from "@/api/limitUp";
import { SectorWarmupResearchPanel } from "./SectorWarmupResearchPanel";

function report(): LimitUpSectorWarmupReport {
  const comparison = (
    variant: string,
    label: string,
    tradeCount: number,
    winRate: number,
    average: number,
    total: number,
    drawdown: number,
    finalEquity: number,
  ) => ({
    variant,
    label,
    formal: false,
    trade_count: tradeCount,
    trade_day_count: tradeCount,
    win_rate: winRate,
    average_net_return_pct: average,
    total_return_pct: total,
    max_drawdown_pct: drawdown,
    hard_loss_rate: 2.0,
    seal_rate: 80.0,
    initial_cash: 100_000,
    final_equity: finalEquity,
    start: "2025-06-27",
    end: "2026-06-15",
    delta: variant === "baseline" ? null : {
      trade_count: tradeCount - 99,
      win_rate: winRate - 54.55,
      average_net_return_pct: average - 0.149,
      total_return_pct: total - 9.46,
      max_drawdown_pct: drawdown + 23.59,
    },
  });
  return {
    status: "ready",
    research_version: "sector-warmup-research-v1",
    research_status: "proxy_only",
    simulation_eligible: false,
    scope: "first_board",
    primary_exit: "next_open",
    initial_cash: 100_000,
    round_trip_cost_pct: 0.31,
    forward_start_date: "2026-07-13",
    event_start: "2025-06-27",
    event_end: "2026-06-15",
    candidate_funnel: {
      raw_first_board: 12_455,
      eligible: 196,
      closed: 196,
      warmup_confirmed: 38,
    },
    comparisons: [
      comparison("baseline", "当前首板 Top1", 99, 54.55, 0.149, 9.46, -23.59, 109_456.39),
      comparison("warmup_rank", "预热优先排序", 99, 54.55, 0.199, 14.71, -23.59, 114_708.09),
      comparison("warmup_gate", "预热准入门", 30, 66.67, 0.874, 27.06, -10.72, 127_061.53),
      comparison("warmup_leader_proxy", "预热 + 昨日龙头代理", 10, 50, -0.966, -10, -20, 90_000),
    ],
    phase_summaries: {
      locked_holdout: [
        comparison("baseline", "当前首板 Top1", 50, 54, 0.0273, -1.3563, -19.536, 98_643.69),
        comparison("warmup_gate", "预热准入门", 10, 60, -0.1169, -1.6829, -7.7835, 98_317.06),
      ],
    },
    acceptance: {
      passed: false,
      evaluated_variant: "warmup_gate",
      checks: [{ code: "formal_data", passed: false, label: "点时概念数据不少于500日" }],
    },
    data_coverage: {
      concept_daily_bar_days: 253,
      membership_snapshot_days: 0,
      intraday_fund_snapshot_days: 1,
    },
    formal_concept_backtest_ready: false,
    lane_isolation: {
      passed: true,
      affected_lanes: ["first_board"],
      unchanged_lanes: ["one_to_two", "two_to_three", "high_board"],
    },
    limitations: ["当前结果为行业日级代理。"],
  };
}

describe("SectorWarmupResearchPanel", () => {
  it("renders the compact comparison and point-in-time data warning", () => {
    const html = renderToStaticMarkup(
      <SectorWarmupResearchPanel report={report()} loading={false} />,
    );

    expect(html).toContain("板块预热研究");
    expect(html).toContain("代理研究，未接入实时动作");
    expect(html).toContain("当前首板 Top1");
    expect(html).toContain("预热优先排序");
    expect(html).toContain("预热准入门");
    expect(html).toContain("昨日龙头代理");
    expect(html).toContain("66.67%");
    expect(html).toContain("+0.87%");
    expect(html).toContain("+27.06%");
    expect(html).toContain("-10.72%");
    expect(html).toContain("¥127,061.53");
    expect(html).toContain("概念日线 253 日");
    expect(html).toContain("历史成员 0 日");
    expect(html).toContain("盘中资金 1 日");
    expect(html).toContain("锁定留出");
    expect(html).toContain("预热准入 10 笔");
    expect(html).toContain("平均 -0.12%");
    expect(html).toContain("期末 ¥98,317.06");
  });

  it("keeps a research error inside the warmup panel", () => {
    const html = renderToStaticMarkup(
      <SectorWarmupResearchPanel loading={false} error="请求失败" />,
    );

    expect(html).toContain("板块预热研究暂不可用：请求失败");
  });
});
