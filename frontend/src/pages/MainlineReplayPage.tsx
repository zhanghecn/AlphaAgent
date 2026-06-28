/**
 * MainlineReplayPage — 主线回放（量化复盘终端）
 *
 * 视觉：indigo 深色终端感。Signature = 资金强弱矩阵（选中板块多维体检）。
 * 结构：时间轴 + 三栏（主线榜热度条 / 大盘+资金矩阵 / 详情+成分股+关联）。
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { LoadingState } from "@/components/LoadingState";
import { RelationPanel } from "@/features/replay/RelationPanel";
import { SectorStocksTable } from "@/features/replay/SectorStocksTable";
import {
  fetchReplaySnapshot,
  fetchReplayTimeline,
  type IndexQuote,
  type SectorRankItem,
} from "@/api/mainlineReplay";
import { cn, formatAmount, formatPct } from "@/lib/utils";

export default function MainlineReplayPage() {
  const timelineQ = useQuery({
    queryKey: ["replayTimeline"],
    queryFn: fetchReplayTimeline,
    staleTime: 60_000,
  });
  const dates = timelineQ.data?.dates ?? [];
  const [selectedDate, setSelectedDate] = useState<string>("");
  const effectiveDate = selectedDate || dates[0] || "";

  const snapshotQ = useQuery({
    queryKey: ["replaySnapshot", effectiveDate],
    queryFn: () => fetchReplaySnapshot({ date: effectiveDate }),
    enabled: !!effectiveDate,
    staleTime: 60_000,
  });

  const [selectedSector, setSelectedSector] = useState<SectorRankItem | null>(null);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div>
        <h1 className="font-display text-xl font-bold tracking-tight">主线回放</h1>
        <p className="mt-0.5 text-xs text-muted-foreground">
          拖动时间轴回到任意交易日 · 主线 · 资金 · 个股
        </p>
      </div>

      {/* 时间轴 */}
      <div className="rounded-lg border bg-card p-3">
        {timelineQ.isLoading ? (
          <LoadingState rows={1} />
        ) : dates.length === 0 ? (
          <div className="text-sm text-muted-foreground">
            暂无回放数据。请先在 <a href="/data" className="underline">数据管理</a> 同步 sector_period_scores。
          </div>
        ) : (
          <DateScrubber dates={dates} value={effectiveDate} onChange={setSelectedDate} />
        )}
      </div>

      {/* 三栏 */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[300px_minmax(0,1fr)_340px]">
        {/* 左：主线榜（热度条 signature）*/}
        <div className="rounded-lg border bg-card p-3">
          <div className="mb-2 flex items-baseline justify-between">
            <span className="text-xs font-medium">主线板块榜</span>
            <span className="text-[10px] text-muted-foreground">热度 · 20日收益率</span>
          </div>
          {snapshotQ.isLoading ? (
            <LoadingState rows={8} />
          ) : (
            <div className="max-h-[calc(100vh-320px)] space-y-0.5 overflow-y-auto">
              {(snapshotQ.data?.ranking ?? []).map((r, i) => (
                <SectorRankRow
                  key={r.sector_id}
                  item={r}
                  rank={i + 1}
                  selected={selectedSector?.sector_id === r.sector_id}
                  onSelect={() => setSelectedSector(r)}
                />
              ))}
              {(snapshotQ.data?.ranking ?? []).length === 0 && (
                <div className="py-4 text-center text-xs text-muted-foreground">该日无主线评分</div>
              )}
            </div>
          )}
        </div>

        {/* 中：大盘 + 资金矩阵 */}
        <div className="space-y-4">
          <div className="rounded-lg border bg-card p-3">
            <div className="mb-2 text-xs font-medium text-muted-foreground">
              大盘指数 · {effectiveDate || "--"}
            </div>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
              {(snapshotQ.data?.index ?? []).map((ix) => (
                <IndexCard key={ix.vt_symbol} ix={ix} />
              ))}
              {(snapshotQ.data?.index ?? []).length === 0 && !snapshotQ.isLoading && (
                <div className="col-span-full py-3 text-center text-xs text-muted-foreground">该日无指数数据</div>
              )}
            </div>
          </div>

          {selectedSector ? (
            <div className="rounded-lg border bg-card p-3">
              <div className="mb-2 flex items-baseline justify-between">
                <span className="font-display text-sm font-semibold">
                  {selectedSector.name ?? selectedSector.sector_id}
                </span>
                <span className="text-[11px] uppercase tracking-wide text-muted-foreground">资金强弱矩阵</span>
              </div>
              <FundMatrix item={selectedSector} />
            </div>
          ) : (
            <div className="flex h-32 items-center justify-center rounded-lg border border-dashed text-xs text-muted-foreground">
              选中板块后显示资金强弱矩阵
            </div>
          )}
        </div>

        {/* 右：成分股 + 关联 */}
        <div className="space-y-4">
          {selectedSector ? (
            <>
              <div className="rounded-lg border bg-card p-3">
                <div className="mb-2 flex items-center gap-2">
                  <span className="inline-block h-2 w-2 rounded-full bg-indigo-400" />
                  <span className="font-display text-sm font-semibold">
                    {selectedSector.name ?? selectedSector.sector_id}
                  </span>
                </div>
                <SectorStocksTable sectorId={selectedSector.sector_id} date={effectiveDate} />
              </div>
              <div className="rounded-lg border bg-card p-3">
                <RelationPanel sectorId={selectedSector.sector_id} date={effectiveDate} />
              </div>
            </>
          ) : (
            <div className="flex h-40 items-center justify-center rounded-lg border border-dashed text-sm text-muted-foreground">
              ← 点左侧板块看成分股与关联
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── 时间轴：当前日期 font-display 大字 + scrubber + 左右刻度 ──

function DateScrubber({
  dates,
  value,
  onChange,
}: {
  dates: string[];
  value: string;
  onChange: (d: string) => void;
}) {
  const idx = Math.max(0, dates.indexOf(value));
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
      <div className="flex items-baseline gap-2">
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground">回放至</span>
        <span className="font-display text-lg font-bold tabular-nums text-indigo-300">{value || "--"}</span>
      </div>
      <div className="flex min-w-[200px] flex-1 items-center gap-3">
        <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground">{dates[dates.length - 1]}</span>
        <input
          type="range"
          min={0}
          max={Math.max(0, dates.length - 1)}
          value={idx}
          onChange={(e) => onChange(dates[Number(e.target.value)])}
          className="h-1 flex-1 cursor-pointer appearance-none rounded-full bg-muted accent-indigo-500"
        />
        <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground">{dates[0]}</span>
      </div>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border bg-background px-2 py-1 text-xs"
      >
        {dates.map((d) => (
          <option key={d} value={d}>{d}</option>
        ))}
      </select>
    </div>
  );
}

// ── 主线榜行：排名 + 名称 + 热度条 + 收益率 ──

function SectorRankRow({
  item,
  rank,
  selected,
  onSelect,
}: {
  item: SectorRankItem;
  rank: number;
  selected: boolean;
  onSelect: () => void;
}) {
  const heat = item.heat_score ?? 0;
  return (
    <button
      onClick={onSelect}
      className={cn(
        "flex w-full flex-col gap-1 rounded-md px-2 py-1.5 text-left transition-colors",
        selected ? "bg-indigo-500/15 ring-1 ring-inset ring-indigo-400/40" : "hover:bg-muted/60",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="flex min-w-0 items-center gap-1.5 text-sm">
          <span className="w-4 shrink-0 text-[11px] tabular-nums text-muted-foreground">{rank}</span>
          <span className={cn("truncate", selected ? "font-semibold text-indigo-200" : "font-medium")}>
            {item.name ?? item.sector_id}
          </span>
        </span>
        <span className={cn("shrink-0 text-xs tabular-nums", (item.return_pct ?? 0) >= 0 ? "text-rise" : "text-fall")}>
          {formatPct(item.return_pct)}
        </span>
      </div>
      {/* 热度条 */}
      <div className="flex items-center gap-1.5 pl-5">
        <div className="h-1 flex-1 overflow-hidden rounded-full bg-muted">
          <div
            className={cn("h-full rounded-full", selected ? "bg-indigo-400" : "bg-indigo-500/60")}
            style={{ width: `${Math.min(100, Math.max(0, heat))}%` }}
          />
        </div>
        <span className="w-7 shrink-0 text-right text-[10px] tabular-nums text-muted-foreground">{heat.toFixed(0)}</span>
      </div>
    </button>
  );
}

// ── 大盘指数卡 ──

function IndexCard({ ix }: { ix: IndexQuote }) {
  const up = (ix.change_pct ?? 0) >= 0;
  const null_pct = ix.change_pct == null;
  return (
    <div className="rounded-md border bg-background/40 px-2.5 py-2">
      <div className="text-[11px] text-muted-foreground">{ix.name}</div>
      <div className="mt-0.5 font-display text-base font-semibold tabular-nums">
        {ix.close != null ? ix.close.toFixed(2) : "--"}
      </div>
      <div className={cn("text-[11px] tabular-nums", null_pct ? "text-muted-foreground" : up ? "text-rise" : "text-fall")}>
        {formatPct(ix.change_pct)}
      </div>
    </div>
  );
}

// ── 资金强弱矩阵（signature）：6 维色编码体检 ──

function FundMatrix({ item }: { item: SectorRankItem }) {
  const trendColor = trendColorClass(item.trend_state);
  return (
    <div className="grid grid-cols-3 gap-2">
      <Metric label="热度分" value={fmt1(item.heat_score)} bar={item.heat_score} barColor="bg-indigo-500" />
      <Metric label="资金分" value={fmt1(item.fund_score)} bar={item.fund_score} barColor="bg-indigo-500" />
      <Metric label="趋势" value={item.trend_state ?? "--"} valueClass={trendColor} />
      <Metric
        label="收益率"
        value={formatPct(item.return_pct)}
        valueClass={(item.return_pct ?? 0) >= 0 ? "text-rise" : "text-fall"}
      />
      <Metric
        label="放量比"
        value={fmtRatio(item.volume_ratio)}
        valueClass={item.volume_ratio == null ? "" : item.volume_ratio >= 1 ? "text-indigo-300" : "text-muted-foreground"}
      />
      <Metric
        label="主力净流入"
        value={item.fund_inflow_available ? formatAmount(item.accumulated_main_inflow) : "近端无"}
        valueClass={item.fund_inflow_available ? ((item.accumulated_main_inflow ?? 0) >= 0 ? "text-rise" : "text-fall") : "text-muted-foreground"}
      />
    </div>
  );
}

function Metric({
  label,
  value,
  valueClass,
  bar,
  barColor,
}: {
  label: string;
  value: string;
  valueClass?: string;
  bar?: number | null;
  barColor?: string;
}) {
  return (
    <div className="rounded-md border bg-background/40 px-2 py-1.5">
      <div className="text-[10px] text-muted-foreground">{label}</div>
      <div className={cn("mt-0.5 font-display text-sm font-semibold tabular-nums", valueClass)}>{value}</div>
      {bar != null && (
        <div className="mt-1 h-0.5 overflow-hidden rounded-full bg-muted">
          <div className={cn("h-full rounded-full", barColor)} style={{ width: `${Math.min(100, Math.max(0, bar))}%` }} />
        </div>
      )}
    </div>
  );
}

function trendColorClass(t: string | null | undefined): string {
  if (!t) return "";
  if (t === "MAINLINE_UP" || t === "FAST_UP") return "text-rise";
  if (t === "ROTATION") return "text-amber-400";
  if (t === "FADING" || t === "WEAK") return "text-fall";
  return "";
}

function fmt1(v: number | null | undefined): string {
  return v == null ? "--" : v.toFixed(1);
}
function fmtRatio(v: number | null | undefined): string {
  return v == null ? "--" : `${v.toFixed(2)}x`;
}
