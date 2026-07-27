import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import type { LimitUpLaneBacktest } from "@/api/limitUp";
import {
  BacktestView,
  LIMIT_UP_BACKTEST_SCOPE,
  limitUpBacktestSummaries,
} from "./LimitUpPage";

describe("LimitUpPage backtest contract", () => {
  it("always requests the formal portfolio scope", () => {
    expect(LIMIT_UP_BACKTEST_SCOPE).toBe("portfolio");
  });

  it("keeps recommendation quality separate from the two-slot account", () => {
    const cashSummary = { trade_count: 2, total_return_pct: 8.0 };
    const qualitySummary = { trade_count: 5, total_return_pct: 12.0 };
    const report = {
      summary: cashSummary,
      signal_summary: { trade_count: 99 },
      recommendation_quality: { summary: qualitySummary },
    } as unknown as LimitUpLaneBacktest;

    expect(limitUpBacktestSummaries(report)).toEqual({
      cashSummary,
      qualitySummary,
    });
  });

  it("shows an explicit status while the first backtest report is loading", () => {
    const html = renderToStaticMarkup(
      <BacktestView
        indexBars={[]}
        loading
        start="2023-03-28"
        end="2026-07-24"
        onStart={() => undefined}
        onEnd={() => undefined}
        rebuildRunning={false}
        rebuildError={null}
        onRebuild={() => undefined}
      />,
    );

    expect(html).toContain("A+B+C 回测载入中");
    expect(html).toContain("正在读取 A+B+C 全量回测");
    expect(html).toContain("完成后本页会自动更新");
    expect(html).toContain('role="status"');
  });
});
