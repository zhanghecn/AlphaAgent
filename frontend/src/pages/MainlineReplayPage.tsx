/**
 * MainlineReplayPage — 概念指数（量化复盘终端）
 *
 * 视觉：暗色行情磁带。Signature = 概念指数曲线 + 连续状态带。
 * 结构：时间轴 + 三栏（概念指数榜 / 指数详情 / 成分股+共振）。
 */
import { useEffect, useMemo, useRef, useState, type PointerEvent } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { Activity, CircleSlash, Flame, Radio, Sparkles } from "lucide-react";

import { LoadingState } from "@/components/LoadingState";
import { RelationPanel } from "@/features/replay/RelationPanel";
import { SectorStocksTable } from "@/features/replay/SectorStocksTable";
import { buildUnifiedDateList, pickDataSource } from "@/features/replay/unifiedTimeline";
import {
  fetchConceptSearch,
  fetchLiveMainline,
  fetchReplaySnapshot,
  fetchReplayTimeline,
  fetchSentimentCycle,
  type FlowTop,
  type FlowTopItem,
  type IndexQuote,
  type RelationItem,
  type SectorRankItem,
  type SentimentCycleData,
  type SentimentCyclePoint,
  type SentimentCycleRange,
  type SentimentCycleShadow,
} from "@/api/mainlineReplay";
import { cn, formatAmount, formatPct } from "@/lib/utils";

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
type SentimentChartShape = {
  width: number;
  height: number;
  path: string;
  areaPath: string;
  points: Array<{ x: number; y: number; point: SentimentCyclePoint }>;
  first: { x: number; y: number; point: SentimentCyclePoint };
  last: { x: number; y: number; point: SentimentCyclePoint };
  step: number;
  bandY: (score: number) => number;
};
type SentimentVersionHeatItem = {
  lookback: number;
  data?: SentimentCycleData;
  loading: boolean;
  error: boolean;
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
  const timelineDates = timelineQ.data?.dates ?? [];
  const [flowPeriod, setFlowPeriod] = useState<string>("即时");
  const [searchTerm, setSearchTerm] = useState<string>("");
  const liveQ = useQuery({
    queryKey: ["mainlineLive", flowPeriod],
    queryFn: () => fetchLiveMainline({ flow_period: flowPeriod }),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
  const liveDate = liveQ.data?.trade_date;
  // 统一时间轴：合并 live 最新日 + history 评分日，最新日期排在最前
  const dates = useMemo(
    () => buildUnifiedDateList(liveDate, timelineDates),
    [liveDate, timelineDates],
  );
  const [selectedDate, setSelectedDate] = useState<string>("");
  const [datePinnedByUser, setDatePinnedByUser] = useState<boolean>(false);
  const [sentimentLookback, setSentimentLookback] = useState<number>(20);
  useEffect(() => {
    if (dates.length === 0) return;
    if (!selectedDate || !dates.includes(selectedDate)) {
      setSelectedDate(dates[0]);
      setDatePinnedByUser(false);
      return;
    }
    if (!datePinnedByUser && selectedDate !== dates[0]) {
      setSelectedDate(dates[0]);
    }
  }, [dates, selectedDate, datePinnedByUser]);
  function handleDateChange(date: string) {
    setDatePinnedByUser(true);
    setSelectedDate(date);
  }
  // 选中日期 == liveDate 走 live 实时数据；否则走历史 snapshot
  const source = pickDataSource(selectedDate, liveDate);
  const effectiveDate = source === "live" ? (liveDate ?? selectedDate) : selectedDate;
  const relationDate =
    source === "live" ? (liveQ.data?.base_daily_date ?? selectedDate) : selectedDate;

  const snapshotQ = useQuery({
    queryKey: ["replaySnapshot", selectedDate, flowPeriod],
    queryFn: () => fetchReplaySnapshot({ date: selectedDate, flow_period: flowPeriod }),
    enabled: source === "history" && !!selectedDate,
    staleTime: 60_000,
  });
  const searchQ = useQuery({
    queryKey: ["conceptSearch", searchTerm.trim(), effectiveDate, flowPeriod],
    queryFn: () => fetchConceptSearch({ q: searchTerm.trim(), trade_date: effectiveDate, period: flowPeriod }),
    enabled: searchTerm.trim().length > 0 && !!effectiveDate,
    staleTime: 60_000,
  });
  // 情绪大周期与回放日期解耦：后端以最新完整日线为锚计算连续曲线，
  // 切换回放日期不再重取（同一日在任何窗口下数值一致，曲线不断裂）。
  const sentimentQ = useQuery({
    queryKey: ["mainlineSentimentCycle", sentimentLookback, source],
    queryFn: () => fetchSentimentCycle({
      lookback: sentimentLookback,
      include_live: source === "live",
    }),
    enabled: !!effectiveDate,
    staleTime: source === "live" ? 30_000 : 60_000,
    refetchInterval: (query) => {
      const state = query.state.data?.status;
      const cacheState = query.state.data?.cache_state;
      if (state === "building" || cacheState === "refreshing") return 3_000;
      return source === "live" ? 60_000 : false;
    },
  });

  const activeData = source === "live" ? liveQ.data : snapshotQ.data;
  const activeLoading = source === "live" ? liveQ.isLoading : snapshotQ.isLoading;
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
    const fallback = filteredRanking[0] ?? ranking[0] ?? null;
    if (!selectedSectorId) return fallback;
    return (
      ranking.find((item) => item.sector_id === selectedSectorId)
      ?? (selectedSectorOverride?.sector_id === selectedSectorId ? selectedSectorOverride : null)
      ?? fallback
    );
  }, [filteredRanking, ranking, selectedSectorId, selectedSectorOverride]);
  useEffect(() => {
    setSelectedSectorOverride(null);
  }, [effectiveDate, flowPeriod]);

  function selectRankedSector(item: SectorRankItem) {
    setSelectedSectorOverride(null);
    setSelectedSectorId(item.sector_id);
  }
  const threeColRef = useRef<HTMLDivElement>(null);
  function selectTopConcept(item: FlowTopItem) {
    setSelectedSectorOverride(flowTopItemToSectorRankItem(item));
    setSelectedSectorId(item.sector_id);
    threeColRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
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

      {/* 统一时间轴 */}
      <div className="rounded-lg border bg-card p-3">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span
              className={cn(
                "inline-block h-2 w-2 rounded-full",
                source === "live" ? "bg-emerald-400" : "bg-muted-foreground/50",
              )}
            />
            {source === "live" ? "最新主线 · 自动刷新" : "历史日期"}
          </div>
          <div className="text-xs text-muted-foreground">
            {source === "live"
              ? `${liveQ.data?.trade_date ?? "--"} · 基准日 ${liveQ.data?.base_daily_date ?? "--"}`
              : `历史 ${selectedDate || "--"}`}
          </div>
        </div>
        {dates.length === 0 ? (
          timelineQ.isLoading || liveQ.isLoading ? (
            <LoadingState rows={1} />
          ) : (
            <div className="text-sm text-muted-foreground">
              暂无回放数据。请先在 <a href="/data" className="underline">数据管理</a> 同步 sector_period_scores。
            </div>
          )
        ) : (
          <>
            <DateScrubber dates={dates} value={selectedDate} onChange={handleDateChange} />
            {source === "live" && <LiveStatus data={liveQ.data} loading={liveQ.isLoading} />}
          </>
        )}
      </div>

      <SentimentCyclePanel
        data={sentimentQ.data}
        loading={sentimentQ.isLoading}
        lookback={sentimentLookback}
        onLookbackChange={setSentimentLookback}
      />

      {/* 主题资金流条带：游资真实看的主题级聚合 */}
      <TopicFlowStrip
        flowTop={activeData?.flow_top ?? null}
        flowPeriod={flowPeriod}
        onPeriodChange={setFlowPeriod}
        searchTerm={searchTerm}
        onSearchChange={setSearchTerm}
        searchItems={searchQ.data?.items ?? null}
        isSearching={searchQ.isLoading}
        onSelect={selectTopConcept}
      />

      {/* 三栏 */}
      <div ref={threeColRef} className="grid grid-cols-1 gap-4 lg:grid-cols-[340px_minmax(0,1fr)_340px]">
        {/* 左：概念指数榜 */}
        <div className="rounded-lg border bg-card p-3">
          <div className="mb-2 flex items-baseline justify-between">
            <span className="text-xs font-medium">概念指数榜</span>
            <span className="text-[10px] text-muted-foreground">
              {source === "live" ? "按连续状态/指数涨幅排序" : "按指数走势/热度排序"}
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
                    ? source === "live" ? "今日暂无概念资金流" : "该日无概念评分"
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
          <MarketIndexStrip data={activeData?.index ?? []} loading={activeLoading} live={source === "live"} date={effectiveDate} />
        </div>

        {/* 右：成分股 + 关联 */}
        <div className="space-y-4">
          {selectedSector ? (
            <>
              <div className="rounded-lg border bg-card p-3">
                <div className="mb-2 flex items-center gap-2">
                  <span className="inline-block h-2 w-2 rounded-full bg-brand-400" />
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

function LiveStatus({
  data,
  loading,
}: {
  data?: {
    latest_minute_time?: string | null;
    realtime_updated_at?: string | null;
    snapshot_updated_at?: string | null;
    data_state?: string;
    message?: string;
  };
  loading: boolean;
}) {
  if (loading) return <LoadingState rows={1} />;
  const updatedAt = data?.realtime_updated_at ?? data?.snapshot_updated_at;
  const stateLabel = data?.data_state === "realtime"
    ? "盘中实时"
    : data?.data_state === "realtime_delayed"
      ? "实时源延迟"
      : "最近可用";
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
      <span>{stateLabel}</span>
      <span>更新于：{shortDateTime(updatedAt)}</span>
      {data?.latest_minute_time && <span>分钟：{shortDateTime(data.latest_minute_time)}</span>}
      <span className="text-brand-300">{data?.message ?? "动态计算中"}</span>
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
        <span className="font-display text-lg font-bold tabular-nums text-brand-300">{value || "--"}</span>
      </div>
      <div className="flex min-w-[200px] flex-1 items-center gap-3">
        <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground">{dates[dates.length - 1]}</span>
        <input
          type="range"
          min={0}
          max={Math.max(0, dates.length - 1)}
          value={sliderValue}
          onChange={(e) => onChange(dates[dates.length - 1 - Number(e.target.value)])}
          className="h-1 flex-1 cursor-pointer appearance-none rounded-full bg-muted accent-brand-500"
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

const SENTIMENT_LOOKBACKS = [20, 60, 120];

function SentimentCyclePanel({
  data,
  loading,
  lookback,
  onLookbackChange,
}: {
  data?: SentimentCycleData;
  loading: boolean;
  lookback: number;
  onLookbackChange: (lookback: number) => void;
}) {
  const points = data?.points ?? [];
  const building = data?.status === "building";
  const current = data?.current ?? points[points.length - 1] ?? null;
  const [hoveredDate, setHoveredDate] = useState<string | null>(null);
  const [lockedDate, setLockedDate] = useState<string | null>(null);
  const hoveredPoint = hoveredDate ? points.find((point) => point.date === hoveredDate) ?? null : null;
  const lockedPoint = lockedDate ? points.find((point) => point.date === lockedDate) ?? null : null;
  const detailPoint = hoveredPoint ?? lockedPoint ?? current;
  const detailMode = hoveredPoint ? "hover" : lockedPoint ? "locked" : "current";
  const versionQueries = useQueries({
    queries: SENTIMENT_LOOKBACKS.map((days) => ({
      queryKey: ["mainlineSentimentCycleVersionHeat", lockedDate, days, Boolean(lockedPoint?.temporary)],
      queryFn: () => fetchSentimentCycle({
        date: lockedDate ?? undefined,
        lookback: days,
        include_live: Boolean(lockedPoint?.temporary),
      }),
      enabled: Boolean(lockedDate),
      staleTime: lockedPoint?.temporary ? 30_000 : 60_000,
    })),
  });
  const versionHeat: SentimentVersionHeatItem[] = SENTIMENT_LOOKBACKS.map((days, index) => ({
    lookback: days,
    data: versionQueries[index].data,
    loading: versionQueries[index].isLoading,
    error: versionQueries[index].isError,
  }));

  useEffect(() => {
    if (!lockedDate || loading || points.length === 0) return;
    if (!points.some((point) => point.date === lockedDate)) {
      setLockedDate(null);
    }
  }, [lockedDate, loading, points]);

  return (
    <div className="rounded-lg border bg-card p-3">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium">情绪周期</span>
          {current && <PhasePill phase={current.phase} label={current.phase_label} />}
          <span className="text-[10px] text-muted-foreground">
            {data?.mode === "live" ? "实时投影 · 60s 刷新" : "历史日线"}
          </span>
        </div>
        <div className="flex rounded-md border bg-background p-0.5">
          {SENTIMENT_LOOKBACKS.map((days) => (
            <button
              key={days}
              type="button"
              onClick={() => onLookbackChange(days)}
              className={cn(
                "rounded px-2 py-0.5 text-[11px] transition-colors",
                lookback === days ? "bg-brand-500 text-ink-950" : "text-muted-foreground hover:bg-muted",
              )}
            >
              {days}日
            </button>
          ))}
        </div>
      </div>

      {loading || building ? (
        <LoadingState rows={4} />
      ) : points.length < 2 || !current ? (
        <div className="rounded-md border border-dashed bg-background/30 px-3 py-5 text-center text-xs text-muted-foreground">
          暂无情绪周期数据
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1fr)_320px]">
            <SentimentScoreChart
              points={points}
              hoveredDate={hoveredDate}
              selectedDate={lockedDate}
              onHoverPoint={(point) => setHoveredDate(point?.date ?? null)}
              onSelectPoint={(point) => setLockedDate(point.date)}
            />
            <SentimentPointDetails
              point={detailPoint}
              mode={detailMode}
              locked={Boolean(lockedPoint)}
              onClearLock={() => setLockedDate(null)}
            />
          </div>
          <SentimentVersionHeat lockedDate={lockedDate} items={versionHeat} />
          <SentimentRangeSummary ranges={data?.ranges ?? []} lookback={lookback} />
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px] text-muted-foreground">
            <span>{current.date}</span>
            <span>样本 {current.total_stocks}</span>
            {current.temporary && <span className="text-brand-300">盘中临时点</span>}
            {data?.latest_minute_time && <span>分钟 {shortDateTime(data.latest_minute_time)}</span>}
          </div>
        </>
      )}
    </div>
  );
}

function SentimentScoreChart({
  points,
  hoveredDate,
  selectedDate,
  onHoverPoint,
  onSelectPoint,
}: {
  points: SentimentCyclePoint[];
  hoveredDate: string | null;
  selectedDate: string | null;
  onHoverPoint: (point: SentimentCyclePoint | null) => void;
  onSelectPoint: (point: SentimentCyclePoint) => void;
}) {
  const frameRef = useRef<HTMLDivElement>(null);
  const chart = buildSentimentChart(points, 640, 210, 14);
  if (!chart) {
    return (
      <div className="flex h-[220px] items-center justify-center rounded-md border bg-background/40 text-xs text-muted-foreground">
        情绪点不足
      </div>
    );
  }
  const chartShape = chart;
  const current = chartShape.points[chartShape.points.length - 1];
  const rising = (current.point.score_change ?? 0) >= 0;
  const stroke = rising ? "#ef4444" : "#22c55e";
  const hoveredCoord = hoveredDate ? chartShape.points.find((item) => item.point.date === hoveredDate) ?? null : null;
  const selectedCoord = selectedDate ? chartShape.points.find((item) => item.point.date === selectedDate) ?? null : null;

  function nearestPoint(clientX: number) {
    const rect = frameRef.current?.getBoundingClientRect();
    if (!rect || rect.width <= 0) return null;
    const x = ((clientX - rect.left) / rect.width) * chartShape.width;
    return chartShape.points.reduce((nearest, item) => (
      Math.abs(item.x - x) < Math.abs(nearest.x - x) ? item : nearest
    ));
  }

  function handlePointerMove(event: PointerEvent<HTMLDivElement>) {
    const nearest = nearestPoint(event.clientX);
    if (!nearest) return;
    onHoverPoint(nearest.point);
  }

  function handlePointerDown(event: PointerEvent<HTMLDivElement>) {
    const nearest = nearestPoint(event.clientX);
    if (!nearest) return;
    onSelectPoint(nearest.point);
  }

  return (
    <div className="rounded-md border bg-background/40 p-2">
      <div
        ref={frameRef}
        className="relative h-[220px] cursor-crosshair select-none"
        onPointerMove={handlePointerMove}
        onPointerDown={handlePointerDown}
        onPointerLeave={() => onHoverPoint(null)}
      >
        <svg className="h-full w-full" viewBox={`0 0 ${chart.width} ${chart.height}`} preserveAspectRatio="none">
          <rect x="0" y="0" width={chart.width} height={chart.bandY(72)} fill="#ef4444" opacity="0.06" />
          <rect x="0" y={chart.bandY(72)} width={chart.width} height={chart.bandY(55) - chart.bandY(72)} fill="#f59e0b" opacity="0.07" />
          <rect x="0" y={chart.bandY(55)} width={chart.width} height={chart.bandY(35) - chart.bandY(55)} fill="#3b82f6" opacity="0.07" />
          <rect x="0" y={chart.bandY(35)} width={chart.width} height={chart.height - chart.bandY(35)} fill="#22c55e" opacity="0.06" />
          {[35, 55, 72].map((line) => (
            <line
              key={line}
              x1={0}
              x2={chart.width}
              y1={chart.bandY(line)}
              y2={chart.bandY(line)}
              stroke="currentColor"
              className="text-border"
              strokeDasharray="4 6"
              strokeWidth={1}
            />
          ))}
          <path d={chart.areaPath} fill={stroke} opacity={0.08} />
          <path d={chart.path} fill="none" stroke={stroke} strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round" />
          {chart.points.map((item) => (
            <rect
              key={item.point.date}
              x={item.x - chart.step / 2}
              y={chart.height - 8}
              width={Math.max(1, chart.step)}
              height={8}
              fill={phaseColor(item.point.phase)}
              opacity={item.point.temporary ? 0.95 : 0.55}
            />
          ))}
          {selectedCoord && (
            <>
              <line
                x1={selectedCoord.x}
                x2={selectedCoord.x}
                y1={10}
                y2={chart.height - 8}
                stroke="#a5b4fc"
                strokeWidth={1.2}
                strokeDasharray="3 4"
                opacity={0.9}
              />
              <circle cx={selectedCoord.x} cy={selectedCoord.y} r={4.6} fill="hsl(var(--background))" stroke="#a5b4fc" strokeWidth={2} />
            </>
          )}
          {hoveredCoord && (
            <>
              <line
                x1={hoveredCoord.x}
                x2={hoveredCoord.x}
                y1={8}
                y2={chart.height - 8}
                stroke="currentColor"
                className="text-foreground"
                strokeWidth={1}
                opacity={0.55}
              />
              <circle cx={hoveredCoord.x} cy={hoveredCoord.y} r={5} fill={stroke} stroke="hsl(var(--card))" strokeWidth={2} />
            </>
          )}
          <circle cx={current.x} cy={current.y} r={3.8} fill={stroke} stroke="hsl(var(--card))" strokeWidth={2} />
        </svg>
        {hoveredCoord && (
          <div
            className="pointer-events-none absolute z-10 min-w-[132px] rounded-md border bg-popover px-2 py-1 text-[10px] shadow-sm"
            style={{
              left: `min(max(${(hoveredCoord.x / chart.width) * 100}%, 74px), calc(100% - 74px))`,
              top: hoveredCoord.y > chart.height * 0.55
                ? `calc(${(hoveredCoord.y / chart.height) * 100}% - 58px)`
                : `calc(${(hoveredCoord.y / chart.height) * 100}% + 10px)`,
              transform: "translateX(-50%)",
            }}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium tabular-nums">{hoveredCoord.point.date}</span>
              <span className="text-muted-foreground">{hoveredCoord.point.phase_label}</span>
            </div>
            <div className="mt-0.5 tabular-nums">
              情绪 {hoveredCoord.point.score.toFixed(1)}
              <span className={cn("ml-1", (hoveredCoord.point.score_change ?? 0) >= 0 ? "text-rise" : "text-fall")}>
                {signedNumber(hoveredCoord.point.score_change)}
              </span>
            </div>
            <div className="mt-0.5 text-muted-foreground">
              涨停 {hoveredCoord.point.limit_up_count} · 跌停 {hoveredCoord.point.limit_down_count}
            </div>
          </div>
        )}
      </div>
      <div className="mt-1 flex items-center justify-between text-[10px] text-muted-foreground">
        <span>{chart.first.point.date}</span>
        <div className="flex items-center gap-2">
          <span>35 冰点</span>
          <span>55 修复</span>
          <span>72 高潮</span>
        </div>
        <span>{chart.last.point.date}</span>
      </div>
    </div>
  );
}

function SentimentPointDetails({
  point,
  mode,
  locked,
  onClearLock,
}: {
  point: SentimentCyclePoint | null;
  mode: "hover" | "locked" | "current";
  locked: boolean;
  onClearLock: () => void;
}) {
  if (!point) {
    return (
      <div className="rounded-md border border-dashed bg-background/30 px-3 py-5 text-center text-xs text-muted-foreground">
        暂无交易日明细
      </div>
    );
  }
  const modeLabel = mode === "hover" ? "鼠标所指" : mode === "locked" ? "点击锁定" : "当前最新";
  const scoreTone = point.score_change == null ? undefined : point.score_change >= 0 ? "rise" : "fall";

  return (
    <div className="rounded-md border bg-background/40 p-2.5">
      <div className="mb-2 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="font-display text-base font-semibold tabular-nums">{point.date}</span>
            <PhasePill phase={point.phase} label={point.phase_label} compact />
          </div>
          <div className="mt-0.5 text-[10px] text-muted-foreground">
            {modeLabel} · 样本 {point.total_stocks}
            {point.temporary ? " · 盘中临时点" : ""}
          </div>
        </div>
        {locked && (
          <button
            type="button"
            onClick={onClearLock}
            className="shrink-0 rounded-md border px-1.5 py-0.5 text-[10px] text-muted-foreground transition-colors hover:bg-muted"
          >
            取消锁定
          </button>
        )}
      </div>
      <div className="grid grid-cols-2 gap-2">
        <SentimentMetric label="情绪分" value={point.score.toFixed(1)} tone={scoreTone} />
        <SentimentMetric label="分数变化" value={signedNumber(point.score_change)} tone={scoreTone} />
        <SentimentMetric label="涨跌家数" value={`${point.rise_count}/${point.fall_count}`} />
        <SentimentMetric label="涨跌占比" value={`${fmtRate(point.up_ratio)}/${fmtRate(point.down_ratio)}`} />
        <SentimentMetric label="涨停/跌停" value={`${point.limit_up_count}/${point.limit_down_count}`} tone={point.limit_down_count > 20 ? "fall" : "rise"} />
        <SentimentMetric label="炸板率" value={fmtRate(point.failed_limit_up_rate)} tone={(point.failed_limit_up_rate ?? 0) >= 0.4 ? "fall" : undefined} />
        <SentimentMetric label="连板高度" value={`${point.max_limit_up_streak || 0}板`} tone={point.max_limit_up_streak >= 3 ? "rise" : undefined} />
        <SentimentMetric label="晋级率" value={`${point.promoted_limit_up_count}/${point.previous_limit_up_count} · ${fmtRate(point.promotion_rate)}`} tone={(point.promotion_rate ?? 0) >= 0.35 ? "rise" : undefined} />
      </div>
      {point.shadow && <SentimentShadowBlock shadow={point.shadow} />}
    </div>
  );
}

/** v2 影子指标：打板溢价 / 梯队晋级率 / 连板广度（观察用，不进情绪分） */
function SentimentShadowBlock({ shadow }: { shadow: SentimentCycleShadow }) {
  const premiumTone =
    shadow.prev_limit_up_avg_change == null
      ? undefined
      : shadow.prev_limit_up_avg_change >= 0
        ? "rise"
        : "fall";
  return (
    <div className="mt-2 border-t border-border/60 pt-2">
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
          v2 影子指标 · 观察中
        </span>
        <span className="text-[10px] tabular-nums text-muted-foreground">
          连板 {shadow.consecutive_limit_up_count} 家
        </span>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <SentimentMetric
          label="打板溢价"
          value={
            shadow.prev_limit_up_avg_change == null
              ? "--"
              : `${shadow.prev_limit_up_avg_change >= 0 ? "+" : ""}${shadow.prev_limit_up_avg_change.toFixed(2)}%`
          }
          tone={premiumTone}
        />
        <SentimentMetric
          label="打板赚钱面"
          value={fmtRate(shadow.prev_limit_up_rise_ratio)}
          tone={(shadow.prev_limit_up_rise_ratio ?? 0) >= 0.5 ? "rise" : "fall"}
        />
        <SentimentMetric
          label={`一进二 · 样本${shadow.tier_samples["1to2"]}`}
          value={fmtRate(shadow.promotion_1to2_rate)}
          tone={(shadow.promotion_1to2_rate ?? 0) >= 0.3 ? "rise" : undefined}
        />
        <SentimentMetric
          label={`二进三 · 样本${shadow.tier_samples["2to3"]}`}
          value={fmtRate(shadow.promotion_2to3_rate)}
          tone={(shadow.promotion_2to3_rate ?? 0) >= 0.3 ? "rise" : undefined}
        />
        <SentimentMetric
          label={`高标晋级 · 样本${shadow.tier_samples.high}`}
          value={fmtRate(shadow.promotion_high_rate)}
          tone={(shadow.promotion_high_rate ?? 0) >= 0.4 ? "rise" : undefined}
        />
      </div>
    </div>
  );
}

function SentimentVersionHeat({
  lockedDate,
  items,
}: {
  lockedDate: string | null;
  items: SentimentVersionHeatItem[];
}) {
  if (!lockedDate) {
    return (
      <div className="mt-3 rounded-md border border-dashed bg-background/30 px-3 py-2 text-[11px] text-muted-foreground">
        未锁定交易日；锁定后显示 20/60/120 日版本热度。
      </div>
    );
  }

  return (
    <div className="mt-3">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className="text-xs font-medium">版本周期热度</span>
        <span className="text-[10px] tabular-nums text-muted-foreground">{lockedDate}</span>
      </div>
      <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
        {items.map((item) => {
          const range = largestSentimentRange(item.data?.ranges ?? []);
          const latestPoint = item.data?.points ? item.data.points[item.data.points.length - 1] : null;
          const latest = item.data?.current ?? latestPoint;
          return (
            <div key={item.lookback} className="rounded-md border bg-background/40 px-2.5 py-2">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[11px] text-muted-foreground">{item.lookback}日版</span>
                {range ? (
                  <PhasePill phase={range.dominant_phase} label={range.dominant_phase_label} compact />
                ) : (
                  <span className="text-[10px] text-muted-foreground">{item.loading ? "加载中" : item.error ? "失败" : "--"}</span>
                )}
              </div>
              <div className="mt-1 flex items-end justify-between gap-2">
                <span className="font-display text-base font-semibold tabular-nums">
                  {range ? range.avg_score.toFixed(1) : "--"}
                </span>
                <span className={cn("text-[11px] tabular-nums", (range?.score_change ?? 0) >= 0 ? "text-rise" : "text-fall")}>
                  {range ? signedNumber(range.score_change) : "--"}
                </span>
              </div>
              <div className="mt-0.5 text-[10px] tabular-nums text-muted-foreground">
                {range ? `${range.start_date} - ${range.end_date}` : "无区间"}
              </div>
              <div className="mt-0.5 text-[10px] text-muted-foreground">
                {range ? `区间 ${range.min_score.toFixed(1)}-${range.max_score.toFixed(1)}` : "区间 --"}
                {latest ? ` · 当日 ${latest.score.toFixed(1)}` : ""}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function SentimentRangeSummary({ ranges, lookback }: { ranges: SentimentCycleRange[]; lookback: number }) {
  if (ranges.length === 0) return null;
  return (
    <div className="mt-3">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className="text-xs font-medium">当前版本区间</span>
        <span className="text-[10px] text-muted-foreground">{lookback}日</span>
      </div>
      <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
      {ranges.slice(0, 3).map((range) => (
        <div key={range.label} className="rounded-md border bg-background/40 px-2.5 py-2">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[11px] text-muted-foreground">{range.label}</span>
            <PhasePill phase={range.dominant_phase} label={range.dominant_phase_label} compact />
          </div>
          <div className="mt-1 flex items-end justify-between gap-2">
            <span className="font-display text-base font-semibold tabular-nums">{range.avg_score.toFixed(1)}</span>
            <span className={cn("text-[11px] tabular-nums", (range.score_change ?? 0) >= 0 ? "text-rise" : "text-fall")}>
              {signedNumber(range.score_change)}
            </span>
          </div>
          <div className="mt-0.5 text-[10px] text-muted-foreground">
            {range.min_score.toFixed(1)} - {range.max_score.toFixed(1)}
          </div>
        </div>
      ))}
      </div>
    </div>
  );
}

function largestSentimentRange(ranges: SentimentCycleRange[]): SentimentCycleRange | null {
  if (ranges.length === 0) return null;
  return ranges.reduce((largest, range) => (range.days > largest.days ? range : largest), ranges[0]);
}

function SentimentMetric({
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

function PhasePill({ phase, label, compact = false }: { phase: string; label: string; compact?: boolean }) {
  return (
    <span className={cn(
      "inline-flex shrink-0 items-center rounded-md border px-1.5 py-0.5 font-medium",
      compact ? "text-[10px]" : "text-[11px]",
      phaseClass(phase),
    )}>
      {label}
    </span>
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
                ? "border-brand-400/50 bg-brand-500/15 text-brand-200"
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
          ? "border-brand-400/40 bg-brand-500/10 ring-1 ring-inset ring-brand-400/30"
          : "hover:border-border hover:bg-muted/40",
      )}
    >
      <div className="min-w-0">
        <div className="flex min-w-0 items-center gap-1.5">
          <span className="w-5 shrink-0 text-[11px] tabular-nums text-muted-foreground">{rank}</span>
          <span className={cn("min-w-0 truncate text-sm", selected ? "font-semibold text-brand-200" : "font-medium")}>
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

function flowTopItemToSectorRankItem(item: FlowTopItem): SectorRankItem {
  return {
    ...item,
    main_net_inflow: item.main_net_inflow ?? item.net_inflow,
    accumulated_main_inflow: item.accumulated_main_inflow ?? item.net_inflow,
    fund_inflow_available: item.fund_inflow_available ?? item.net_inflow != null,
  };
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
      <Metric label="热度分" value={fmt1(item.heat_score)} bar={item.heat_score} barColor="bg-brand-500" />
      <Metric label="资金分" value={fmt1(item.fund_score)} bar={item.fund_score} barColor="bg-brand-500" />
      <Metric label="趋势" value={item.trend_state ?? "--"} valueClass={trendColor} />
      <Metric
        label="收益率"
        value={formatPct(item.return_pct)}
        valueClass={(item.return_pct ?? 0) >= 0 ? "text-rise" : "text-fall"}
      />
      <Metric
        label={live ? "资金占比" : "放量比"}
        value={live ? formatPct(netRatio) : fmtRatio(item.volume_ratio)}
        valueClass={live ? ((netRatio ?? 0) >= 0 ? "text-rise" : "text-fall") : item.volume_ratio == null ? "" : item.volume_ratio >= 1 ? "text-brand-300" : "text-muted-foreground"}
      />
      <Metric
        label="主力净流入"
        value={item.fund_inflow_available ? formatAmount(netInflow) : "近端无"}
        valueClass={item.fund_inflow_available ? ((netInflow ?? 0) >= 0 ? "text-rise" : "text-fall") : "text-muted-foreground"}
      />
    </div>
  );
}

const FLOW_PERIODS: Array<{ value: string; label: string }> = [
  { value: "即时", label: "今日" },
  { value: "3日", label: "3日" },
  { value: "5日", label: "5日" },
  { value: "10日", label: "10日" },
  { value: "20日", label: "20日" },
];

function TopicFlowStrip({
  flowTop,
  flowPeriod,
  onPeriodChange,
  searchTerm,
  onSearchChange,
  searchItems,
  isSearching,
  onSelect,
}: {
  flowTop: FlowTop | null;
  flowPeriod: string;
  onPeriodChange: (p: string) => void;
  searchTerm: string;
  onSearchChange: (q: string) => void;
  searchItems: FlowTopItem[] | null;
  isSearching: boolean;
  onSelect: (item: FlowTopItem) => void;
}) {
  const showingSearch = searchTerm.trim().length > 0;
  const actualDays = flowTop?.actual_days;
  const periodLabel = FLOW_PERIODS.find((p) => p.value === flowPeriod)?.label ?? flowPeriod;
  return (
    <div className="rounded-lg border bg-card p-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-baseline gap-2">
          <span className="text-xs font-medium">概念资金流</span>
          <span className="text-[10px] text-muted-foreground">按主力净流入排序</span>
        </div>
        <div className="flex rounded-md border bg-background p-0.5">
          {FLOW_PERIODS.map((p) => (
            <button
              key={p.value}
              type="button"
              onClick={() => onPeriodChange(p.value)}
              className={cn(
                "rounded px-2 py-0.5 text-[11px] transition-colors",
                flowPeriod === p.value ? "bg-brand-500 text-ink-950" : "text-muted-foreground hover:bg-muted",
              )}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>
      <div className="mb-2">
        <input
          type="text"
          value={searchTerm}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="搜概念名定位（CPO / PCB / 半导体 ...），点击看成分股"
          className="w-full rounded-md border bg-background px-2 py-1 text-xs outline-none focus:border-brand-400"
        />
      </div>
      {!showingSearch && actualDays != null && actualDays > 0 && actualDays < 20 && flowPeriod === "20日" && (
        <div className="mb-1 text-[10px] text-amber-400">⚠ 即时资金流只保留近 {actualDays} 日，20日为累加近似</div>
      )}
      {showingSearch ? (
        <SearchResultColumn items={searchItems ?? []} isSearching={isSearching} onSelect={onSelect} />
      ) : !flowTop || (flowTop.inflows.length === 0 && flowTop.outflows.length === 0) ? (
        <div className="py-2 text-center text-[11px] text-muted-foreground">{periodLabel}暂无资金流数据</div>
      ) : (
        <div className="grid grid-cols-1 gap-x-6 gap-y-2 md:grid-cols-2">
          <ConceptFlowColumn title="流入" items={flowTop.inflows} tone="rise" onSelect={onSelect} />
          <ConceptFlowColumn title="流出" items={flowTop.outflows} tone="fall" onSelect={onSelect} />
        </div>
      )}
    </div>
  );
}

function SearchResultColumn({
  items,
  isSearching,
  onSelect,
}: {
  items: FlowTopItem[];
  isSearching: boolean;
  onSelect: (item: FlowTopItem) => void;
}) {
  if (isSearching && items.length === 0) {
    return <div className="py-2 text-center text-[11px] text-muted-foreground">搜索中...</div>;
  }
  if (items.length === 0) {
    return <div className="py-2 text-center text-[11px] text-muted-foreground">无匹配概念</div>;
  }
  return (
    <div>
      <div className="mb-1 text-[11px] text-muted-foreground">匹配 {items.length} 个概念 · 点击看成分股</div>
      <div>
        {items.map((it, i) => (
          <button
            key={it.sector_id}
            type="button"
            onClick={() => onSelect(it)}
            className="flex w-full items-center justify-between rounded px-1.5 py-0.5 text-left text-xs transition-colors hover:bg-brand-500/10"
          >
            <span className="flex min-w-0 items-center gap-1.5">
              <span className="w-4 shrink-0 text-[10px] tabular-nums text-muted-foreground">{i + 1}</span>
              <span className="truncate">{it.name}</span>
            </span>
            <span className={cn("ml-2 shrink-0 font-medium tabular-nums", it.net_inflow >= 0 ? "text-rise" : "text-fall")}>
              {formatAmount(it.net_inflow)}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

function ConceptFlowColumn({
  title,
  items,
  tone,
  onSelect,
}: {
  title: string;
  items: FlowTopItem[];
  tone: "rise" | "fall";
  onSelect: (item: FlowTopItem) => void;
}) {
  return (
    <div>
      <div className={cn("mb-1 text-[11px] font-medium", tone === "rise" ? "text-rise" : "text-fall")}>
        {title} TOP{items.length || ""}
      </div>
      <div>
        {items.map((it, i) => (
          <button
            key={it.sector_id}
            type="button"
            onClick={() => onSelect(it)}
            className="flex w-full items-center justify-between rounded px-1.5 py-0.5 text-left text-xs transition-colors hover:bg-brand-500/10"
          >
            <span className="flex min-w-0 items-center gap-1.5">
              <span className="w-4 shrink-0 text-[10px] tabular-nums text-muted-foreground">{i + 1}</span>
              <span className="truncate">{it.name}</span>
            </span>
            <span className={cn("ml-2 shrink-0 font-medium tabular-nums", tone === "rise" ? "text-rise" : "text-fall")}>
              {formatAmount(it.net_inflow)}
            </span>
          </button>
        ))}
        {items.length === 0 && <div className="px-1.5 py-0.5 text-[11px] text-muted-foreground">无</div>}
      </div>
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

function buildSentimentChart(
  points: SentimentCyclePoint[],
  width: number,
  height: number,
  padding: number,
): SentimentChartShape | null {
  const drawable = points
    .filter((point) => point.date && Number.isFinite(point.score))
    .slice(-180);
  if (drawable.length < 2) return null;
  const xSpan = width - padding * 2;
  const ySpan = height - padding * 2;
  const bandY = (score: number) => padding + (1 - Math.min(100, Math.max(0, score)) / 100) * ySpan;
  const coords = drawable.map((point, index) => {
    const x = padding + (xSpan * index) / (drawable.length - 1);
    const y = bandY(point.score);
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
    points: coords,
    first,
    last,
    step: xSpan / Math.max(1, drawable.length - 1),
    bandY,
  };
}

function phaseClass(phase: string): string {
  if (phase === "climax") return "border-rise/35 bg-rise/10 text-rise";
  if (phase === "divergence") return "border-amber-400/35 bg-amber-400/10 text-amber-300";
  if (phase === "repair") return "border-brand-400/35 bg-brand-500/10 text-brand-200";
  if (phase === "ice") return "border-fall/35 bg-fall/10 text-fall";
  return "border-border bg-background/60 text-muted-foreground";
}

function phaseColor(phase: string): string {
  if (phase === "climax") return "#ef4444";
  if (phase === "divergence") return "#f59e0b";
  if (phase === "repair") return "#6366f1";
  if (phase === "ice") return "#22c55e";
  return "#64748b";
}

function fmtRate(v: number | null | undefined): string {
  return v == null ? "--" : `${Math.round(v * 100)}%`;
}

function signedNumber(v: number | null | undefined): string {
  if (v == null) return "--";
  return `${v > 0 ? "+" : ""}${v.toFixed(1)}`;
}

function shortDateTime(value: string | null | undefined): string {
  if (!value) return "--";
  const text = String(value);
  return text.length > 16 ? text.slice(0, 16).replace("T", " ") : text;
}
