import { useState } from "react";
import { ChevronDown } from "lucide-react";

import type {
  LimitUpLaneLedger,
  LimitUpLaneLedgerTrade,
} from "@/api/limitUp";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { cn } from "@/lib/utils";
import { summarizeLedgerDay, weekdayLabel } from "./ledgerTimeline";
import {
  amountTone,
  boardStatusLabel,
  d1OutcomeLabel,
  entryKindLabel,
  factorLabel,
  formatPrice,
  setupTagLabel,
  twoToThreeQualityLabel,
  twoToThreeRiskTitle,
} from "./liveFormat";

export interface LedgerTimelineDay {
  date: string;
  ledger?: LimitUpLaneLedger;
  loading: boolean;
}

interface LedgerTimelineProps {
  days: LedgerTimelineDay[];
}

export function LedgerTimeline({ days }: LedgerTimelineProps) {
  return (
    <div className="overflow-x-auto" aria-label="历史交割单时间轴">
      <div className="flex min-w-max items-stretch divide-x">
        {days.map((day) => (
          <LedgerDayColumn key={day.date} day={day} />
        ))}
      </div>
    </div>
  );
}

function LedgerDayColumn({ day }: { day: LedgerTimelineDay }) {
  const summary = day.ledger ? summarizeLedgerDay(day.ledger) : null;
  const displayTrades = summary
    ? (summary.trades.length ? summary.trades : summary.observations)
    : [];
  return (
    <section className="flex w-72 shrink-0 flex-col" aria-label={`${day.date} 交割单`}>
      <header className={cn(
        "border-b px-3 py-2.5",
        summary?.observationOnly ? "bg-amber-500/5" : "bg-muted/20",
      )}>
        <div className="flex items-baseline gap-2">
          <span className="text-sm font-semibold tabular-nums">{day.date.slice(5)}</span>
          <span className="text-xs text-muted-foreground">{weekdayLabel(day.date)}</span>
          {summary && summary.totalReturnPct != null && (
            <span className={cn("ml-auto text-sm font-bold tabular-nums", amountTone(summary.totalReturnPct))}>
              {formatSigned(summary.totalReturnPct)}
            </span>
          )}
        </div>
        <div className="mt-0.5 text-[11px] text-muted-foreground">
          {day.loading && !summary
            ? "读取中…"
            : summary
              ? summary.observationOnly
                ? `研究观察 ${summary.observations.length} 只 · 不计入交割`
                : summary.tradeCount
                  ? `正式交割 ${summary.tradeCount} 只 · ${summary.winCount}/${summary.closedCount} 胜`
                  : "空仓 · 无正式买点"
              : "无数据"}
        </div>
      </header>
      <div className="flex-1 space-y-2 p-2">
        {day.loading && !summary ? (
          <div className="space-y-2 p-1">
            <div className="h-20 animate-pulse rounded-md bg-muted" />
            <div className="h-20 animate-pulse rounded-md bg-muted" />
          </div>
        ) : displayTrades.length ? (
          displayTrades.map((trade) => (
            <LedgerTradeCard
              key={`${trade.buy_date}:${trade.vt_symbol}`}
              trade={trade}
              observation={Boolean(summary?.observationOnly)}
            />
          ))
        ) : (
          <div className="flex h-24 items-center justify-center rounded-md border border-dashed text-xs text-muted-foreground">
            系统空仓
          </div>
        )}
      </div>
    </section>
  );
}

function LedgerTradeCard({ trade, observation }: { trade: LimitUpLaneLedgerTrade; observation: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const setups = (trade.setup_tags ?? []).map(setupTagLabel).join(" · ");
  const factors = trade.favorable_factors?.map(factorLabel).join("；") || "无可执行证据";
  return (
    <article
      className={cn(
        "overflow-hidden rounded-md border bg-card",
        trade.return_pct != null && trade.return_pct > 0 && "border-rise/40",
        trade.return_pct != null && trade.return_pct <= 0 && "border-fall/40",
        observation && "border-amber-500/40",
      )}
    >
      <button
        type="button"
        className="w-full px-3 py-2.5 text-left"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
      >
        <div className="flex items-center gap-2">
          <div className="min-w-0 flex-1">
            <StockIdentityLink name={trade.name} vtSymbol={trade.vt_symbol} />
          </div>
          <span className={cn("text-base font-bold tabular-nums", amountTone(trade.return_pct))}>
            {trade.return_pct != null ? formatSigned(trade.return_pct) : "待D+1"}
          </span>
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px]">
          <span className="tabular-nums text-muted-foreground">{trade.buy_time?.slice(0, 8)} 买</span>
          <span className="tabular-nums text-muted-foreground">{formatPrice(trade.buy_price)}</span>
          <span className={cn(
            "rounded-full px-1.5 py-px font-medium",
            trade.d_board_status === "sealed" ? "bg-rise/10 text-rise" : "bg-fall/10 text-fall",
          )}>
            {boardStatusLabel(trade.d_board_status)}
          </span>
          <span className="text-muted-foreground">{d1OutcomeLabel(trade.d1_outcome)}</span>
          {(trade.split_count ?? 1) > 1 && (
            <span className="rounded-full bg-sky-500/10 px-1.5 py-px font-medium text-sky-600 dark:text-sky-400">
              分{trade.split_count}批
            </span>
          )}
          <ChevronDown
            size={13}
            className={cn("ml-auto text-muted-foreground transition-transform", expanded && "rotate-180")}
          />
        </div>
      </button>
      {expanded && (
        <div className="space-y-1.5 border-t bg-muted/10 px-3 py-2.5 text-[11px] leading-4">
          <div className="text-muted-foreground">
            买入 {trade.buy_date} {trade.buy_time} · {formatPrice(trade.buy_price)} · {entryKindLabel(trade.signal_kind ?? "")}
          </div>
          <div className="text-muted-foreground">
            卖出 {trade.sell_date ?? "待 D+1"} {trade.sell_time ?? ""} · {formatPrice(trade.sell_price)} · 官方收盘价
          </div>
          {trade.exit_splits && trade.exit_splits.length > 1 && (
            <div className="text-muted-foreground">
              <span className="font-medium text-foreground">分批卖出：</span>
              {trade.exit_splits.map((split, i) => (
                <span key={i}>
                  {" "}{split.exit_reason} {Math.round(split.volume)}股
                  {split.return_pct != null ? ` ${formatSigned(split.return_pct)}` : ""}
                  {i < (trade.exit_splits?.length ?? 0) - 1 ? " ·" : ""}
                </span>
              ))}
            </div>
          )}
          {trade.quality_priority_tier && (
            <div className="text-muted-foreground">
              质量层 {qualityTierLabel(trade.quality_priority_tier)} · 胜率 {formatQualityProbability(trade.quality_win_probability)} · D+1预期 {formatQualityReturn(trade.quality_expected_d1_net_return_pct)}
            </div>
          )}
          {trade.lane === "two_to_three" && (
            <div className="text-muted-foreground" title={twoToThreeRiskTitle(trade.two_to_three_risk_flags)}>
              {twoToThreeQualityLabel(trade.two_to_three_quality_tier, trade.two_to_three_risk_count)}
            </div>
          )}
          {setups && <div className="font-medium text-foreground">{setups}</div>}
          <div className="text-muted-foreground">{factors}</div>
        </div>
      )}
    </article>
  );
}

function formatSigned(value: number): string {
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function qualityTierLabel(value: string): string {
  if (value === "A_industry_expanding") return "A";
  if (value === "C_capital_diffusion_rescue") return "C";
  if (value === "B_recognition_only") return "B";
  return value;
}

function formatQualityProbability(value?: number | null): string {
  return value == null ? "-" : `${(value * 100).toFixed(1)}%`;
}

function formatQualityReturn(value?: number | null): string {
  return value == null ? "-" : `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}
