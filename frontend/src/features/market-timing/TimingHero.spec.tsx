import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { TimingDirection, TimingOverview } from "@/api/marketTiming";
import { TimingHero } from "./TimingHero";

function overview(currentDirection: TimingDirection): TimingOverview {
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
    latest_signal: {
      direction: "GOLD",
      status: "CONFIRMED",
      grade: "WEAK",
      setup_type: "REVERSAL_GOLD",
      date: "2026-06-11",
      confirm_date: "2026-06-12",
      bull_force: 39.5,
      bear_force: 61.7,
    },
  };
}

describe("TimingHero", () => {
  it("shows no current signal instead of a stale historical gold event", () => {
    const html = renderToStaticMarkup(
      <TimingHero overview={overview("NEUTRAL")} loading={false} />,
    );

    expect(html).toContain("无信号");
    expect(html).toContain("当前无金银信号");
    expect(html).not.toContain("最近信号");
    expect(html).not.toContain("2026-06-11");
    expect(html).not.toContain("金手指");
    expect(html).not.toContain("银手指区");
  });

  it("keeps genuine current gold and silver directions", () => {
    const gold = renderToStaticMarkup(
      <TimingHero overview={overview("GOLD")} loading={false} />,
    );
    const silver = renderToStaticMarkup(
      <TimingHero overview={overview("SILVER")} loading={false} />,
    );

    expect(gold).toContain("金手指");
    expect(silver).toContain("银手指");
    expect(gold).not.toContain("当前无金银信号");
    expect(silver).not.toContain("当前无金银信号");
  });
});
