import { useEffect, useMemo, useRef, useState } from "react";
import {
  createChart,
  ColorType,
  CrosshairMode,
  type IChartApi,
  type MouseEventParams,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";
import {
  type TimingChart as TimingChartData,
  type TimingDailyState,
  type TimingDirection,
  type TimingSignal,
} from "@/api/marketTiming";
import { useChartColors } from "@/lib/chart-theme";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { GOLD, SILVER } from "./TimingHero";
import { summarizeTimingEvents, visibleChartSignals } from "./timingPresentation";
import {
  buildTimingHoverSummaries,
  formatTimingAxisTick,
  formatTimingCrosshairDate,
  timingActiveLabel,
  timingEventLabel,
  type TimingHoverSummary,
} from "./timingChartPresentation";

function buildMarkers(signals: TimingSignal[]): SeriesMarker<Time>[] {
  // lightweight-charts 要求 markers 按 time 升序; detect_events 已升序
  // 主图只显示正式和待确认事件；否决候选保留在摘要及最近日期表中。
  return signals.map((s) => {
    const isGold = s.direction === "GOLD";
    const baseColor = isGold ? GOLD : SILVER;
    const pending = s.status === "PENDING";
    const color = pending ? `${baseColor}B3` : baseColor;
    const text = pending ? `${isGold ? "金" : "银"}?` : isGold ? "金" : "银";
    return {
      time: s.date as Time,
      position: isGold ? "belowBar" : "aboveBar",
      color,
      shape: isGold ? "arrowUp" : "arrowDown",
      text,
      size: 2,
    };
  });
}

function directionClass(direction: TimingDirection | undefined): string {
  if (direction === "GOLD") return "text-amber-500";
  if (direction === "SILVER") return "text-slate-500 dark:text-slate-300";
  return "text-foreground";
}

function formatValue(value: number): string {
  return value.toFixed(2);
}

function TimingHoverStrip({ summary }: { summary: TimingHoverSummary | null }) {
  if (!summary) {
    return <div className="min-h-[52px] border-t px-2 py-2 text-xs text-muted-foreground">暂无悬停数据</div>;
  }
  const changeText = summary.changePct == null
    ? "--"
    : `${summary.changePct >= 0 ? "+" : ""}${summary.changePct.toFixed(2)}%`;
  const changeClass = summary.changePct == null
    ? "text-muted-foreground"
    : summary.changePct >= 0
      ? "text-rise"
      : "text-fall";
  return (
    <div className="min-h-[52px] border-t px-2 py-2 text-xs">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 tabular-nums">
        <span data-testid="timing-hover-date" className="font-medium text-foreground">
          {summary.date}
        </span>
        <span><span className="text-muted-foreground">开</span> {formatValue(summary.bar.open)}</span>
        <span><span className="text-muted-foreground">高</span> {formatValue(summary.bar.high)}</span>
        <span><span className="text-muted-foreground">低</span> {formatValue(summary.bar.low)}</span>
        <span><span className="text-muted-foreground">收</span> {formatValue(summary.bar.close)}</span>
        <span className={changeClass}>涨跌 {changeText}</span>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-muted-foreground">
        <span>
          手指状态{" "}
          <span
            data-testid="timing-hover-finger"
            className={cn("font-medium", directionClass(summary.activeDirection))}
          >
            {timingActiveLabel(summary.activeDirection)}
          </span>
        </span>
        <span>当日新手指 <span className="font-medium text-foreground">{timingEventLabel(summary.state?.event ?? null)}</span></span>
      </div>
    </div>
  );
}

export function TimingChart({
  chart,
  series,
  loading,
}: {
  chart: TimingChartData | null;
  series: TimingDailyState[];
  loading: boolean;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [hoveredDate, setHoveredDate] = useState<string | null>(null);
  const palette = useChartColors();
  const hoverSummaries = useMemo(
    () => buildTimingHoverSummaries(chart?.bars ?? [], series),
    [chart?.bars, series],
  );
  const latestDate = chart?.bars[chart.bars.length - 1]?.date ?? null;
  const focusedSummary = hoverSummaries.get(hoveredDate ?? latestDate ?? "") ?? null;

  useEffect(() => {
    if (!containerRef.current || !chart || chart.bars.length === 0) return;

    const c = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: palette.text,
        fontFamily: "inherit",
      },
      grid: { vertLines: { color: palette.grid }, horzLines: { color: palette.grid } },
      crosshair: { mode: CrosshairMode.Normal, vertLine: { labelBackgroundColor: palette.brand } },
      rightPriceScale: { borderColor: palette.axis },
      timeScale: {
        borderColor: palette.axis,
        barSpacing: 6,
        tickMarkFormatter: formatTimingAxisTick,
      },
      localization: {
        locale: "zh-CN",
        timeFormatter: formatTimingCrosshairDate,
      },
      autoSize: true,
    });
    chartRef.current = c;

    const candle = c.addCandlestickSeries({
      upColor: palette.rise,
      downColor: palette.fall,
      borderUpColor: palette.rise,
      borderDownColor: palette.fall,
      wickUpColor: palette.rise,
      wickDownColor: palette.fall,
    });
    candle.setData(
      chart.bars.map((b) => ({
        time: b.date as Time,
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
      })),
    );
    const markers = buildMarkers(visibleChartSignals(chart.signals));
    if (markers.length) candle.setMarkers(markers);

    const handleCrosshairMove = (param: MouseEventParams<Time>) => {
      setHoveredDate(param.time ? formatTimingCrosshairDate(param.time) : null);
    };
    c.subscribeCrosshairMove(handleCrosshairMove);
    c.timeScale().fitContent();

    return () => {
      c.unsubscribeCrosshairMove(handleCrosshairMove);
      c.remove();
      chartRef.current = null;
    };
  }, [chart, palette]);

  if (loading || !chart) {
    return (
      <Card className="flex h-[420px] items-center justify-center text-sm text-muted-foreground">
        加载 K 线…
      </Card>
    );
  }
  const summary = summarizeTimingEvents(chart.signals);
  return (
    <Card className="p-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 px-2 pt-1 text-xs text-muted-foreground">
        <span>
          {chart.index_symbol} · 上证指数日线 · 已确认 金 {summary.confirmed.gold} / 银 {summary.confirmed.silver}
          {summary.invalidated > 0 && ` · 已否决 ${summary.invalidated}`}
          {summary.pending > 0 && ` · 待确认 ${summary.pending}`}
        </span>
        <span className="flex flex-wrap items-center gap-3">
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-full bg-amber-400" /> 金手指（看多）
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-full bg-slate-500" /> 银手指（看空）
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-full bg-amber-400/50" /> 待确认
          </span>
        </span>
      </div>
      <TimingHoverStrip summary={focusedSummary} />
      <div ref={containerRef} className="h-[420px] w-full" />
    </Card>
  );
}
