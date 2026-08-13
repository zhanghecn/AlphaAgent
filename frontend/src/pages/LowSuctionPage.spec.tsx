import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { LOW_SUCTION_LIVE_REFRESH_INTERVAL_MS } from "./LowSuctionPage";
import { LowSuctionLiveView } from "@/features/lowSuction/LowSuctionLiveView";

describe("LowSuctionPage live refresh cadence", () => {
  it("polls the lightweight persisted snapshot once per minute", () => {
    expect(LOW_SUCTION_LIVE_REFRESH_INTERVAL_MS).toBe(60 * 1000);
  });

  it("keeps dated snapshots reachable when today's real-time scan is unavailable", () => {
    const html = renderToStaticMarkup(
      <LowSuctionLiveView
        payload={{
          status: "unavailable",
          trade_date: "2026-08-12",
          message: "现货快照 OHLCV 覆盖不足，暂不能生成今日低吸推荐",
        }}
        availableDates={["2026-08-12", "2026-08-11", "2026-08-08"]}
        selectedDate={null}
        onDateChange={() => undefined}
        onTrendPageChange={() => undefined}
        onOversoldPageChange={() => undefined}
      />,
    );

    expect(html).toContain("选择推荐交易日");
    expect(html).toContain("2026-08-11");
    expect(html).toContain("今日低吸推荐");
  });
});
