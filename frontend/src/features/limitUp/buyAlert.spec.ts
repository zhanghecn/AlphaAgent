import { describe, expect, it } from "vitest";

import type { LimitUpLiveSignal, LimitUpSignalSnapshot } from "@/api/limitUp";
import {
  EMPTY_BUY_ALERT_STATE,
  buyAlertContent,
  evaluateBuyAlerts,
  type BuyAlertState,
} from "./buyAlert";

const NOW = Date.parse("2026-07-15T10:05:00+08:00");

function signal(overrides: Partial<LimitUpLiveSignal> = {}): LimitUpLiveSignal {
  return {
    vt_symbol: "600001.SSE",
    name: "测试股份",
    board_level: 1,
    board_lane: "first_board",
    action: "buy_now",
    entry_kind: "sweep",
    reason: "买点触发",
    cancel_condition: "开板取消",
    execution_confidence: "proxy_without_l2",
    execution_state: "actionable",
    signal_state: "trigger_ready",
    last_price: 10.87,
    change_pct: 8.73,
    distance_to_limit_pct: 1.18,
    strategy_name: "弱市题材进攻",
    ...overrides,
  };
}

function snapshot(
  rows: LimitUpLiveSignal[] = [signal()],
  overrides: Partial<LimitUpSignalSnapshot> = {},
): LimitUpSignalSnapshot {
  return {
    mode: "live_snapshot",
    trade_date: "2026-07-15",
    captured_at: "2026-07-15T10:05:00+08:00",
    source: "test",
    market_context: {},
    recommendations: {
      market_gate: { passed: true, reasons: [] },
      lanes: { now: rows, tail: [], next_auction: [] },
      portfolio: rows,
      watchlist: [],
    },
    data_quality: { status: "ready", is_stale: false },
    ...overrides,
  };
}

describe("limit-up buy alerts", () => {
  it("alerts once when a symbol first enters the live buy state", () => {
    const first = evaluateBuyAlerts(snapshot(), EMPTY_BUY_ALERT_STATE, NOW, true);
    const repeated = evaluateBuyAlerts(snapshot(), first.state, NOW + 10_000, true);

    expect(first.alerts.map((row) => row.vt_symbol)).toEqual(["600001.SSE"]);
    expect(repeated.alerts).toEqual([]);
    expect(first.state.activeSymbols).toEqual(["600001.SSE"]);
    expect(first.state.lastAlertAt["600001.SSE"]).toBe(NOW);
  });

  it("does not alert for stale snapshots or next-session plans", () => {
    const stale = snapshot(undefined, {
      data_quality: { status: "stale", is_stale: true },
    });
    const plan = snapshot(undefined, { mode: "next_session_final" });
    const historical = snapshot(undefined, { mode: "historical_proxy" });

    expect(evaluateBuyAlerts(stale, EMPTY_BUY_ALERT_STATE, NOW, true).alerts).toEqual([]);
    expect(evaluateBuyAlerts(plan, EMPTY_BUY_ALERT_STATE, NOW, true).alerts).toEqual([]);
    expect(evaluateBuyAlerts(historical, EMPTY_BUY_ALERT_STATE, NOW, true).alerts).toEqual([]);
  });

  it("tracks state while disabled without emitting an alert", () => {
    const result = evaluateBuyAlerts(snapshot(), EMPTY_BUY_ALERT_STATE, NOW, false);

    expect(result.alerts).toEqual([]);
    expect(result.state.activeSymbols).toEqual(["600001.SSE"]);
    expect(result.state.lastAlertAt).toEqual({});
  });

  it("alerts after a symbol leaves and reenters beyond the cooldown", () => {
    const active = evaluateBuyAlerts(snapshot(), EMPTY_BUY_ALERT_STATE, NOW, true);
    const inactive = evaluateBuyAlerts(snapshot([]), active.state, NOW + 20_000, true);
    const reentered = evaluateBuyAlerts(snapshot(), inactive.state, NOW + 61_000, true);

    expect(inactive.state.activeSymbols).toEqual([]);
    expect(reentered.alerts.map((row) => row.vt_symbol)).toEqual(["600001.SSE"]);
  });

  it("resets prior symbols when the trade date advances", () => {
    const previous: BuyAlertState = {
      tradeDate: "2026-07-14",
      activeSymbols: ["600001.SSE"],
      lastAlertAt: { "600001.SSE": NOW - 10_000 },
    };
    const result = evaluateBuyAlerts(snapshot(), previous, NOW, true);

    expect(result.alerts).toHaveLength(1);
    expect(result.state.tradeDate).toBe("2026-07-15");
  });

  it("builds a concise notification from point-in-time fields", () => {
    expect(buyAlertContent(signal())).toEqual({
      title: "买点触发 · 测试股份",
      body: "600001.SSE · 现涨 +8.73% · 距板 1.18% · 弱市题材进攻",
    });
  });
});
