import { useEffect, useRef } from "react";
import {
  createChart,
  ColorType,
  CrosshairMode,
  type IChartApi,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";
import { type TimingChart as TimingChartData, type TimingSignal } from "@/api/marketTiming";
import { useChartColors } from "@/lib/chart-theme";
import { Card } from "@/components/ui/card";
import { GOLD, SILVER } from "./TimingHero";

function buildMarkers(signals: TimingSignal[]): SeriesMarker<Time>[] {
  // lightweight-charts 要求 markers 按 time 升序; detect_events 已升序
  // v4 按 status 区分显示(保留金/银方向色相, 用透明度+后缀表达状态):
  //   CONFIRMED  - 实色金/银箭头(已确认信号)
  //   INVALIDATED - 褪色方向色 + ✗(假突破否决, 一眼看出"被否决的金/银")
  //   PENDING    - 略褪色方向色 + ?(序列末端待确认候选)
  return signals.map((s) => {
    const isGold = s.direction === "GOLD";
    const baseColor = isGold ? GOLD : SILVER;
    const invalidated = s.status === "INVALIDATED";
    const pending = s.status === "PENDING";
    const color = invalidated
      ? `${baseColor}66` // 0.4 褪色: 被否决, 保留金/银色相 + ✗
      : pending
        ? `${baseColor}B3` // 0.7 褪色: 待确认 + ?
        : baseColor;
    const text = invalidated
      ? `${isGold ? "金" : "银"}✗`
      : pending
        ? `${isGold ? "金" : "银"}?`
        : isGold
          ? "金"
          : "银";
    return {
      time: s.date as Time,
      position: isGold ? "belowBar" : "aboveBar",
      color,
      shape: isGold ? "arrowUp" : "arrowDown",
      text,
      size: invalidated ? 1 : 2,
    };
  });
}

export function TimingChart({
  chart,
  loading,
}: {
  chart: TimingChartData | null;
  loading: boolean;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const palette = useChartColors();

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
      timeScale: { borderColor: palette.axis, barSpacing: 6 },
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
    const markers = buildMarkers(chart.signals);
    if (markers.length) candle.setMarkers(markers);

    c.timeScale().fitContent();

    return () => {
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
  return (
    <Card className="p-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 px-2 pt-1 text-xs text-muted-foreground">
        <span>
          {chart.index_symbol} · 上证指数日线 + 信号标记（{chart.signals.length} 个）
        </span>
        <span className="flex flex-wrap items-center gap-3">
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-full bg-amber-400" /> 金手指（看多）
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-full bg-slate-500" /> 银手指（看空）
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-full bg-slate-400/50" /> 否决（假突破）
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-full bg-amber-400/50" /> 待确认
          </span>
        </span>
      </div>
      <div ref={containerRef} className="h-[420px] w-full" />
    </Card>
  );
}
