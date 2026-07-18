import { useEffect } from "react";
import { BellRing, X } from "lucide-react";

import type { BuyAlertBannerItem } from "./useBuyAlerts";

const AUTO_DISMISS_MS = 15_000;

interface BuyAlertBannerProps {
  items: BuyAlertBannerItem[];
  onDismiss: () => void;
  onLocate?: (vtSymbol: string) => void;
}

export function BuyAlertBanner({ items, onDismiss, onLocate }: BuyAlertBannerProps) {
  useEffect(() => {
    if (!items.length) return;
    const timer = window.setTimeout(onDismiss, AUTO_DISMISS_MS);
    return () => window.clearTimeout(timer);
  }, [items, onDismiss]);

  if (!items.length) return null;

  return (
    <div
      role="alert"
      aria-live="assertive"
      className="pointer-events-none fixed inset-x-0 top-3 z-50 flex justify-center px-3"
    >
      <div className="pointer-events-auto relative w-full max-w-xl overflow-hidden rounded-lg border-2 border-rise bg-card shadow-2xl shadow-rise/20">
        <span className="absolute inset-0 animate-ping rounded-lg border-2 border-rise/40 [animation-iteration-count:3]" aria-hidden />
        <div className="flex items-start gap-3 px-4 py-3">
          <span className="mt-1 flex h-9 w-9 shrink-0 animate-pulse items-center justify-center rounded-full bg-rise text-rise-foreground">
            <BellRing size={18} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-xs font-medium text-rise">买点语音播报中</div>
            <ul className="mt-1 space-y-1.5">
              {items.map((item) => (
                <li key={item.key}>
                  <button
                    type="button"
                    className="group flex w-full items-baseline gap-2 text-left"
                    onClick={() => {
                      onLocate?.(item.signal.vt_symbol);
                      onDismiss();
                    }}
                  >
                    <span className="truncate text-lg font-bold text-foreground group-hover:underline">
                      {item.signal.name || item.signal.vt_symbol}
                    </span>
                    <span className="shrink-0 text-sm font-semibold tabular-nums text-rise">
                      现涨 {formatPct(item.signal.change_pct)}
                    </span>
                    <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                      距板 {formatPct(item.signal.distance_to_limit_pct)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
          <button
            type="button"
            className="shrink-0 rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
            aria-label="关闭买点提醒横幅"
            onClick={onDismiss}
          >
            <X size={16} />
          </button>
        </div>
      </div>
    </div>
  );
}

function formatPct(value?: number | null) {
  return value == null || !Number.isFinite(value) ? "--" : `${value.toFixed(1)}%`;
}

export function alertBannerLocate(vtSymbol: string): void {
  const target = document.getElementById(signalAnchorId(vtSymbol));
  target?.scrollIntoView({ behavior: "smooth", block: "center" });
}

export function signalAnchorId(vtSymbol: string): string {
  return `limit-up-signal-${vtSymbol.replace(/[^a-zA-Z0-9]/g, "-")}`;
}
