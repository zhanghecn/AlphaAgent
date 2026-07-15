import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { TimingDirection, TimingOverview } from "@/api/marketTiming";
import { TimingHero } from "./TimingHero";

function overview(currentDirection: TimingDirection): TimingOverview {
  const latestSignal = currentDirection === "NEUTRAL"
    ? null
    : {
        direction: currentDirection,
        status: "CONFIRMED" as const,
        grade: "WEAK" as const,
        setup_type: currentDirection === "GOLD"
          ? "REVERSAL_GOLD" as const
          : "TOP_SILVER" as const,
        date: currentDirection === "GOLD" ? "2026-06-11" : "2026-07-07",
        confirm_date: currentDirection === "GOLD" ? "2026-06-12" : "2026-07-08",
        bull_force: currentDirection === "GOLD" ? 39.5 : 41.2,
        bear_force: currentDirection === "GOLD" ? 61.7 : 68.4,
      };
  return {
    latest_date: "2026-07-15",
    factor_date: "2026-07-15",
    quote_date: "2026-07-15",
    current_direction: currentDirection,
    danger_state: "NORMAL",
    phase: "retreat",
    phase_label: "退潮",
    bull_force: 46.2,
    bear_force: 53.9,
    factors: {
      trend: 54.8,
      momentum: 33.6,
      breadth: 50,
      structure: 43.9,
      volume: 50,
    },
    top_factors: {},
    index_close: 3958.21,
    index_change_pct: -0.22,
    latest_signal: latestSignal,
  };
}

describe("TimingHero", () => {
  it("shows no current signal before the first confirmed event", () => {
    const html = renderToStaticMarkup(
      <TimingHero overview={overview("NEUTRAL")} loading={false} />,
    );

    expect(html).toContain("无信号");
    expect(html).toContain("尚无手指");
    expect(html).not.toContain("最近信号");
    expect(html).not.toContain("2026-06-11");
    expect(html).not.toContain("金手指");
    expect(html).not.toContain("银手指区");
  });

  it("shows the confirmed gold finger as the ongoing user result", () => {
    const gold = renderToStaticMarkup(
      <TimingHero overview={overview("GOLD")} loading={false} />,
    );

    expect(gold).toContain("手指状态");
    expect(gold).toContain("金手指");
    expect(gold).toContain("金手指延续");
    expect(gold).toContain("2026-06-12 起");
    expect(gold).toContain("等待银手指反转");
    expect(gold).not.toContain("当前行情");
    expect(gold).not.toContain("尚无手指");
  });

  it("shows the confirmed silver finger as the ongoing user result", () => {
    const silver = renderToStaticMarkup(
      <TimingHero overview={overview("SILVER")} loading={false} />,
    );

    expect(silver).toContain("银手指");
    expect(silver).toContain("银手指延续");
    expect(silver).toContain("2026-07-08 起");
    expect(silver).toContain("等待金手指反转");
    expect(silver).not.toContain("当前行情");
    expect(silver).not.toContain("尚无手指");
  });
});
