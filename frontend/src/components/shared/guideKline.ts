import type { Bar } from "@/api/types";

/**
 * 低吸说明书案例图表的日线专用纯函数：MA 计算、拉取窗口（日历日）与
 * 显示窗口（交易日索引）切片。与 StockKlineChart 的内部实现分家——那里
 * 带分钟周期时区逻辑且是模块私有，本场景只需要 daily-only 的最小实现。
 */

/** 拉取窗口：底盘/信号锚前 75 个日历日（≈50 个交易日，MA30 预热 + 斜率回看）。 */
export const FETCH_LOOKBACK_CALENDAR_DAYS = 75;
/** 拉取窗口：信号日后 30 个日历日（覆盖 D+10 展示 + 春节级长假）。 */
export const FETCH_FORWARD_CALENDAR_DAYS = 30;
/** 显示窗口：底盘起点前多露 5 根，交代底盘前的下跌语境。 */
export const DISPLAY_BEFORE_NARRATIVE_BARS = 5;
/** 显示窗口：无底盘起点（research_pending 案例）时回落到信号日前 40 根。 */
export const DISPLAY_FALLBACK_BEFORE_SIGNAL_BARS = 40;
/** 显示窗口：信号日后 10 根，用于演示因子的后续效果。 */
export const DISPLAY_AFTER_SIGNAL_BARS = 10;

export interface GuideFetchWindow {
  fetchStart: string;
  fetchEnd: string;
}

/** ISO 日期（YYYY-MM-DD）加 N 个日历日，UTC 计算避免时区抖动。 */
export function addCalendarDays(isoDate: string, days: number): string {
  const base = new Date(`${isoDate}T00:00:00Z`);
  const shifted = new Date(base.getTime() + days * 86400000);
  return shifted.toISOString().slice(0, 10);
}

/** 数据拉取窗口：宽拉（日历日边界），供 /vnpy/local-bars 查询参数使用。 */
export function buildFetchWindow(
  signalDate: string,
  narrativeStartDate: string | null,
): GuideFetchWindow {
  return {
    fetchStart: addCalendarDays(
      narrativeStartDate ?? signalDate,
      -FETCH_LOOKBACK_CALENDAR_DAYS,
    ),
    fetchEnd: addCalendarDays(signalDate, FETCH_FORWARD_CALENDAR_DAYS),
  };
}

/** 收盘简单移动平均，与输入索引对齐，前 window-1 位为 null。 */
export function smaSeries(values: number[], window: number): (number | null)[] {
  const result: (number | null)[] = new Array(values.length).fill(null);
  let sum = 0;
  for (let index = 0; index < values.length; index += 1) {
    sum += values[index];
    if (index >= window) {
      sum -= values[index - window];
    }
    if (index >= window - 1) {
      result[index] = sum / window;
    }
  }
  return result;
}

export interface DisplayWindowRange {
  start: number;
  end: number;
}

/**
 * 显示窗口：交易日索引空间的闭区间 [start, end]。
 * 只保留「底盘 + 因子信号 + 信号后效果」段；停牌缺口因索引语义天然压缩。
 * 信号日不在序列中（数据缺失）返回 null。
 */
export function displayWindowRange(
  bars: Pick<Bar, "trade_date">[],
  signalDate: string,
  narrativeStartDate: string | null,
): DisplayWindowRange | null {
  const signalIndex = bars.findIndex((bar) => bar.trade_date === signalDate);
  if (signalIndex < 0) {
    return null;
  }
  let anchorIndex: number;
  if (narrativeStartDate) {
    // 底盘起点不一定是交易日：落到其后第一个实际交易日。
    const found = bars.findIndex((bar) => bar.trade_date >= narrativeStartDate);
    anchorIndex =
      (found < 0 ? signalIndex : Math.min(found, signalIndex)) -
      DISPLAY_BEFORE_NARRATIVE_BARS;
  } else {
    anchorIndex = signalIndex - DISPLAY_FALLBACK_BEFORE_SIGNAL_BARS;
  }
  return {
    start: Math.max(0, anchorIndex),
    end: Math.min(bars.length - 1, signalIndex + DISPLAY_AFTER_SIGNAL_BARS),
  };
}
