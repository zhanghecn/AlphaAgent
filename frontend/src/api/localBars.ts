import { apiClient } from "./client";
import type { Bar } from "./types";

/** /vnpy/local-bars 的原始 item（vn.py BarData 的 API 序列化形状）。 */
interface LocalBarItem {
  datetime: string; // "2026-07-24T00:00:00"
  open_price: number;
  high_price: number;
  low_price: number;
  close_price: number;
  volume: number;
  turnover: number | null;
}

interface LocalBarsData {
  status: "ready" | "empty" | "unavailable" | string;
  count: number;
  items: LocalBarItem[];
  message?: string;
}

export interface LocalDailyBars {
  status: string;
  items: Bar[];
}

/**
 * 本地历史库日线（stock_daily_bars，raw 不复权，与低吸回测同口径）。
 * 按交易日日期范围过滤；说明书案例图表专用——/stocks/:symbol/bars 只支持
 * limit 不支持日期窗口，这里映射为 Bar 兼容形状便于复用图表工具函数。
 */
export async function fetchLocalDailyBars(
  vtSymbol: string,
  start: string,
  end: string,
): Promise<LocalDailyBars> {
  const qs = new URLSearchParams({
    vt_symbol: vtSymbol,
    start,
    end,
    limit: "5000",
  });
  const data = await apiClient.get<LocalBarsData>(`/vnpy/local-bars?${qs}`);
  const items = (data.items ?? []).map((item) => ({
    trade_date: item.datetime.slice(0, 10),
    open: item.open_price,
    high: item.high_price,
    low: item.low_price,
    close: item.close_price,
    volume: item.volume,
    turnover: item.turnover ?? null,
    change_pct: null,
  }));
  return { status: data.status, items };
}
