import type { LowSuctionStrategyOverview } from "@/api/lowSuction";

export type LiveTone = "go" | "wait" | "stop" | "info" | "muted";

export interface LiveStatus {
  tone: LiveTone;
  label: string;
  /** 阻塞时展示翻译后的原因，绝不让系统静默死亡 */
  detail?: string;
}

const STATUS_META: Record<string, { tone: LiveTone; label: string }> = {
  paper_account_active: { tone: "go", label: "纸面买入已记录" },
  signal_frozen: { tone: "go", label: "尾盘信号已确认" },
  preview_ready: { tone: "info", label: "盘中预警已更新" },
  awaiting_signal_window: { tone: "wait", label: "等待扫描窗口" },
  not_run: { tone: "muted", label: "今日尚未计算" },
  market_closed: { tone: "muted", label: "休市" },
};

const BLOCKING_REASON_LABELS: Record<string, string> = {
  future_or_outcome_columns_prohibited: "输入校验未通过（防未来函数守护）",
  d_minus_one_top3_missing: "缺少 D-1 龙头榜数据",
  signal_capture_not_ready: "尾盘信号尚未冻结",
  intraday_stock_quotes_missing: "盘中行情快照缺失",
  intraday_concept_quotes_missing: "概念行情快照缺失",
  intraday_benchmark_quotes_missing: "基准行情快照缺失",
  intraday_stock_quotes_stale: "盘中行情快照过期",
  intraday_concept_quotes_stale: "概念行情快照过期",
  intraday_benchmark_quotes_stale: "基准行情快照过期",
  outside_intraday_preview_window: "不在盘中预警窗口",
  outside_1450_signal_window: "不在 14:50 信号窗口",
  capture_trade_date_mismatch: "采集时间与信号日不一致",
  source_session_must_precede_signal: "源交易日必须早于信号日",
  d_minus_one_completed_session_missing: "缺少 D-1 完整交易日",
  complete_daily_session_missing: "缺少完整日线交易日",
  completed_d_minus_one_session_missing: "缺少 D-1 完整交易日",
};

/**
 * 把 session 状态塌缩成一盏状态灯：能不能行动一眼可读。
 * blocked 必须带出翻译后的阻塞原因——这是信号管道静默死亡的 UX 保险。
 */
export function deriveLiveStatus(strategy: LowSuctionStrategyOverview): LiveStatus {
  const session = strategy.session;
  if (session.status === "blocked") {
    return { tone: "stop", label: "信号计算受阻", detail: firstBlockingDetail(session.phases) };
  }
  const meta = STATUS_META[session.status];
  if (!meta) {
    return { tone: "muted", label: "状态未知" };
  }
  return { tone: meta.tone, label: meta.label };
}

/** 阻塞原因翻译成人话；未知码回退原文，方便排查 */
export function blockingReasonLabel(code: string): string {
  return BLOCKING_REASON_LABELS[code] ?? code;
}

function firstBlockingDetail(
  phases: LowSuctionStrategyOverview["session"]["phases"] | undefined,
): string | undefined {
  if (!phases) return undefined;
  const reasons = Object.values(phases)
    .filter((phase) => phase?.status === "blocked")
    .flatMap((phase) => phase.blocking_reasons ?? []);
  const unique = [...new Set(reasons)];
  if (unique.length === 0) return undefined;
  return unique.map(blockingReasonLabel).join(" · ");
}

/** 自适应轮询：跟随后端 auto_refresh_seconds，缺失时回退 60s */
export function liveRefetchIntervalMs(strategy: LowSuctionStrategyOverview): number {
  const seconds = strategy.session?.auto_refresh_seconds;
  return seconds != null && seconds > 0 ? seconds * 1000 : 60_000;
}
