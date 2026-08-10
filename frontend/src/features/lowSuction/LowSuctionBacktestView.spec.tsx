import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { LowSuctionBacktestView } from "./LowSuctionBacktestView";
import { LowSuctionLedgerView } from "./LowSuctionLedgerView";

describe("LowSuctionBacktestView", () => {
  it("restores an in-flight legacy rebuild even before a report exists", () => {
    const html = renderToStaticMarkup(
      <LowSuctionBacktestView
        report={null}
        rebuild={{
          status: "building",
          started_at: "2026-08-10T08:23:49.503398+00:00",
        }}
        building
        canRebuild={false}
        onRebuild={() => undefined}
        rebuildError={null}
      />,
    );

    expect(html).toContain("全量重算中");
    expect(html).toContain("开始于");
    expect(html).toContain("旧版本启动的回测不会补录轨道");
    expect(html).toContain("disabled=\"\"");
  });

  it("explains a duplicate manual request without claiming another task started", () => {
    const html = renderToStaticMarkup(
      <LowSuctionBacktestView
        report={null}
        rebuild={{
          status: "building",
          run_id: 41,
          stage: "scan_candidates",
          started_at: "2026-08-10T08:23:49.503398+00:00",
        }}
        building
        canRebuild={false}
        onRebuild={() => undefined}
        rebuildError="低吸回测正在重算"
      />,
    );

    expect(html).toContain("扫描全市场候选");
    expect(html).toContain("本次点击未新建任务：低吸回测正在重算");
  });

  it("lists persisted run evidence with the latest scan metrics", () => {
    const html = renderToStaticMarkup(
      <LowSuctionBacktestView
        report={null}
        rebuild={{
          status: "idle",
          recent_runs: [
            {
              id: 41,
              source: "manual",
              status: "ready",
              stage: "completed",
              strategy_version: "low-suction-daily-backtest-v3",
              score_version: "low-suction-daily-score-v2.8",
              requested_at: "2026-08-10T08:23:49.503398+00:00",
              started_at: "2026-08-10T08:23:49.503398+00:00",
              stage_started_at: "2026-08-10T08:41:00.000000+00:00",
              finished_at: "2026-08-10T09:12:00.000000+00:00",
              message: "回测报告已写入",
              error: null,
              metrics: { candidate_count: 50_704, labeled: 48_921 },
            },
          ],
        }}
        building={false}
        canRebuild
        onRebuild={() => undefined}
        rebuildError={null}
      />,
    );

    expect(html).toContain("最近回测记录");
    expect(html).toContain("已完成");
    expect(html).toContain("候选 50,704");
    expect(html).toContain("回测报告已写入");
  });

  it("points an empty ledger to the server-side rebuild", () => {
    const html = renderToStaticMarkup(
      <LowSuctionLedgerView ledgerDays={[]} />,
    );

    expect(html).toContain("服务器端回测重算完成后展示");
    expect(html).not.toContain("CLI");
  });
});
