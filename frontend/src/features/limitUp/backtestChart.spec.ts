import { describe, expect, it } from "vitest";

import type { LimitUpLaneBacktest } from "@/api/limitUp";
import type { Bar } from "@/api/types";
import { alignIndexReturns, buildBacktestChartPoints } from "./backtestChart";

function bar(trade_date: string, close: number): Bar {
  return { trade_date, open: close, close, high: close, low: close, volume: 1, turnover: null, change_pct: null };
}

describe("alignIndexReturns", () => {
  it("从区间首个有行情的日期归一为 0", () => {
    const returns = alignIndexReturns(
      [bar("2026-07-14", 100), bar("2026-07-15", 102), bar("2026-07-16", 101)],
      ["2026-07-14", "2026-07-15", "2026-07-16"],
    );
    expect(returns.get("2026-07-14")).toBeCloseTo(0);
    expect(returns.get("2026-07-15")).toBeCloseTo(2);
    expect(returns.get("2026-07-16")).toBeCloseTo(1);
  });

  it("非交易日沿用此前最近收盘价", () => {
    const returns = alignIndexReturns(
      [bar("2026-07-17", 100), bar("2026-07-20", 105)],
      ["2026-07-17", "2026-07-18", "2026-07-20"],
    );
    expect(returns.get("2026-07-18")).toBeCloseTo(0);
    expect(returns.get("2026-07-20")).toBeCloseTo(5);
  });

  it("行情缺失时返回空表", () => {
    expect(alignIndexReturns([], ["2026-07-17"]).size).toBe(0);
  });
});

describe("buildBacktestChartPoints", () => {
  it("合并账户、推荐质量和指数三条曲线", () => {
    const report = {
      daily_results: [
        { result_date: "2026-07-15", total_return_pct: 1.5, drawdown_pct: -0.2 },
        { result_date: "2026-07-16", total_return_pct: 2.0, drawdown_pct: -0.1 },
      ],
      recommendation_quality: {
        daily_results: [
          { result_date: "2026-07-15", total_return_pct: 3.0, trade_count: 2, daily_return_pct: 3, equity: 0, drawdown_pct: 0 },
        ],
      },
    } as unknown as LimitUpLaneBacktest;
    const points = buildBacktestChartPoints(report, [bar("2026-07-15", 100), bar("2026-07-16", 104)]);
    expect(points).toHaveLength(2);
    expect(points[0]).toMatchObject({
      result_date: "2026-07-15",
      account_return_pct: 1.5,
      recommendation_return_pct: 3.0,
      index_return_pct: 0,
    });
    expect(points[1].recommendation_return_pct).toBeNull();
    expect(points[1].index_return_pct).toBeCloseTo(4);
  });
});
