/**
 * MainlineReplayPage — 概念指数（量化复盘终端）
 *
 * 视觉：暗色行情磁带。Signature = 概念指数曲线 + 连续状态带。
 * 结构：时间轴 + 三栏（概念指数榜 / 指数详情 / 成分股+共振）。
 */
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, CircleSlash, Flame, Radio, Sparkles } from "lucide-react";

import { LoadingState } from "@/components/LoadingState";
import { RelationPanel } from "@/features/replay/RelationPanel";
import { SectorStocksTable } from "@/features/replay/SectorStocksTable";
import {
  fetchLiveMainline,
  fetchReplaySnapshot,
  fetchReplayTimeline,
  type IndexQuote,
  type RelationItem,
  type SectorRankItem,
} from "@/api/mainlineReplay";
import { cn, formatAmount, formatPct } from "@/lib/utils";

type ReplayViewMode = "live" | "history";
type ConceptTapeFilter = "all" | "maintained" | "new" | "broken";
type NormalizedConceptStatus = "maintained" | "new" | "broken" | "watch";
type ConceptTapeCounts = Record<ConceptTapeFilter, number>;
type DrawablePoint = {
  date: string;
  close: number;
  temporary?: boolean;
};
type ChartShape = {
  width: number;
  height: number;
  path: string;
  areaPath: string;
  coords: Array<{ x: number; y: number; point: DrawablePoint }>;
  first: DrawablePoint;
  last: DrawablePoint;
  min: number;
  max: number;
};

const FILTERS: Array<{ value: ConceptTapeFilter; label: string }> = [
  { value: "all", label: "全部" },
  { value: "maintained", label: "维持" },
  { value: "new", label: "新起" },
  { value: "broken", label: "断档" },
];

export default function MainlineReplayPage() {
  const timelineQ = useQuery({
    queryKey: ["replayTimeline"],
    queryFn: fetchReplayTimeline,
    staleTime: 60_000,
  });
  const dates = timelineQ.data?.dates ?? [];
  const liveQ = useQuery({
    queryKey: ["mainlineLive"],
    queryFn: () => fetchLiveMainline(),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
  const liveReady = (liveQ.data?.ranking ?? []).length > 0;
  const [viewMode, setViewMode] = useState<ReplayViewMode>("live");
  const [selectedDate, setSelectedDate] = useState<string>("");
  const historyDate = selectedDate || dates[0] || "";
  const effectiveDate = viewMode === "live" ? (liveQ.data?.trade_date || historyDate) : historyDate;
  const relationDate = viewMode === "live" ? (liveQ.data?.base_daily_date || historyDate) : historyDate;
  useEffect(() => {
    if (dates.length === 0) return;
    if (!selectedDate || !dates.includes(selectedDate)) {
      setSelectedDate(dates[0]);
    }
  }, [dates, selectedDate]);
  useEffect(() => {
    if (!liveQ.isLoading && !liveReady && dates.length > 0 && viewMode === "live") {
      setViewMode("history");
    }
  }, [dates.length, liveQ.isLoading, liveReady, viewMode]);

  const snapshotQ = useQuery({
    queryKey: ["replaySnapshot", historyDate],
    queryFn: () => fetchReplaySnapshot({ date: historyDate }),
    enabled: !!historyDate && viewMode === "history",
    staleTime: 60_000,
  });

  const activeData = viewMode === "live" ? liveQ.data : snapshotQ.data;
  const activeLoading = viewMode === "live" ? liveQ.isLoading : snapshotQ.isLoading;
  const ranking = activeData?.ranking ?? [];
  const [tapeFilter, setTapeFilter] = useState<ConceptTapeFilter>("all");
  const filteredRanking = useMemo(
    () => ranking.filter((item) => matchesTapeFilter(item, tapeFilter)),
    [ranking, tapeFilter],
  );
  const tapeCounts = useMemo(() => conceptTapeCounts(ranking), [ranking]);
  const [selectedSectorId, setSelectedSectorId] = useState<string>("");
  const [selectedSectorOverride, setSelectedSectorOverride] = useState<SectorRankItem | null>(null);
  const selectedSector = useMemo(() => {
    const source = filteredRanking.length > 0 ? filteredRanking : ranking;
    if (source.length === 0) return null;
    return (
      source.find((item) => item.sector_id === selectedSectorId)
      ?? (selectedSectorOverride?.sector_id === selectedSectorId ? selectedSectorOverride : null)
      ?? source[0]
    );
  }, [filteredRanking, ranking, selectedSectorId, selectedSectorOverride]);

  function selectRankedSector(item: SectorRankItem) {
    setSelectedSectorOverride(null);
    setSelectedSectorId(item.sector_id);
  }

  function selectRelatedSector(item: RelationItem) {
    setSelectedSectorOverride({
      sector_id: item.sector_id,
      name: item.name ?? item.sector_id,
    });
    setSelectedSectorId(item.sector_id);
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div>
        <h1 className="font-display text-xl font-bold tracking-tight">概念指数</h1>
        <p className="mt-0.5 text-xs text-muted-foreground">
          指数走势 · 连续热度 · 今日资金 · 成分股
        </p>
      </div>

      {/* 时间轴 */}
      <div className="rounded-lg border bg-card p-3">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex rounded-md border bg-background p-0.5">
            <button
              type="button"
              onClick={() => setViewMode("live")}
              disabled={!liveReady && !liveQ.isLoading}
              className={cn(
                "rounded px-2.5 py-1 text-xs transition-colors disabled:cursor-not-allowed disabled:opacity-50",
                viewMode === "live" ? "bg-indigo-500 text-white" : "text-muted-foreground hover:bg-muted",
              )}
            >
              今日实时
            </button>
            <button
              type="button"
              onClick={() => setViewMode("history")}
              className={cn(
                "rounded px-2.5 py-1 text-xs transition-colors",
                viewMode === "history" ? "bg-indigo-500 text-white" : "text-muted-foreground hover:bg-muted",
              )}
            >
              历史回放
            </button>
          </div>
          <div className="text-xs text-muted-foreground">
            {viewMode === "live"
              ? `实时 ${liveQ.data?.trade_date ?? "--"} · 基准日 ${liveQ.data?.base_daily_date ?? "--"}`
              : `历史 ${historyDate || "--"}`}
          </div>
        </div>
        {viewMode === "live" ? (
          <LiveStatus data={liveQ.data} loading={liveQ.isLoading} />
        ) : timelineQ.isLoading ? (
          <LoadingState rows={1} />
        ) : dates.length === 0 ? (
          <div className="text-sm text-muted-foreground">
            暂无回放数据。请先在 <a href="/data" className="underline">数据管理</a> 同步 sector_period_scores。
          </div>
        ) : (
          <DateScrubber dates={dates} value={historyDate} onChange={setSelectedDate} />
        )}
      </div>

      {/* 三栏 */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[340px_minmax(0,1fr)_340px]">
        {/* 左：概念指数榜 */}
        <div className="rounded-lg border bg-card p-3">
          <div className="mb-2 flex items-baseline justify-between">
            <span className="text-xs font-medium">概念指数榜</span>
            <span className="text-[10px] text-muted-foreground">
              {viewMode === "live" ? "今日涨跌 · 连续状态" : "指数走势 · 热度"}
            </span>
          </div>
          <ConceptTapeFilters value={tapeFilter} counts={tapeCounts} onChange={setTapeFilter} />
          {activeLoading ? (
            <LoadingState rows={8} />
          ) : (
            <div className="max-h-[calc(100vh-320px)] space-y-0.5 overflow-y-auto">
              {filteredRanking.map((r, i) => (
                <SectorRankRow
                  key={r.sector_id}
                  item={r}
                  rank={i + 1}
                  selected={selectedSector?.sector_id === r.sector_id}
                  onSelect={() => selectRankedSector(r)}
                />
              ))}
              {filteredRanking.length === 0 && (
                <div className="py-4 text-center text-xs text-muted-foreground">
                  {ranking.length === 0
                    ? viewMode === "live" ? "今日暂无概念资金流" : "该日无概念评分"
                    : "当前分组暂无概念"}
                </div>
              )}
            </div>
          )}
        </div>

        {/* 中：概念指数详情 + 大盘 */}
        <div className="space-y-4">
          {selectedSector ? (
            <ConceptIndexDetail item={selectedSector} date={effectiveDate} />
          ) : (
            <div className="flex h-32 items-center justify-center rounded-lg border border-dashed text-xs text-muted-foreground">
              选中概念后显示指数走势
            </div>
          )}
          <MarketIndexStrip data={activeData?.index ?? []} loading={activeLoading} live={viewMode === "live"} date={effectiveDate} />
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
                <RelationPanel
                  sectorId={selectedSector.sector_id}
                  date={relationDate}
                  onSelectSector={selectRelatedSector}
                />
              </div>
            </>
          ) : (
            <div className="flex h-40 items-center justify-center rounded-lg border border-dashed text-sm text-muted-foreground">
              ← 点左侧概念看成分股与关联
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── 时间轴：当前日期 font-display 大字 + scrubber + 左右刻度 ──

function LiveStatus({ data, loading }: { data?: { latest_minute_time?: string | null; snapshot_updated_at?: string | null; message?: string }; loading: boolean }) {
  if (loading) return <LoadingState rows={1} />;
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
      <span>源表：sector_fund_flows</span>
      <span>分钟线：{shortDateTime(data?.latest_minute_time)}</span>
      <span>快照：{shortDateTime(data?.snapshot_updated_at)}</span>
      <span className="text-indigo-300">{data?.message ?? "动态计算中"}</span>
    </div>
  );
}

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
  const sliderValue = Math.max(0, dates.length - 1 - idx);
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
          value={sliderValue}
          onChange={(e) => onChange(dates[dates.length - 1 - Number(e.target.value)])}
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

function ConceptTapeFilters({
  value,
  counts,
  onChange,
}: {
  value: ConceptTapeFilter;
  counts: ConceptTapeCounts;
  onChange: (filter: ConceptTapeFilter) => void;
}) {
  return (
    <div className="mb-2 grid grid-cols-4 gap-1">
      {FILTERS.map((filter) => {
        const active = filter.value === value;
        return (
          <button
            key={filter.value}
            type="button"
            onClick={() => onChange(filter.value)}
            className={cn(
              "flex min-w-0 items-center justify-between gap-1 rounded-md border px-2 py-1.5 text-left text-[11px] transition-colors",
              active
                ? "border-indigo-400/50 bg-indigo-500/15 text-indigo-200"
                : "bg-background/40 text-muted-foreground hover:bg-muted/60",
            )}
          >
            <span className="flex min-w-0 items-center gap-1">
              {filterIcon(filter.value)}
              <span className="truncate">{filter.label}</span>
            </span>
            <span className="shrink-0 tabular-nums">{counts[filter.value]}</span>
          </button>
        );
      })}
    </div>
  );
}

// ── 概念榜行：排名 + 指数微线 + 连续状态 ──

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
  const status = conceptStatus(item);
  const amount = item.main_net_inflow ?? item.accumulated_main_inflow;
  const priceChange = item.return_pct ?? item.index_change_pct;
  const activeDays = item.activity_days_20 ?? 0;
  const continuationDays = item.continuation_days ?? 0;
  const rollingCount = item.rolling_board_count ?? 0;
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "grid w-full grid-cols-[minmax(0,1fr)_78px] gap-2 rounded-md border border-transparent px-2 py-2 text-left transition-colors",
        selected
          ? "border-indigo-400/40 bg-indigo-500/10 ring-1 ring-inset ring-indigo-400/30"
          : "hover:border-border hover:bg-muted/40",
      )}
    >
      <div className="min-w-0">
        <div className="flex min-w-0 items-center gap-1.5">
          <span className="w-5 shrink-0 text-[11px] tabular-nums text-muted-foreground">{rank}</span>
          <span className={cn("min-w-0 truncate text-sm", selected ? "font-semibold text-indigo-200" : "font-medium")}>
            {item.name ?? item.sector_id}
          </span>
        </div>
        <div className="mt-1 flex min-w-0 items-center gap-1.5 pl-5 text-[10px] text-muted-foreground">
          <StatusPill status={status} compact />
          <span className="truncate">
            滚动 {rollingCount} 次 · 连续 {continuationDays} 天 · 活跃 {activeDays}/20
          </span>
        </div>
      </div>
      <div className="flex flex-col items-end justify-between">
        <span className={cn("text-xs font-semibold tabular-nums", (priceChange ?? 0) >= 0 ? "text-rise" : "text-fall")}>
          {formatPct(priceChange)}
        </span>
        <MiniIndexLine points={item.index_points} tone={(priceChange ?? 0) >= 0 ? "rise" : "fall"} />
        <span className="max-w-[78px] truncate text-[10px] tabular-nums text-muted-foreground">
          {formatAmount(amount)}
        </span>
      </div>
    </button>
  );
}

function ConceptIndexDetail({ item, date }: { item: SectorRankItem; date: string }) {
  const status = conceptStatus(item);
  const points = item.index_points ?? [];
  const lastPoint = latestDrawablePoint(points);
  const priceChange = item.index_change_pct ?? item.return_pct;
  const activityRatio = item.activity_ratio_20 == null ? "--" : `${Math.round(item.activity_ratio_20 * 100)}%`;
  const rollingAvg = item.rolling_board_avg_change_pct == null ? "--" : formatPct(item.rolling_board_avg_change_pct);
  const temporary = Boolean(lastPoint?.temporary);

  return (
    <div className="rounded-lg border bg-card p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex min-w-0 items-center gap-2">
            <h2 className="min-w-0 truncate font-display text-lg font-semibold">
              {item.name ?? item.sector_id}
            </h2>
            <StatusPill status={status} />
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <span>{item.sector_id}</span>
            <span>{date || "--"}</span>
            <span>{temporary ? "盘中临时指数点" : "历史指数缓存"}</span>
          </div>
        </div>
        <div className="text-right">
          <div className={cn("font-display text-2xl font-semibold tabular-nums", (priceChange ?? 0) >= 0 ? "text-rise" : "text-fall")}>
            {formatPct(priceChange)}
          </div>
          <div className="text-[10px] text-muted-foreground">近 20 点指数涨跌</div>
        </div>
      </div>

      <ConceptIndexChart points={points} />

      <div className="mt-3 grid grid-cols-2 gap-2 xl:grid-cols-4">
        <TapeNumber label="滚动上榜" value={`${item.rolling_board_count ?? 0} 次`} />
        <TapeNumber label="连续热度" value={`${item.continuation_days ?? 0} 天`} tone={status === "broken" ? "fall" : "rise"} />
        <TapeNumber label="20点活跃" value={`${item.activity_days_20 ?? 0}/20`} />
        <TapeNumber label="上榜均涨" value={rollingAvg} tone={(item.rolling_board_avg_change_pct ?? 0) >= 0 ? "rise" : "fall"} />
        <TapeNumber label="活跃占比" value={activityRatio} />
        <TapeNumber label="指数点位" value={lastPoint ? lastPoint.close.toFixed(2) : "--"} />
      </div>

      <div className="mt-3">
        <FundMatrix item={item} />
      </div>
    </div>
  );
}

function ConceptIndexChart({ points }: { points: SectorRankItem["index_points"] }) {
  const chart = buildChart(points, 560, 168, 10);
  if (!chart) {
    return (
      <div className="mt-3 flex h-44 items-center justify-center rounded-md border bg-background/40 text-xs text-muted-foreground">
        暂无概念指数曲线
      </div>
    );
  }

  const rising = chart.last.close >= chart.first.close;
  const stroke = rising ? "#ef4444" : "#22c55e";
  const lastCoord = chart.coords[chart.coords.length - 1];

  return (
    <div className="mt-3 rounded-md border bg-background/40 p-2">
      <div className="h-40">
        <svg className="h-full w-full" viewBox={`0 0 ${chart.width} ${chart.height}`} preserveAspectRatio="none">
          <path d={chart.areaPath} fill={stroke} opacity={0.08} />
          <path d={chart.path} fill="none" stroke={stroke} strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round" />
          <line x1={0} x2={chart.width} y1={chart.height - 10} y2={chart.height - 10} stroke="currentColor" className="text-border" strokeWidth={1} />
          {lastCoord && (
            <circle cx={lastCoord.x} cy={lastCoord.y} r={3.2} fill={stroke} stroke="hsl(var(--card))" strokeWidth={2} />
          )}
        </svg>
      </div>
      <div className="mt-1 flex items-center justify-between text-[10px] text-muted-foreground">
        <span>{chart.first.date}</span>
        <span className="tabular-nums">
          {chart.min.toFixed(2)} - {chart.max.toFixed(2)}
        </span>
        <span>{chart.last.date}</span>
      </div>
    </div>
  );
}

function MarketIndexStrip({
  data,
  loading,
  live,
  date,
}: {
  data: IndexQuote[];
  loading: boolean;
  live: boolean;
  date: string;
}) {
  return (
    <div className="rounded-lg border bg-card p-3">
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <span className="text-xs font-medium">大盘参照</span>
        <span className="text-[10px] text-muted-foreground">{date || "--"}</span>
      </div>
      {loading ? (
        <LoadingState rows={2} />
      ) : data.length > 0 ? (
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-7">
          {data.map((ix) => (
            <IndexCard key={ix.vt_symbol} ix={ix} />
          ))}
        </div>
      ) : (
        <div className="rounded-md border border-dashed bg-background/30 px-3 py-4 text-xs text-muted-foreground">
          {live ? "实时模式先按概念资金流和盘中快照判断，大盘指数收盘后进入历史回放。" : "该日暂无大盘指数缓存。"}
        </div>
      )}
    </div>
  );
}

function TapeNumber({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "rise" | "fall";
}) {
  return (
    <div className="rounded-md border bg-background/40 px-2 py-1.5">
      <div className="text-[10px] text-muted-foreground">{label}</div>
      <div className={cn("mt-0.5 font-display text-sm font-semibold tabular-nums", tone === "rise" && "text-rise", tone === "fall" && "text-fall")}>
        {value}
      </div>
    </div>
  );
}

function StatusPill({ status, compact = false }: { status: NormalizedConceptStatus; compact?: boolean }) {
  return (
    <span className={cn(
      "inline-flex shrink-0 items-center gap-1 rounded-md border px-1.5 py-0.5 font-medium",
      compact ? "text-[10px]" : "text-[11px]",
      statusClass(status),
    )}>
      {statusIcon(status)}
      <span>{statusLabel(status)}</span>
    </span>
  );
}

function MiniIndexLine({
  points,
  tone,
}: {
  points: SectorRankItem["index_points"];
  tone: "rise" | "fall";
}) {
  return (
    <div className="h-7 w-[74px]">
      <Sparkline points={points} stroke={tone === "rise" ? "#ef4444" : "#22c55e"} />
    </div>
  );
}

function Sparkline({
  points,
  stroke,
}: {
  points: SectorRankItem["index_points"];
  stroke: string;
}) {
  const chart = buildChart(points, 74, 28, 2);
  if (!chart) {
    return <div className="h-full w-full rounded-sm border border-dashed border-border/80" />;
  }
  return (
    <svg className="h-full w-full" viewBox={`0 0 ${chart.width} ${chart.height}`} preserveAspectRatio="none">
      <path d={chart.path} fill="none" stroke={stroke} strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function filterIcon(filter: ConceptTapeFilter) {
  if (filter === "maintained") return <Flame size={12} />;
  if (filter === "new") return <Sparkles size={12} />;
  if (filter === "broken") return <CircleSlash size={12} />;
  return <Activity size={12} />;
}

function statusIcon(status: NormalizedConceptStatus) {
  if (status === "maintained") return <Flame size={12} />;
  if (status === "new") return <Sparkles size={12} />;
  if (status === "broken") return <CircleSlash size={12} />;
  return <Radio size={12} />;
}

function statusLabel(status: NormalizedConceptStatus): string {
  if (status === "maintained") return "维持";
  if (status === "new") return "新起";
  if (status === "broken") return "断档";
  return "观察";
}

function statusClass(status: NormalizedConceptStatus): string {
  if (status === "maintained") return "border-rise/30 bg-rise/10 text-rise";
  if (status === "new") return "border-amber-400/35 bg-amber-400/10 text-amber-300";
  if (status === "broken") return "border-fall/30 bg-fall/10 text-fall";
  return "border-border bg-background/60 text-muted-foreground";
}

function conceptStatus(item: SectorRankItem): NormalizedConceptStatus {
  const raw = String(item.continuation_status ?? "").toLowerCase();
  if (raw === "maintained" || raw === "hot") return "maintained";
  if (raw === "new") return "new";
  if (raw === "broken" || raw === "cold") return "broken";
  return "watch";
}

function matchesTapeFilter(item: SectorRankItem, filter: ConceptTapeFilter): boolean {
  if (filter === "all") return true;
  return conceptStatus(item) === filter;
}

function conceptTapeCounts(items: SectorRankItem[]): ConceptTapeCounts {
  return items.reduce<ConceptTapeCounts>(
    (acc, item) => {
      acc.all += 1;
      const status = conceptStatus(item);
      if (status === "maintained" || status === "new" || status === "broken") {
        acc[status] += 1;
      }
      return acc;
    },
    { all: 0, maintained: 0, new: 0, broken: 0 },
  );
}

function latestDrawablePoint(points: SectorRankItem["index_points"]): DrawablePoint | null {
  const drawable = drawablePoints(points);
  return drawable[drawable.length - 1] ?? null;
}

function drawablePoints(points: SectorRankItem["index_points"]): DrawablePoint[] {
  return (points ?? [])
    .filter((point): point is NonNullable<typeof point> => Boolean(point))
    .map((point) => ({
      date: point.date,
      close: Number(point.close),
      temporary: point.temporary,
    }))
    .filter((point) => point.date && Number.isFinite(point.close));
}

function buildChart(
  points: SectorRankItem["index_points"],
  width: number,
  height: number,
  padding: number,
): ChartShape | null {
  const drawable = drawablePoints(points);
  if (drawable.length < 2) return null;

  const closes = drawable.map((point) => point.close);
  const rawMin = Math.min(...closes);
  const rawMax = Math.max(...closes);
  const span = rawMax - rawMin || 1;
  const min = rawMin - span * 0.08;
  const max = rawMax + span * 0.08;
  const xSpan = width - padding * 2;
  const ySpan = height - padding * 2;

  const coords = drawable.map((point, index) => {
    const x = padding + (xSpan * index) / (drawable.length - 1);
    const y = padding + (1 - (point.close - min) / (max - min || 1)) * ySpan;
    return { x, y, point };
  });
  const path = coords.map((coord, index) => `${index === 0 ? "M" : "L"} ${coord.x.toFixed(2)} ${coord.y.toFixed(2)}`).join(" ");
  const first = coords[0];
  const last = coords[coords.length - 1];
  const areaPath = `${path} L ${last.x.toFixed(2)} ${height - padding} L ${first.x.toFixed(2)} ${height - padding} Z`;

  return {
    width,
    height,
    path,
    areaPath,
    coords,
    first: first.point,
    last: last.point,
    min: rawMin,
    max: rawMax,
  };
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
  const netInflow = item.main_net_inflow ?? item.accumulated_main_inflow;
  const netRatio = item.main_net_inflow_ratio;
  const live = item.data_mode === "live";
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
        label={live ? "资金占比" : "放量比"}
        value={live ? formatPct(netRatio) : fmtRatio(item.volume_ratio)}
        valueClass={live ? ((netRatio ?? 0) >= 0 ? "text-rise" : "text-fall") : item.volume_ratio == null ? "" : item.volume_ratio >= 1 ? "text-indigo-300" : "text-muted-foreground"}
      />
      <Metric
        label="主力净流入"
        value={item.fund_inflow_available ? formatAmount(netInflow) : "近端无"}
        valueClass={item.fund_inflow_available ? ((netInflow ?? 0) >= 0 ? "text-rise" : "text-fall") : "text-muted-foreground"}
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

function shortDateTime(value: string | null | undefined): string {
  if (!value) return "--";
  const text = String(value);
  return text.length > 16 ? text.slice(0, 16).replace("T", " ") : text;
}
