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
    const portfolio = [signal("600010.SSE", 1, "buy_now")];

    expect(liveSignalsForScope(snapshot({ portfolio }), "portfolio")).toEqual(portfolio);
  });

  it("keeps only the first two active product signals", () => {
    const portfolio = [
      signal("600010.SSE", 1, "buy_now"),
      signal("600011.SSE", 1, "buy_now"),
      signal("600012.SSE", 1, "buy_now"),
      signal("600013.SSE", 3, "buy_now"),
    ];

    expect(
      liveSignalsForScope(snapshot({ portfolio }), "portfolio").map((row) => row.vt_symbol),
    ).toEqual(["600010.SSE", "600011.SSE"]);
  });

  it("keeps two-to-three and first-board in the single product portfolio", () => {
    const portfolio = [
      signal("600010.SSE", 3, "buy_now"),
      signal("600011.SSE", 1, "buy_now"),
      signal("600012.SSE", 4, "buy_now"),
      signal("600013.SSE", 2, "buy_now"),
    ];

    expect(
      liveSignalsForScope(snapshot({ portfolio }), "portfolio").map((row) => row.vt_symbol),
    ).toEqual(["600010.SSE", "600011.SSE"]);
  });

  it("shows the backend watchlist when the strict portfolio is empty", () => {
    const watchlist = [signal("600011.SSE", 1, "observe")];

    expect(liveSignalsForScope(snapshot({ portfolio: [], watchlist }), "portfolio")).toEqual(watchlist);
  });

  it("shows only watchlist rows that can still transition to buy", () => {
    const watchlist = [
      { ...signal("600011.SSE", 1, "observe"), signal_state: "rejected" },
      { ...signal("600012.SSE", 1, "observe"), signal_state: "missed" },
      { ...signal("600013.SSE", 1, "observe"), signal_state: "invalidated" },
      {
        ...signal("600014.SSE", 1, "observe"),
        signal_state: "approaching_trigger",
        blocking_scope: "structural",
      },
      {
        ...signal("600015.SSE", 1, "observe"),
        signal_state: "approaching_trigger",
        blocking_scope: "dynamic",
      },
    ];

    expect(
      liveSignalsForScope(snapshot({ portfolio: [], watchlist }), "portfolio").map(
        (row) => row.vt_symbol,
      ),
    ).toEqual(["600015.SSE"]);
  });

  it("keeps observations behind executable portfolio signals", () => {
    const portfolio = [signal("600010.SSE", 1, "buy_now")];
    const watchlist = [
      signal("600010.SSE", 1, "observe"),
      signal("600011.SSE", 1, "observe"),
    ];

    expect(
      liveSignalsForScope(snapshot({ portfolio, watchlist }), "portfolio").map(
        (row) => row.vt_symbol,
      ),
    ).toEqual(["600010.SSE", "600011.SSE"]);
  });

  it("keeps two portfolio rows plus six observations without duplicates", () => {
    const portfolio = [
      { ...signal("600010.SSE", 1, "buy_now"), portfolio_selected: true },
      { ...signal("600011.SSE", 1, "observe"), portfolio_selected: true },
    ];
    const watchlist = Array.from({ length: 8 }, (_, index) => ({
      ...signal(`6000${index + 10}.SSE`, 1, "observe"),
      signal_state: index % 2 ? "concept_warming" : "approaching_trigger",
      concept_strength_rank: index + 1,
    }));

    const rows = liveSignalsForScope(snapshot({ portfolio, watchlist }), "portfolio");

    expect(rows).toHaveLength(8);
    expect(new Set(rows.map((row) => row.vt_symbol)).size).toBe(8);
    expect(rows.slice(0, 2).every((row) => row.portfolio_selected)).toBe(true);
  });

  it("falls back to deduplicated executable lanes for old responses", () => {
    const old = snapshot({
      lanes: {
        now: [
          signal("600001.SSE", 1, "observe"),
          signal("600001.SSE", 1, "buy_now"),
          { ...signal("600004.SSE", 1, "observe"), signal_state: "rejected" },
          { ...signal("600005.SSE", 1, "observe"), signal_state: "missed" },
        ],
        tail: [],
        next_auction: [signal("600002.SSE", 3, "next_auction"), signal("600003.SSE", 2, "next_auction")],
      },
    });

    expect(liveSignalsForScope(old, "portfolio").map((row) => row.vt_symbol)).toEqual([
      "600001.SSE",
    ]);
  });

  it("filters a single board lane without requiring portfolio membership", () => {
    expect(liveSignalsForScope(snapshot(), "two_to_three").map((row) => row.vt_symbol)).toEqual([
      "600002.SSE",
    ]);
  });
});
