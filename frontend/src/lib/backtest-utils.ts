/**
 * Shared utilities for backtest and portfolio components.
 * Extracted from QuantTradingPage and PortfolioPage.
 */

/** Format a metric value based on its key naming convention. */
export function formatMetric(key: string, value: number | null): string {
  if (value == null) return "--";
  if (key.endsWith("_pct") || key === "win_rate") {
    const pct = key === "win_rate" ? value * 100 : value;
    const sign = pct > 0 ? "+" : "";
    return `${sign}${pct.toFixed(2)}%`;
  }
  if (key.includes("cash") || key.includes("equity") || key.includes("win") || key.includes("loss")) {
    return formatAmountCompact(value);
  }
  return value.toFixed(2);
}

/** Format large numbers in 亿/万 (supports negative values). */
export function formatAmountCompact(value: number | null | undefined): string {
  if (value == null) return "--";
  const abs = Math.abs(value);
  if (abs >= 1e8) return `${(value / 1e8).toFixed(2)}亿`;
  if (abs >= 1e4) return `${(value / 1e4).toFixed(2)}万`;
  return value.toFixed(2);
}

/** Extract a finite number from an unknown value. */
export function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Format a number with fixed decimal places. */
export function formatNumber(value: number | null | undefined, digits = 2): string {
  if (value == null) return "--";
  return value.toFixed(digits);
}

/** Normalize ISO/Timestamp to display string (YYYY-MM-DD HH:mm). */
export function formatTime(value: string | null | undefined): string {
  if (!value) return "--";
  const normalized = value.replace("T", " ");
  return normalized.length > 16 ? normalized.slice(0, 16) : normalized;
}

/** Map a source string to a human-readable label. */
export function sourceLabel(source?: string | null): string {
  if (source === "manual") return "手动";
  if (source === "quant_screen") return "量化筛选";
  if (source === "simulation_auto") return "自动模拟";
  if (source === "quant_auto") return "量化自动";
  return source || "--";
}

/** Compare two semver-like version strings. Returns negative if left < right. */
export function compareVersions(left: string, right: string): number {
  const leftParts = left.split(".").map((item) => Number(item) || 0);
  const rightParts = right.split(".").map((item) => Number(item) || 0);
  const length = Math.max(leftParts.length, rightParts.length);
  for (let index = 0; index < length; index += 1) {
    const diff = (leftParts[index] ?? 0) - (rightParts[index] ?? 0);
    if (diff !== 0) return diff;
  }
  return 0;
}

/** Map a robustness check status to a display label. */
export function robustnessStatus(status: string): string {
  if (status === "pass") return "通过";
  if (status === "fail") return "未通过";
  return "需复核";
}

/** Format a robustness diagnostic value based on its type. */
export function formatRobustnessValue(value: number | null | undefined, valueType?: string): string {
  if (valueType === "count") return value == null ? "--" : value.toLocaleString();
  if (value == null) return "--";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

/** Map a backtest audit event to a display label. */
export function eventLabel(event: { event_type: string; side?: string; status?: string }): string {
  const side = event.side === "BUY" ? "买入" : event.side === "SELL" ? "卖出" : event.side ?? "--";
  if (event.event_type === "trade") return `${side}成交`;
  if (event.status === "filled") return `${side}订单成交`;
  if (event.status === "rejected") return `${side}订单拒绝`;
  return `${side}订单`;
}

/** Map an execution mode string to a display label. */
export function executionModeLabel(mode?: string | null): string {
  if (mode === "minute_1430") return "实时分钟";
  if (mode === "daily_close_proxy") return "收盘代理";
  if (mode === "minute_1430_sell") return "实时分钟卖出";
  if (mode === "daily_close_proxy_sell") return "收盘代理卖出";
  if (mode === "strict_1430_required") return "严格分钟";
  if (mode === "strict_1430_required_sell") return "严格分钟卖出";
  if (mode === "limit_up_tail_unfilled") return "涨停未买";
  if (mode === "limit_down_tail_blocked") return "跌停未卖";
  if (mode === "limit_down_open_blocked") return "开盘跌停未卖";
  if (mode === "minute_tail_ma5") return "实时分钟";
  if (mode === "daily_next_open") return "次日开盘";
  if (mode === "daily_next_open_sell") return "次日开盘卖出";
  if (mode === "daily_next_open_fallback") return "开盘回退";
  if (mode === "minute_tail_ma5_required") return "严格分钟";
  return mode || "--";
}

/** Determine the CSS color class for a backtest metric key. */
export function metricColor(key: string, value: number | null): string {
  if (value == null) return "";
  if (key === "max_drawdown_pct") return "text-fall";
  if (key === "average_loss") return "text-fall";
  if (key.includes("return") || key === "average_win") {
    return value > 0 ? "text-rise" : value < 0 ? "text-fall" : "";
  }
  return "";
}

/** Minimum strategy version considered trustworthy for backtest results. */
export const MIN_TRUSTED_BACKTEST_VERSION = "0.1.8";

/**
 * Assess the trustworthiness of a backtest report.
 * Returns a verdict with status, labels, and actionable items.
 */
export function backtestTrustVerdict(report: {
  strategy_version: string;
  method?: {
    execution?: {
      execution_model?: string | null;
    };
  } | null;
  execution_quality?: {
    status?: string | null;
    buy_count?: number | null;
    daily_open_fallback_ratio?: number | null;
    daily_close_proxy_ratio?: number | null;
  } | null;
}) {
  const legacy = compareVersions(report.strategy_version, MIN_TRUSTED_BACKTEST_VERSION) < 0;
  const quality = report.execution_quality;
  const buyCount = quality?.buy_count ?? 0;
  const executionModel = report.method?.execution?.execution_model ?? "";
  const fallbackRatio = quality?.daily_open_fallback_ratio ?? 0;
  const proxyRatio = quality?.daily_close_proxy_ratio ?? 0;
  const items: string[] = [];
  const entryMode =
    buyCount <= 0
      ? "无成交"
      : executionModel === "legacy_next_open" || fallbackRatio >= 80
        ? "D+1开盘"
        : proxyRatio >= 80
          ? "D+1收盘"
          : "日线成交";

  if (legacy) {
    items.push("旧版本卖出撮合存在时间顺序风险：收盘触发条件可能按当天开盘成交，历史结果不要用于判断策略有效性。");
  }
  if (buyCount === 0) {
    items.push("这份报告没有买入成交，只能检查数据和筛选流程，不能统计策略胜率。");
  }
  if (buyCount > 0 && executionModel !== "legacy_next_open") {
    items.push("这份报告不是当前默认日线 D+1 开盘口径，和新主流程对比时建议重跑。");
  }

  if (legacy) {
    return {
      status: "invalid" as const,
      label: "需重跑",
      title: "这份旧回测不能信",
      description: "当前结果来自旧撮合版本，先重新运行回测再看收益、胜率和个股归因。",
      entryMode: "旧版撮合",
      items,
    };
  }
  if (quality?.status === "pass") {
    return {
      status: "pass" as const,
      label: "可复核",
      title: "日线回测可复核",
      description: "信号按历史逐日生成，买卖按下一交易日日线价格执行，适合做通用策略研究。",
      entryMode,
      items,
    };
  }
  return {
    status: "warning" as const,
    label: "需复核",
    title: "结果需要结合日志复核",
    description: "撮合版本已更新，但样本、财报覆盖和股票池范围仍可能影响结论。",
    entryMode,
    items,
  };
}
