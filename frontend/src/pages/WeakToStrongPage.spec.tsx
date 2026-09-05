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
  rules_version: "w2s-v4.0",
  counts: {
    pool: 2,
    actionable: 1,
    signals: 1,
    by_group: { yin2: 1, yang4: 1 },
    by_status: { watching: 1, holding: 1 },
  },
  mkt_lim_tm1: 121,
  group_labels: {
    yin2: "2板阴·坑蹲",
    yang2a: "2板阳·坑底首阳",
    yang2b: "2板阳·坑中纠缠",
    yin4: "4+阴·孤板多头",
    yang4: "4+阳·2板穿插",
  },
  last_scan: null,
  entries: [
    {
      vt_symbol: "000592.SZSE",
      name: "平潭发展",
      group_key: "yin2",
      actionable: true,
      prev_close: 3.75,
      trigger_price: 4.125,
      limit_price: 4.13,
      chg_tm1: -5.1,
      ushadow_tm1: 1.2,
      yang_tm1: false,
      base: "u_dip",
      base_label: "U型蹲",
      pos3: "坑内",
      low_dd: -12.3,
      pull: -8.1,
      reb: 5.2,
      ma_st: null,
      n_lim_mid: null,
      topped: false,
      d23ok: null,
      seg_h: null,
      gap_days: 8,
      status: "holding",
      gap_open_pct: 0.8,
      touched_at: "2026-08-21T09:42:00+08:00",
      entry_price: 4.125,
      entry_time: "2026-08-21T09:42:00+08:00",
      last_price: 4.54,
      change_pct: 10.0,
      sealed: true,
      streak_h: 2,
      exit_date: null,
      exit_price: null,
      exit_reason: null,
      ret_pct: null,
    },
    {
      vt_symbol: "600683.SSE",
      name: "京投发展",
      group_key: "yang4",
      actionable: false,
      prev_close: 5.0,
      trigger_price: 5.5,
      limit_price: 5.5,
      chg_tm1: -6.2,
      ushadow_tm1: 1.1,
      yang_tm1: false,
      base: null,
      base_label: null,
      pos3: "无坑",
      low_dd: -2.1,
      pull: -1.3,
      reb: null,
      ma_st: "+++",
      n_lim_mid: 0,
      topped: null,
      d23ok: null,
      seg_h: 2,
      gap_days: 4,
      status: "watching",
      gap_open_pct: 1.2,
      touched_at: null,
      entry_price: null,
      entry_time: null,
      last_price: 5.06,
      change_pct: 1.2,
      sealed: null,
      streak_h: null,
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
  it("renders group badges, actionable marks and status labels", () => {
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
    expect(html).toContain("N型补涨打板 · 实时推荐");
    expect(html).toContain("2板阴");
    expect(html).toContain("2板阴·坑蹲");
    expect(html).toContain("4+阳");
    expect(html).toContain("✅出手");
    expect(html).toContain("无坑");
    expect(html).toContain("持有中");
    expect(html).toContain("平潭发展");
    expect(html).not.toContain("大盘停手日");
    expect(html).not.toContain("停手日·不做");
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
                group: "yin2",
                group_label: "2板阴·坑蹲",
                entry_price: 4.125,
                gap_open_pct: 0.8,
                sealed: true,
                streak_h: 5,
                exit_date: "2026-08-27",
                exit_price: 5.54,
                exit_reason: "break_close",
                ret_pct: 13.1,
                touch: "10:15",
              },
            ],
          },
        ]}
        />
      ),
    );
    expect(html).toContain("断板日收盘卖");
    expect(html).toContain("5 板");
    expect(html).toContain("2板阴");
  });
});

describe("ShortTermResearchPage", () => {
  it("registers N型补涨打板 as a research tab", () => {
    const html = renderToStaticMarkup(
      withProviders(<ShortTermResearchPage />, ["/short-term?research=weak-to-strong"]),
    );
    expect(html).toContain("N型补涨打板");
    expect(html).toContain("潜龙首板");
    expect(html).toContain("低吸");
  });
});
