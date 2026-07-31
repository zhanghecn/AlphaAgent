import type { LimitUpLiveSignal, LimitUpSignalSnapshot } from "@/api/limitUp";
import { liveSignalsForScope, preboardSignals } from "./livePortfolio";

export const BUY_ALERT_REENTRY_COOLDOWN_MS = 60_000;

export interface BuyAlertState {
  tradeDate: string;
  activeSymbols: string[];
  lastAlertAt: Record<string, number>;
}

export const EMPTY_BUY_ALERT_STATE: BuyAlertState = {
  tradeDate: "",
  activeSymbols: [],
  lastAlertAt: {},
};

export function evaluateBuyAlerts(
  snapshot: LimitUpSignalSnapshot | undefined,
  previous: BuyAlertState,
  now: number,
  enabled: boolean,
): { state: BuyAlertState; alerts: LimitUpLiveSignal[] } {
  if (!isUsableLiveSnapshot(snapshot)) {
    return { state: copyState(previous), alerts: [] };
  }

  const prior = previous.tradeDate === snapshot.trade_date
    ? previous
    : { ...EMPTY_BUY_ALERT_STATE, tradeDate: snapshot.trade_date };
  const previousSymbols = new Set(prior.activeSymbols);
  const currentSignals = alertableSignals(snapshot);
  const currentSymbols = currentSignals.map((signal) => signal.vt_symbol);
  const lastAlertAt = { ...prior.lastAlertAt };
  const alerts: LimitUpLiveSignal[] = [];

  for (const signal of currentSignals) {
    const lastAt = lastAlertAt[signal.vt_symbol];
    const cooldownPassed = lastAt == null || now - lastAt >= BUY_ALERT_REENTRY_COOLDOWN_MS;
    if (enabled && !previousSymbols.has(signal.vt_symbol) && cooldownPassed) {
      alerts.push(signal);
      lastAlertAt[signal.vt_symbol] = now;
    }
  }

  return {
    state: {
      tradeDate: snapshot.trade_date,
      activeSymbols: currentSymbols,
      lastAlertAt,
    },
    alerts,
  };
}

export function buyAlertContent(signal: LimitUpLiveSignal): { title: string; body: string } {
  const name = signal.name || signal.vt_symbol;
  const strategy = signal.strategy_name || "综合推荐";
  return {
    title: `${signal.entry_kind === "preboard" ? "板前买点" : "买点触发"} · ${name}`,
    body: [
      signal.vt_symbol,
      `现涨 ${formatSignedPct(signal.change_pct)}`,
      `距板 ${formatUnsignedPct(signal.distance_to_limit_pct)}`,
      strategy,
    ].join(" · "),
  };
}

function alertableSignals(snapshot: LimitUpSignalSnapshot): LimitUpLiveSignal[] {
  const selected = new Map<string, LimitUpLiveSignal>();
  const signals = [
    ...liveSignalsForScope(snapshot, "portfolio"),
    ...preboardSignals(snapshot),
  ];
  for (const signal of signals) {
    if (
      signal.signal_state !== "trigger_ready"
      && signal.execution_state !== "actionable"
    ) continue;
    if (!selected.has(signal.vt_symbol)) selected.set(signal.vt_symbol, signal);
  }
  return [...selected.values()];
}

function isUsableLiveSnapshot(
  snapshot: LimitUpSignalSnapshot | undefined,
): snapshot is LimitUpSignalSnapshot {
  return Boolean(
    snapshot
    && !snapshot.data_quality.is_stale
    && (snapshot.mode == null || snapshot.mode === "live_snapshot"),
  );
}

function copyState(state: BuyAlertState): BuyAlertState {
  return {
    tradeDate: state.tradeDate,
    activeSymbols: [...state.activeSymbols],
    lastAlertAt: { ...state.lastAlertAt },
  };
}

function formatSignedPct(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function formatUnsignedPct(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "-";
  return `${value.toFixed(2)}%`;
}
