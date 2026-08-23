import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { ShortTermResearchPage } from "./ShortTermResearchPage";
import { W2S_LIVE_REFRESH_INTERVAL_MS } from "./WeakToStrongPage";
import type { W2sLivePayload } from "@/api/weakToStrong";
import { W2sLedgerView } from "@/features/weakToStrong/W2sLedgerView";
import { W2sLiveView } from "@/features/weakToStrong/W2sLiveView";

function withProviders(node: React.ReactElement, routerEntries: string[] = ["/"]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={routerEntries}>{node}</MemoryRouter>
    </QueryClientProvider>
  );
}

const LIVE_PAYLOAD: W2sLivePayload = {
  status: "ok",
  trade_date: "2026-08-24",
  stale: false,
  session_stage: "morning",
  rules_version: "w2s-v2.2",
  counts: {
    pool: 2,
    signals: 2,
    by_group: { a1: 1, b: 1 },
    by_status: { watching: 1, holding: 1 },
  },
  market_halt: {
    halted: true,
    mkt_lim_tm1: 121,
    threshold: 110,
    note: "昨日主板非ST涨停家数超阈值 → 今日整池停手",
  },
  group_labels: { a1: "A1 恐慌出清", a2: "A2 强势整理", b: "B 高位弱转强" },
  last_scan: null,
  entries: [
    {
      vt_symbol: "000592.SZSE",
      name: "平潭发展",
      group_key: "a1",
      prev_close: 3.75,
      trigger_price: 4.0125,
      limit_price: 4.13,
      chg_tm1: -5.1,
      lshadow_tm1: 0.76,
      fade_tm1: 2.5,
      vol_rel5_tm1: 0.96,
      amp_tm1: 6.3,
      turnover_tm1: 15.6,
      base20_tm1: 9.0,
      last_streak: 2,
      gap_days: 2,
      halted: true,
      status: "halted",
      gap_open_pct: 0.8,
      touched_at: null,
      entry_price: null,
      entry_time: null,
      last_price: 3.78,
      change_pct: 0.8,
      sealed: null,
      streak_h: null,
      exit_date: null,
      exit_price: null,
      exit_reason: null,
      ret_pct: null,
    },
    {
      vt_symbol: "600683.SSE",
      name: "京投发展",
      group_key: "b",
      prev_close: 5.0,
      trigger_price: 5.35,
      limit_price: 5.5,
      chg_tm1: -6.2,
      lshadow_tm1: 1.1,
      fade_tm1: 3.0,
      vol_rel5_tm1: 0.9,
      amp_tm1: 8.1,
      turnover_tm1: 12.0,
      base20_tm1: 10.0,
      last_streak: 4,
      gap_days: 4,
      halted: true,
      status: "holding",
      gap_open_pct: 1.2,
      touched_at: "2026-08-24T10:01:00+08:00",
      entry_price: 5.35,
      entry_time: "2026-08-24T10:01:00+08:00",
      last_price: 5.5,
      change_pct: 10.0,
      sealed: true,
      streak_h: 2,
      exit_date: null,
      exit_price: null,
      exit_reason: null,
      ret_pct: null,
    },
  ],
};

describe("WeakToStrongPage live refresh cadence", () => {
  it("polls the persisted pool snapshot every 30s during the session", () => {
    expect(W2S_LIVE_REFRESH_INTERVAL_MS).toBe(30 * 1000);
  });
});

describe("W2sLiveView", () => {
  it("renders group badges, halt banner and status labels", () => {
    const html = renderToStaticMarkup(
      withProviders(
        <W2sLiveView
          payload={LIVE_PAYLOAD}
          availableDates={["2026-08-24"]}
          selectedDate={null}
          onDateChange={() => undefined}
        />,
      ),
    );
    expect(html).toContain("A1 恐慌出清");
    expect(html).toContain("B 高位弱转强");
    expect(html).toContain("大盘停手日");
    expect(html).toContain("停手日·不做");
    expect(html).toContain("持有中");
    expect(html).toContain("平潭发展");
  });
});

describe("W2sLedgerView", () => {
  it("renders close-based exit reason labels", () => {
    const html = renderToStaticMarkup(
      withProviders(
        <W2sLedgerView
          caliber="测试口径"
          months={[{ month: "2026-08", count: 1, win_rate: 100, avg_ret_pct: 13.1, total_ret_pct: 13.1 }]}
          month="2026-08"
          onMonthChange={() => undefined}
          ledgerDays={[
          {
            trade_date: "2026-08-20",
            count: 1,
            win: 1,
            avg_ret_pct: 13.1,
            trades: [
              {
                vt_symbol: "000592.SZSE",
                name: "平潭发展",
                group: "a1",
                group_label: "A1 恐慌出清",
                entry_price: 4.0125,
                gap_open_pct: 0.8,
                sealed: true,
                streak_h: 5,
                exit_date: "2026-08-27",
                exit_price: 5.54,
                exit_reason: "break_close",
                ret_pct: 13.1,
              },
            ],
          },
        ]}
        />
      ),
    );
    expect(html).toContain("断板日收盘卖");
    expect(html).toContain("5 板");
    expect(html).toContain("A1");
  });
});

describe("ShortTermResearchPage", () => {
  it("registers 趋势弱转强 as the third research tab", () => {
    const html = renderToStaticMarkup(
      withProviders(<ShortTermResearchPage />, ["/short-term?research=weak-to-strong"]),
    );
    expect(html).toContain("趋势弱转强");
    expect(html).toContain("潜龙首板");
    expect(html).toContain("低吸");
  });
});
