import { describe, expect, it } from "vitest";

import type { LimitUpLiveSignal, LimitUpSignalSnapshot } from "@/api/limitUp";
import { liveSignalsForScope } from "./livePortfolio";

function signal(
  symbol: string,
  boardLevel: number,
  action: LimitUpLiveSignal["action"],
): LimitUpLiveSignal {
  return {
    vt_symbol: symbol,
    name: symbol,
    board_level: boardLevel,
    action,
    entry_kind: "sweep",
    reason: "test",
    cancel_condition: "test",
    execution_confidence: "research_only",
  };
}

function snapshot(overrides: Partial<LimitUpSignalSnapshot["recommendations"]> = {}): LimitUpSignalSnapshot {
  return {
    trade_date: "2026-07-13",
    captured_at: "2026-07-13T10:05:00+08:00",
    source: "test",
    market_context: {},
    recommendations: {
      market_gate: { passed: true, reasons: [] },
      lanes: {
        now: [signal("600001.SSE", 1, "observe"), signal("600002.SSE", 3, "buy_now")],
        tail: [],
        next_auction: [],
      },
      ...overrides,
    },
    data_quality: { status: "ready", is_stale: false },
  };
}

describe("live limit-up portfolio presentation", () => {
  it("uses the backend shared portfolio when present", () => {
    const portfolio = [signal("600010.SSE", 4, "buy_now")];

    expect(liveSignalsForScope(snapshot({ portfolio }), "portfolio")).toEqual(portfolio);
  });

  it("shows the backend watchlist when the strict portfolio is empty", () => {
    const watchlist = [signal("600011.SSE", 1, "observe")];

    expect(liveSignalsForScope(snapshot({ portfolio: [], watchlist }), "portfolio")).toEqual(watchlist);
  });

  it("keeps observations behind executable portfolio signals", () => {
    const portfolio = [signal("600010.SSE", 3, "buy_now")];
    const watchlist = [
      signal("600010.SSE", 3, "observe"),
      signal("600011.SSE", 1, "observe"),
    ];

    expect(
      liveSignalsForScope(snapshot({ portfolio, watchlist }), "portfolio").map(
        (row) => row.vt_symbol,
      ),
    ).toEqual(["600010.SSE", "600011.SSE"]);
  });

  it("falls back to deduplicated executable lanes for old responses", () => {
    const old = snapshot({
      lanes: {
        now: [signal("600001.SSE", 1, "observe"), signal("600001.SSE", 1, "buy_now")],
        tail: [],
        next_auction: [signal("600002.SSE", 3, "next_auction"), signal("600003.SSE", 2, "next_auction")],
      },
    });

    expect(liveSignalsForScope(old, "portfolio").map((row) => row.vt_symbol)).toEqual([
      "600001.SSE",
      "600002.SSE",
    ]);
  });

  it("filters a single board lane without requiring portfolio membership", () => {
    expect(liveSignalsForScope(snapshot(), "two_to_three").map((row) => row.vt_symbol)).toEqual([
      "600002.SSE",
    ]);
  });
});
