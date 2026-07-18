import { describe, expect, it } from "vitest";

import type { LimitUpLaneLedger, LimitUpLaneLedgerTrade } from "@/api/limitUp";
import { summarizeLedgerDay, weekdayLabel } from "./ledgerTimeline";

function trade(overrides: Partial<LimitUpLaneLedgerTrade> = {}): LimitUpLaneLedgerTrade {
  return {
    lane: "first_board",
    vt_symbol: "002636.SZSE",
    name: "金安国纪",
    buy_date: "2026-07-17",
    buy_time: "10:12:03",
    buy_price: 12.34,
    sell_date: "2026-07-18",
    sell_time: "15:00:00",
    sell_price: 13.01,
    return_pct: 5.43,
    d1_outcome: "d1_premium",
    d_board_status: "sealed",
    execution_confidence: "high",
    ...overrides,
  } as LimitUpLaneLedgerTrade;
}

function ledger(trades: LimitUpLaneLedgerTrade[], observations: LimitUpLaneLedgerTrade[] = []): LimitUpLaneLedger {
  return {
    status: "ready",
    trade_date: "2026-07-17",
    lane: "first_board",
    exit_mode: "next_close",
    selected_count: trades.length,
    trades,
    observations,
  } as unknown as LimitUpLaneLedger;
}

describe("summarizeLedgerDay", () => {
  it("汇总当日笔数、胜率和总收益", () => {
    const summary = summarizeLedgerDay(ledger([
      trade(),
      trade({ vt_symbol: "600000.SSE", name: "浦发银行", return_pct: -1.2 }),
      trade({ vt_symbol: "000001.SZSE", name: "平安银行", return_pct: null, sell_date: null }),
    ]));
    expect(summary.tradeCount).toBe(3);
    expect(summary.closedCount).toBe(2);
    expect(summary.winCount).toBe(1);
    expect(summary.totalReturnPct).toBeCloseTo(4.23);
  });

  it("没有闭合交易时总收益为 null", () => {
    expect(summarizeLedgerDay(ledger([])).totalReturnPct).toBeNull();
  });

  it("仅观察日不计入正式交割", () => {
    const summary = summarizeLedgerDay(ledger([], [trade()]));
    expect(summary.observationOnly).toBe(true);
    expect(summary.tradeCount).toBe(0);
  });
});

describe("weekdayLabel", () => {
  it("输出中文星期", () => {
    expect(weekdayLabel("2026-07-17")).toMatch(/周/);
  });
});
