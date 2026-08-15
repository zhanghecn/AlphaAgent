import { describe, expect, it } from "vitest";

import {
  buildFetchWindow,
  displayWindowRange,
  smaSeries,
  DISPLAY_AFTER_SIGNAL_BARS,
  DISPLAY_BEFORE_NARRATIVE_BARS,
  DISPLAY_FALLBACK_BEFORE_SIGNAL_BARS,
  FETCH_FORWARD_CALENDAR_DAYS,
  FETCH_LOOKBACK_CALENDAR_DAYS,
} from "./guideKline";

function makeBars(dates: string[], closes?: number[]) {
  return dates.map((trade_date, index) => ({
    trade_date,
    open: closes?.[index] ?? index + 1,
    close: closes?.[index] ?? index + 1,
    high: closes?.[index] ?? index + 1,
    low: closes?.[index] ?? index + 1,
    volume: 1000,
    turnover: null,
    change_pct: null,
  }));
}

/** 生成连续日期序列（不跳周末，纯索引语义测试用）。 */
function dateSeries(start: string, count: number): string[] {
  const base = new Date(`${start}T00:00:00Z`);
  return Array.from({ length: count }, (_, index) => {
    const d = new Date(base.getTime() + index * 86400000);
    return d.toISOString().slice(0, 10);
  });
}

describe("smaSeries", () => {
  it("与输入索引对齐，前 window-1 位为 null", () => {
    expect(smaSeries([1, 2, 3, 4, 5], 3)).toEqual([null, null, 2, 3, 4]);
  });

  it("window=1 时等于原序列", () => {
    expect(smaSeries([7, 9], 1)).toEqual([7, 9]);
  });

  it("序列不足 window 时全为 null", () => {
    expect(smaSeries([1, 2], 5)).toEqual([null, null]);
  });
});

describe("buildFetchWindow", () => {
  it("有底盘起点时以底盘起点向前扩 75 个日历日（MA30 预热）", () => {
    const w = buildFetchWindow("2026-07-24", "2026-07-15");
    expect(w.fetchStart).toBe("2026-05-01"); // 07-15 往前 75 天
    expect(w.fetchEnd).toBe("2026-08-23"); // 信号日往后 30 天
  });

  it("无底盘起点时以信号日为锚向前扩", () => {
    const withAnchor = buildFetchWindow("2026-07-24", "2026-07-15");
    const withoutAnchor = buildFetchWindow("2026-07-24", null);
    expect(withoutAnchor.fetchStart > withAnchor.fetchStart).toBe(true);
    // 精确值：信号日 -75 天
    expect(withoutAnchor.fetchStart).toBe("2026-05-10");
    expect(withoutAnchor.fetchEnd).toBe(withAnchor.fetchEnd);
  });

  it("跨年/跨月换算正确（2 月案例）", () => {
    const w = buildFetchWindow("2026-02-12", "2026-02-10");
    expect(w.fetchStart).toBe("2025-11-27");
  });

  it("常量口径：75 天回看 ≈50 个交易日，30 天前向覆盖 D+10 展示", () => {
    expect(FETCH_LOOKBACK_CALENDAR_DAYS).toBe(75);
    expect(FETCH_FORWARD_CALENDAR_DAYS).toBe(30);
    expect(DISPLAY_BEFORE_NARRATIVE_BARS).toBe(5);
    expect(DISPLAY_FALLBACK_BEFORE_SIGNAL_BARS).toBe(40);
    expect(DISPLAY_AFTER_SIGNAL_BARS).toBe(10);
  });
});

describe("displayWindowRange", () => {
  it("有底盘起点：窗口从底盘起点前 5 根到信号日后 10 根", () => {
    const dates = dateSeries("2026-05-01", 80); // 05-01 .. 07-19
    const bars = makeBars(dates);
    // 底盘起点 = 第 20 根，信号日 = 第 30 根
    const range = displayWindowRange(bars, dates[30], dates[20]);
    expect(range).toEqual({ start: 15, end: 40 });
  });

  it("无底盘起点：回落到信号日前 40 根", () => {
    const dates = dateSeries("2026-01-01", 100);
    const bars = makeBars(dates);
    const range = displayWindowRange(bars, dates[60], null);
    expect(range).toEqual({ start: 20, end: 70 });
  });

  it("信号日贴近序列末尾时截断，不越界", () => {
    const dates = dateSeries("2026-01-01", 50);
    const bars = makeBars(dates);
    const range = displayWindowRange(bars, dates[48], null);
    expect(range).toEqual({ start: 8, end: 49 });
  });

  it("底盘起点贴近序列开头时截断到 0", () => {
    const dates = dateSeries("2026-01-01", 40);
    const bars = makeBars(dates);
    const range = displayWindowRange(bars, dates[10], dates[2]);
    expect(range).toEqual({ start: 0, end: 20 });
  });

  it("底盘起点不是交易日时取其后第一个交易日", () => {
    const dates = dateSeries("2026-05-01", 80).filter((d) => d !== "2026-05-21");
    const bars = makeBars(dates);
    // 第 20 根被挖掉，底盘锚 2026-05-21 → 落到下一根 05-22（索引 20）
    const range = displayWindowRange(bars, dates[31], "2026-05-21");
    expect(range).toEqual({ start: 15, end: 41 });
  });

  it("停牌缺口不影响交易日索引语义", () => {
    const dates = dateSeries("2026-01-01", 60).filter(
      (d) => d < "2026-02-01" || d > "2026-02-20",
    );
    const bars = makeBars(dates);
    const signalIdx = dates.indexOf("2026-02-21");
    expect(signalIdx).toBeGreaterThan(0);
    const range = displayWindowRange(bars, "2026-02-21", null);
    // 缺口压缩后剩余 40 根，前后窗口分别被截断到序列边界
    expect(range).toEqual({
      start: Math.max(0, signalIdx - 40),
      end: Math.min(dates.length - 1, signalIdx + 10),
    });
  });

  it("信号日不在序列中返回 null", () => {
    const bars = makeBars(dateSeries("2026-01-01", 30));
    expect(displayWindowRange(bars, "2026-08-08", null)).toBeNull();
  });

  it("空序列返回 null", () => {
    expect(displayWindowRange([], "2026-08-08", null)).toBeNull();
  });
});
