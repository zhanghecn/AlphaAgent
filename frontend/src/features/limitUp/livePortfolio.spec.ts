import { describe, expect, it } from "vitest";

import type { LimitUpLiveSignal, LimitUpSignalSnapshot } from "@/api/limitUp";
import { liveSignalsForScope, preboardSignals } from "./livePortfolio";

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

  it("does not cap a strict backend recommendation list", () => {
    const portfolio = [
      signal("600010.SSE", 1, "buy_now"),
      signal("600011.SSE", 1, "buy_now"),
      signal("600012.SSE", 1, "buy_now"),
      signal("600013.SSE", 3, "buy_now"),
    ];

    expect(
      liveSignalsForScope(snapshot({ portfolio }), "portfolio").map((row) => row.vt_symbol),
    ).toEqual([
      "600010.SSE",
      "600011.SSE",
      "600012.SSE",
      "600013.SSE",
    ]);
  });

  it("keeps first-board and two-to-three in the formal product portfolio", () => {
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

  it("keeps the actionable list empty when only the watchlist has rows", () => {
    const watchlist = [signal("600011.SSE", 1, "observe")];

    expect(liveSignalsForScope(snapshot({ portfolio: [], watchlist }), "portfolio")).toEqual([]);
  });

  it("keeps prepared preboard rows separate from formal recommendations", () => {
    const prepared = {
      ...signal("600011.SSE", 1, "observe"),
      state: "near_limit" as const,
      public_quality_preparation_passed: true,
      public_quality_touch_ready: true,
      public_quality_actionable: false,
      validation_passed: true,
      blocking_scope: "none",
    };
    const touched = {
      ...prepared,
      vt_symbol: "600012.SSE",
      state: "sealed" as const,
      public_quality_actionable: true,
    };
    const current = snapshot({
      portfolio: [],
      preboard_candidates: [prepared, touched],
    });

    expect(preboardSignals(current).map((row) => row.vt_symbol)).toEqual([
      "600011.SSE",
    ]);
    expect(liveSignalsForScope(current, "portfolio")).toEqual([]);
  });

  it("excludes a downgraded observation even when the backend puts it in portfolio", () => {
    const portfolio = [
      { ...signal("600011.SSE", 1, "observe"), portfolio_selected: true },
    ];

    expect(liveSignalsForScope(snapshot({ portfolio }), "portfolio")).toEqual([]);
  });

  it("never lets watchlist rows append to the actionable portfolio", () => {
    const portfolio = [signal("600010.SSE", 1, "buy_now")];
    const watchlist = [
      signal("600010.SSE", 1, "observe"),
      signal("600011.SSE", 1, "observe"),
    ];

    expect(
      liveSignalsForScope(snapshot({ portfolio, watchlist }), "portfolio").map(
        (row) => row.vt_symbol,
      ),
    ).toEqual(["600010.SSE"]);
  });

  it("prefers unbounded actionable recommendations over the constrained portfolio", () => {
    const portfolio = [
      signal("600010.SSE", 1, "buy_now"),
      signal("600011.SSE", 1, "buy_now"),
    ];
    const actionable_recommendations = [
      ...portfolio,
      signal("600012.SSE", 1, "buy_now"),
    ];

    expect(
      liveSignalsForScope(
        snapshot({ portfolio, actionable_recommendations }),
        "portfolio",
      ).map((row) => row.vt_symbol),
    ).toEqual(["600010.SSE", "600011.SSE", "600012.SSE"]);
  });

  it("keeps backend portfolio order when a watchlist row has a higher joint rate", () => {
    const portfolio = [
      { ...profitabilitySignal("600001.SSE", 45, 9.8, 1), action: "buy_now" as const },
    ];
    const watchlist = [profitabilitySignal("600002.SSE", 55, 8.8, 5)];

    expect(
      liveSignalsForScope(snapshot({ portfolio, watchlist }), "portfolio").map(
        (row) => row.vt_symbol,
      ),
    ).toEqual(["600001.SSE"]);
  });

  it("returns every strict backend recommendation without watchlist padding", () => {
    const actionable_recommendations = [
      { ...signal("600010.SSE", 1, "buy_now"), portfolio_selected: true },
      { ...signal("600011.SSE", 1, "buy_now"), portfolio_selected: true },
      { ...signal("600012.SSE", 1, "buy_now"), portfolio_selected: false },
    ];
    const watchlist = Array.from({ length: 8 }, (_, index) => ({
      ...signal(`6000${index + 10}.SSE`, 1, "observe"),
      signal_state: index % 2 ? "concept_warming" : "approaching_trigger",
      concept_strength_rank: index + 1,
    }));

    const rows = liveSignalsForScope(
      snapshot({ actionable_recommendations, watchlist }),
      "portfolio",
    );

    expect(rows.map((row) => row.vt_symbol)).toEqual([
      "600010.SSE",
      "600011.SSE",
      "600012.SSE",
    ]);
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

  it("keeps a sealed first-board buy for limit-price queueing", () => {
    const momentum = {
      ...signal("600009.SSE", 1, "buy_now"),
      entry_kind: "momentum",
      signal_state: "trigger_ready",
      missed_preseal_entry: true,
      state: "sealed",
      quality_gate_passed: true,
    };

    expect(
      liveSignalsForScope(
        snapshot({ actionable_recommendations: [momentum] }),
        "portfolio",
      ).map((row) => row.vt_symbol),
    ).toEqual(["600009.SSE"]);
  });

  it("keeps a first-board buy when quote state lags at the limit price", () => {
    const momentum = {
      ...signal("600009.SSE", 1, "buy_now"),
      board_lane: "first_board" as const,
      state: "near_limit",
      last_price: 11,
      limit_price: 11,
      quality_gate_passed: true,
    };

    expect(
      liveSignalsForScope(
        snapshot({ actionable_recommendations: [momentum] }),
        "portfolio",
      ).map((row) => row.vt_symbol),
    ).toEqual(["600009.SSE"]);
  });

  it("does not display a failed first-board as an actionable buy", () => {
    const failed = {
      ...signal("600009.SSE", 1, "buy_now"),
      board_lane: "first_board" as const,
      state: "failed",
    };

    expect(
      liveSignalsForScope(
        snapshot({ actionable_recommendations: [failed] }),
        "portfolio",
      ),
    ).toEqual([]);
  });
});

function profitabilitySignal(
  symbol: string,
  historicalWinRate: number,
  changePct: number,
  conceptStrengthRank: number,
): LimitUpLiveSignal {
  return {
    ...signal(symbol, 1, "observe"),
    board_lane: "first_board",
    signal_state: "approaching_trigger",
    change_pct: changePct,
    concept_strength_rank: conceptStrengthRank,
    historical_evidence: {
      smoothed_win_rate: 50,
      historical_win_rate: historicalWinRate,
    },
  };
}
