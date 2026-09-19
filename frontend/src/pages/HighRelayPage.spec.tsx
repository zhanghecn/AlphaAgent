import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { ShortTermResearchPage } from "./ShortTermResearchPage";
import { HPR_LIVE_REFRESH_INTERVAL_MS } from "./HighRelayPage";
import type { HprLivePayload } from "@/api/highRelay";
import { HprLedgerView } from "@/features/highRelay/HprLedgerView";
import { HprLiveView } from "@/features/highRelay/HprLiveView";

function withProviders(node: React.ReactElement, routerEntries: string[] = ["/"]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={routerEntries}>{node}</MemoryRouter>
    </QueryClientProvider>
  );
}

const LIVE_PAYLOAD: HprLivePayload = {
  status: "ok",
  trade_date: "2026-09-04",
  stale: false,
  session_stage: "first_window",
  rules_version: "hpr-v1.3",
  counts: {
    pool: 2,
    actionable: 1,
    signals: 1,
    by_group: { 二接三阴: 1, 三接四阳: 1 },
    by_point: { B1: 1 },
    by_status: { watching: 1, holding: 1 },
  },
  mkt_lim_tm1: 38,
  group4_labels: {
    二接三阴: "二接三·阴地基",
    二接三阳: "二接三·阳地基",
    三接四阴: "三接四·阴地基",
    三接四阳: "三接四·阳地基",
  },
  point_labels: {
    A1: "A1 修复启动",
    A2: "A2 老龙缩量",
    B1: "B1 竞价确认",
    B2: "B2 低开转强",
    B3: "B3 二波贴线",
  },
  point_levels: { A1: "A", A2: "A", B1: "B", B2: "B", B3: "B" },
  last_scan: null,
  entries: [
    {
      vt_symbol: "002403.SZSE",
      name: "爱仕达",
      group4: "二接三阴",
      n_board: 2,
      point: "B1",
      level: "B",
      actionable: true,
      avoid_static: null,
      auction_gate: null,
      prev_close: 15.0,
      limit_price: 16.5,
      foundation_yang: false,
      foundation_chg: -1.2,
      dist_h60: -20.9,
      ma_state: "++-",
      dist_ma10: -3.1,
      prior_height: null,
      prev_wave60: 0,
      prev_wave120: 0,
      chain: "下影→实体",
      b1_open: 1.1,
      b2_open: 7.2,
      b1_turn: 5.0,
      b2_turn: 6.5,
      turn_grad: 1.5,
      status: "holding",
      auction_pct: 2.1,
      opened: null,
      touched_at: "2026-09-04T09:41:00+08:00",
      entry_price: 16.5,
      entry_time: "2026-09-04T09:41:00+08:00",
      last_price: 16.5,
      change_pct: 10.0,
      sealed: true,
      streak_h: 1,
      exit_date: null,
      exit_price: null,
      exit_reason: null,
      ret_pct: null,
    },
    {
      vt_symbol: "605398.SSE",
      name: "新炬网络",
      group4: "三接四阳",
      n_board: 3,
      point: "—",
      level: "—",
      actionable: false,
      avoid_static: null,
      auction_gate: null,
      prev_close: 20.0,
      limit_price: 22.0,
      foundation_yang: true,
      foundation_chg: 2.2,
      dist_h60: -16.1,
      ma_state: "+++",
      dist_ma10: 6.5,
      prior_height: null,
      prev_wave60: 0,
      prev_wave120: 0,
      chain: "实体→实体→下影",
      b1_open: 0.5,
      b2_open: 1.2,
      b1_turn: 4.0,
      b2_turn: 5.4,
      turn_grad: 1.4,
      status: "watching",
      auction_pct: 0.8,
      opened: null,
      touched_at: null,
      entry_price: null,
      entry_time: null,
      last_price: 20.4,
      change_pct: 2.0,
      sealed: null,
      streak_h: null,
      exit_date: null,
      exit_price: null,
      exit_reason: null,
      ret_pct: null,
    },
  ],
};

describe("HighRelayPage live refresh cadence", () => {
  it("polls the persisted pool snapshot every 30s during the session", () => {
    expect(HPR_LIVE_REFRESH_INTERVAL_MS).toBe(30 * 1000);
  });
});

describe("HprLiveView", () => {
  it("renders point badges, level marks and relay-specific status labels", () => {
    const html = renderToStaticMarkup(
      withProviders(
        <HprLiveView
          payload={LIVE_PAYLOAD}
          availableDates={["2026-09-04"]}
          selectedDate={null}
          onDateChange={() => undefined}
        />,
      ),
    );
    expect(html).toContain("高位接力 · 实时推荐");
    expect(html).toContain("首刻窗(09:30~09:45)");
    expect(html).toContain("B1 竞价确认(二接三阴)");
    expect(html).toContain("🔵轻仓");
    expect(html).toContain("雷达");
    expect(html).toContain("打3板");
    expect(html).toContain("打4板");
    expect(html).toContain("持有中");
    expect(html).toContain("爱仕达");
    expect(html).toContain("下影→实体");
  });
});

describe("HprLedgerView", () => {
  it("renders E3 exit reason labels and E0 comparison column", () => {
    const html = renderToStaticMarkup(
      withProviders(
        <HprLedgerView
          caliber="测试口径"
          months={[{ month: "2026-09", count: 1, win_rate: 100, avg_ret_pct: 12.6, total_ret_pct: 12.6 }]}
          month="2026-09"
          onMonthChange={() => undefined}
          ledgerDays={[
            {
              trade_date: "2026-09-03",
              count: 1,
              win: 1,
              avg_ret_pct: 12.6,
              trades: [
                {
                  vt_symbol: "002403.SZSE",
                  name: "爱仕达",
                  point: "B1",
                  level: "B",
                  group4: "二接三阴",
                  entry_price: 16.5,
                  auction_pct: 2.1,
                  sealed: true,
                  streak_h: 2,
                  exit_date: "2026-09-05",
                  exit_price: 18.58,
                  exit_reason: "break_close",
                  ret_pct: 12.6,
                  ret_e0: 12.6,
                  touch: "09:45",
                },
              ],
            },
          ]}
        />,
      ),
    );
    expect(html).toContain("断板日收盘卖");
    expect(html).toContain("2板");
    expect(html).toContain("B1");
    expect(html).toContain("对照E0");
    expect(html).toContain("炸板当日收盘走");
  });
});

describe("ShortTermResearchPage", () => {
  it("registers 高位接力 as a research tab", () => {
    const html = renderToStaticMarkup(
      withProviders(<ShortTermResearchPage />, ["/short-term?research=high-relay"]),
    );
    expect(html).toContain("高位接力");
    expect(html).toContain("N型补涨打板");
    expect(html).toContain("潜龙首板");
    expect(html).toContain("低吸");
  });
});
