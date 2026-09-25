import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { ShortTermResearchPage } from "./ShortTermResearchPage";
import { FBB_LIVE_REFRESH_INTERVAL_MS } from "./FanbaoPage";
import type { FbbLivePayload } from "@/api/fanbao";
import { FbbLedgerView } from "@/features/fanbao/FbbLedgerView";
import { FbbLiveView } from "@/features/fanbao/FbbLiveView";

function withProviders(node: React.ReactElement, routerEntries: string[] = ["/"]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={routerEntries}>{node}</MemoryRouter>
    </QueryClientProvider>
  );
}

const LIVE_PAYLOAD: FbbLivePayload = {
  status: "ok",
  trade_date: "2026-09-25",
  stale: false,
  session_stage: "first_window",
  rules_version: "fbb-v2.0",
  counts: {
    pool: 3,
    actionable: 1,
    signals: 1,
    by_group: { "2板阴": 2, "5+板阳": 1 },
    by_gap: { "1": 1, "2": 2 },
    by_point: { S1: 1 },
    by_status: { watching: 2, holding: 1 },
  },
  mkt_lim_tm1: 46,
  group6_labels: {
    "2板阴": "2板反包·阴", "2板阳": "2板反包·阳",
    "4板阴": "4板反包·阴", "4板阳": "4板反包·阳",
    "5+板阴": "5+板反包·阴", "5+板阳": "5+板反包·阳",
  },
  point_labels: {
    S1: "S1 一根急杀",
    S2: "S2 四板阴断1",
    S3: "S3 五板+阳断1",
    O1: "O1 五板+阴断1",
    O2: "O2 四板阴断3",
  },
  point_levels: { S1: "S", S2: "S", S3: "S", O1: "O", O2: "O" },
  last_scan: null,
  entries: [
    {
      vt_symbol: "002303.SZSE",
      name: "美盈森",
      group6: "2板阴",
      n_board: 2,
      seg: "2板",
      gap: 2,
      yin_yang: "阴",
      point: "S1",
      level: "S",
      actionable: true,
      avoid_static: null,
      prev_close: 4.4,
      limit_price: 4.84,
      break_end: "2026-09-22",
      wave_start: "2026-09-21",
      break_days: "阳-2.9→阴-5.2",
      break_yin_count: 1,
      break_zha_days: 0,
      last_entity: "阴",
      last_open_pct: -1.2,
      high_var: null,
      break_drop_pct: -8.0,
      pit_depth_pct: -8.0,
      dist_ma5: -0.5,
      dist_h60: -12.3,
      ma_state: "+++",
      dist_ma10: -2.1,
      chain: "实体→下影",
      prev_wave60: 0,
      prev_wave120: 0,
      status: "holding",
      auction_pct: 1.2,
      opened: null,
      touched_at: "2026-09-25T09:41:00+08:00",
      entry_price: 4.84,
      entry_time: "2026-09-25T09:41:00+08:00",
      last_price: 4.84,
      change_pct: 10.0,
      sealed: true,
      streak_h: 1,
      exit_date: null,
      exit_price: null,
      exit_reason: null,
      ret_pct: null,
      bad_ticket: null,
    },
    {
      vt_symbol: "605058.SSE",
      name: "澳弘电子",
      group6: "2板阳",
      n_board: 2,
      seg: "2板",
      gap: 1,
      yin_yang: "阳",
      point: "—",
      level: "—",
      actionable: false,
      avoid_static: "2板0阴:断板期没洗盘",
      prev_close: 20.0,
      limit_price: 22.0,
      break_end: "2026-09-24",
      wave_start: "2026-09-23",
      break_days: "阳+1.1",
      break_yin_count: 0,
      break_zha_days: 0,
      last_entity: "阳",
      last_open_pct: 0.8,
      high_var: null,
      break_drop_pct: 1.1,
      pit_depth_pct: 1.1,
      dist_ma5: 3.2,
      dist_h60: -5.0,
      ma_state: "+++",
      dist_ma10: 4.0,
      chain: "实体→实体",
      prev_wave60: 0,
      prev_wave120: 0,
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
      bad_ticket: null,
    },
    {
      vt_symbol: "601811.SSE",
      name: "新华文轩",
      group6: "5+板阳",
      n_board: 5,
      seg: "5+板",
      gap: 1,
      yin_yang: "阳",
      point: "—",
      level: "—",
      actionable: false,
      avoid_static: null,
      prev_close: 18.0,
      limit_price: 19.8,
      break_end: "2026-09-24",
      wave_start: "2026-09-17",
      break_days: "阳+0.4",
      break_yin_count: 0,
      break_zha_days: 0,
      last_entity: "阳",
      last_open_pct: 0.5,
      high_var: null,
      break_drop_pct: 0.4,
      pit_depth_pct: 0.4,
      dist_ma5: 8.1,
      dist_h60: -1.2,
      ma_state: "+++",
      dist_ma10: 10.0,
      chain: "实体→一字→实体→实体→实体",
      prev_wave60: 0,
      prev_wave120: 0,
      status: "watching",
      auction_pct: 0.5,
      opened: null,
      touched_at: null,
      entry_price: null,
      entry_time: null,
      last_price: 18.2,
      change_pct: 1.1,
      sealed: null,
      streak_h: null,
      exit_date: null,
      exit_price: null,
      exit_reason: null,
      ret_pct: null,
      bad_ticket: null,
    },
  ],
};

describe("FanbaoPage live refresh cadence", () => {
  it("polls the persisted pool snapshot every 30s during the session", () => {
    expect(FBB_LIVE_REFRESH_INTERVAL_MS).toBe(30 * 1000);
  });
});

describe("FbbLiveView", () => {
  it("renders point badges, break-period columns and dead-cell marks", () => {
    const html = renderToStaticMarkup(
      withProviders(
        <FbbLiveView
          payload={LIVE_PAYLOAD}
          availableDates={["2026-09-25"]}
          selectedDate={null}
          onDateChange={() => undefined}
        />,
      ),
    );
    expect(html).toContain("断板反包 · 实时推荐");
    expect(html).toContain("S1 低开急杀(2板·跌8~15%只洗一次,末日低开或平开)");
    expect(html).toContain("✅出手");
    expect(html).toContain("死格");
    expect(html).toContain("雷达");
    expect(html).toContain("累计%");
    expect(html).toContain("阴线数");
    expect(html).toContain("末开%");
    expect(html).toContain("坑深%");
    expect(html).toContain("阳-2.9→阴-5.2");
    expect(html).toContain("持有中");
    expect(html).toContain("美盈森");
    expect(html).toContain("实体→下影");
    expect(html).toContain("断1");
    expect(html).toContain("昨日涨停 46 家");
  });
});

describe("FbbLedgerView", () => {
  it("renders good/bad ticket groups with break-period context", () => {
    const html = renderToStaticMarkup(
      withProviders(
        <FbbLedgerView
          caliber="测试口径"
          months={[{ month: "2026-09", count: 2, bad: 1, win_rate: 50, avg_ret_pct: 1.0, total_ret_pct: 2.0 }]}
          month="2026-09"
          onMonthChange={() => undefined}
          ledgerDays={[
            {
              trade_date: "2026-09-03",
              count: 2,
              win: 1,
              bad: 1,
              avg_ret_pct: 1.0,
              trades: [
                {
                  vt_symbol: "603330.SSE",
                  name: "上海天洋",
                  point: "S1",
                  level: "S",
                  group6: "2板阴",
                  gap: 3,
                  n_board: 2,
                  yin_yang: "阴",
                  entry_price: 20.0,
                  sealed: false,
                  streak_h: 0,
                  exit_date: "2026-09-03",
                  exit_price: 18.2,
                  exit_reason: "break_day_close",
                  ret_pct: -9.0,
                  is_bad: true,
                  result: "炸板",
                  break_drop_pct: -9.4,
                  break_yin_count: 1,
                  last_entity: "阴",
                  last_open_pct: -2.1,
                  high_var: false,
                  pit_depth_pct: -9.4,
                  dist_ma5: -2.0,
                  touch: "09:45",
                },
                {
                  vt_symbol: "002303.SZSE",
                  name: "美盈森",
                  point: "S1",
                  level: "S",
                  group6: "2板阴",
                  gap: 2,
                  n_board: 2,
                  yin_yang: "阴",
                  entry_price: 4.84,
                  sealed: true,
                  streak_h: 2,
                  exit_date: "2026-09-09",
                  exit_price: 5.85,
                  exit_reason: "break_close",
                  ret_pct: 20.9,
                  is_bad: false,
                  result: "封次日正",
                  break_drop_pct: -8.0,
                  break_yin_count: 1,
                  last_entity: "阴",
                  last_open_pct: -1.2,
                  high_var: false,
                  pit_depth_pct: -8.0,
                  dist_ma5: -0.5,
                  touch: "10:00",
                },
              ],
            },
          ]}
        />,
      ),
    );
    expect(html).toContain("坏票 — 1 笔");
    expect(html).toContain("好票 — 1 笔");
    expect(html).toContain("炸板当日·收盘卖");
    expect(html).toContain("断板日收盘卖");
    expect(html).toContain("S1·出");
    expect(html).toContain("累计%");
    expect(html).toContain("次日收盘低于买价");
  });
});

describe("ShortTermResearchPage", () => {
  it("registers 断板反包 as a research tab", () => {
    const html = renderToStaticMarkup(
      withProviders(<ShortTermResearchPage />, ["/short-term?research=fanbao"]),
    );
    expect(html).toContain("断板反包");
    expect(html).toContain("高位接力");
    expect(html).toContain("N型补涨打板");
    expect(html).toContain("潜龙首板");
    expect(html).toContain("低吸");
  });
});
