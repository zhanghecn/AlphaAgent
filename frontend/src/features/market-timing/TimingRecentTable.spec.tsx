import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { TimingDailyState } from "@/api/marketTiming";
import { TimingRecentTable } from "./TimingRecentTable";

describe("TimingRecentTable", () => {
  it("separates persistent regime from the daily candidate zone", () => {
    const rows: TimingDailyState[] = [
      {
        date: "2026-06-11",
        bull_force: 60,
        bear_force: 40,
        active_direction: "NEUTRAL",
        zone_direction: "GOLD",
        danger_state: "NORMAL",
        phase: "warming",
        event: null,
      },
      {
        date: "2026-06-12",
        bull_force: 55,
        bear_force: 45,
        active_direction: "GOLD",
        zone_direction: "NEUTRAL",
        danger_state: "NORMAL",
        phase: "warming",
        event: null,
      },
      {
        date: "2026-07-01",
        bull_force: 40,
        bear_force: 70,
        active_direction: "SILVER",
        zone_direction: "SILVER",
        danger_state: "DANGER",
        phase: "retreat",
        event: null,
      },
    ];

    const html = renderToStaticMarkup(
      <TimingRecentTable series={rows} loading={false} />,
    );

    expect(html).toContain("行情状态");
    expect(html).toContain("候选区域");
    expect(html).toContain("金行情");
    expect(html).toContain("银行情");
  });
});
