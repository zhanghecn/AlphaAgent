import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchStockBars } from "@/api/stocks";
import { fetchIndexBars } from "@/api/indices";
import type { Bar } from "@/api/types";
import { CardSkeleton } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState } from "@/components/EmptyState";
import {
  createChart,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type LineData,
  type MouseEventHandler,
  type SeriesMarker,
  type Time,
  ColorType,
  CrosshairMode,
} from "lightweight-charts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn, formatAmount, formatPrice, priceColorClass } from "@/lib/utils";
import { useChartColors, type ChartPalette } from "@/lib/chart-theme";
import { Database, Radio } from "lucide-react";

interface StockKlineChartProps {
  vtSymbol: string;
  isIndex?: boolean;
  markers?: KlineMarker[];
  selectedMarkerId?: string | null;
  onMarkerClick?: (marker: KlineMarker) => void;
}

export interface KlineMarker {
  id?: string;
  time: string;
  side: "BUY" | "SELL" | string;
  price?: number | null;
  text?: string;
  title?: string;
  strategy?: string;
  signalText?: string;
  executionText?: string;
  reasonText?: string;
  executionMode?: string | null;
  tradeDate?: string;
  signalDate?: string | null;
  executeDate?: string | null;
  volume?: number | null;
  amount?: number | null;
  fee?: number | null;
  pnl?: number | null;
  evidence?: Array<{ label: string; value: string; valueClass?: string }>;
  raw?: Record<string, unknown>;
}

type OverlayMode = "ma" | "boll" | "none";
type IndicatorMode = "volume" | "macd" | "kdj" | "rsi";

const PERIODS = [
  { value: "5m", label: "5分", limit: 500 },
  { value: "15m", label: "15分", limit: 500 },
  { value: "30m", label: "30分", limit: 500 },
  { value: "60m", label: "60分", limit: 500 },
  { value: "1d", label: "日K", limit: 1800 },
  { value: "1w", label: "周K", limit: 800 },
  { value: "1mo", label: "月K", limit: 360 },
];

const OVERLAYS: { value: OverlayMode; label: string }[] = [
  { value: "ma", label: "均线" },
  { value: "boll", label: "BOLL" },
  { value: "none", label: "裸K" },
];

const INDICATORS: { value: IndicatorMode; label: string }[] = [
  { value: "volume", label: "成交量" },
  { value: "macd", label: "MACD" },
  { value: "kdj", label: "KDJ" },
  { value: "rsi", label: "RSI" },
];

const VISIBLE_BARS = 120;
const MOBILE_VISIBLE_BARS = 70;
const EMPTY_MARKERS: KlineMarker[] = [];

export function StockKlineChart({
  vtSymbol,
  isIndex = false,
  markers = EMPTY_MARKERS,
  selectedMarkerId,
  onMarkerClick,
}: StockKlineChartProps) {
  const [period, setPeriod] = useState("1d");
  const [overlayMode, setOverlayMode] = useState<OverlayMode>("ma");
  const [indicatorMode, setIndicatorMode] = useState<IndicatorMode>("volume");
  const [activeBar, setActiveBar] = useState<Bar | null>(null);
  const palette = useChartColors();
  const priceContainerRef = useRef<HTMLDivElement>(null);
  const indicatorContainerRef = useRef<HTMLDivElement>(null);
  const chartsRef = useRef<{ price: IChartApi; indicator: IChartApi } | null>(null);

  const periodConfig = PERIODS.find((item) => item.value === period) ?? PERIODS[4];
  const barsQuery = useQuery({
    queryKey: [isIndex ? "index-bars" : "stock-bars", vtSymbol, period, periodConfig.limit],
    queryFn: () =>
      isIndex
        ? fetchIndexBars(vtSymbol, period, periodConfig.limit)
        : fetchStockBars(vtSymbol, period, periodConfig.limit),
  });

  const bars = useMemo(() => barsQuery.data?.items ?? [], [barsQuery.data]);
  const latest = activeBar ?? bars[bars.length - 1] ?? null;
  const latestIndicators = useMemo(() => latestIndicatorValues(bars), [bars]);

  useEffect(() => {
    return () => {
      destroyCharts(chartsRef.current);
      chartsRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!priceContainerRef.current || !indicatorContainerRef.current || barsQuery.isLoading || bars.length === 0) {
      return;
    }

    destroyCharts(chartsRef.current);
    chartsRef.current = null;

    try {
      const priceChart = createBaseChart(priceContainerRef.current, 430, period, palette);
      const indicatorChart = createBaseChart(indicatorContainerRef.current, 150, period, palette);
      chartsRef.current = { price: priceChart, indicator: indicatorChart };
      setActiveBar(null);

      const candleSeries = priceChart.addCandlestickSeries({
        upColor: "#ef4444",
        downColor: "#22c55e",
        borderUpColor: "#ef4444",
        borderDownColor: "#22c55e",
        wickUpColor: "#ef4444",
        wickDownColor: "#22c55e",
      });
      candleSeries.setData(toCandles(bars, period));
      if (markers.length > 0) {
        candleSeries.setMarkers(toSeriesMarkers(markers, bars, period, selectedMarkerId));
      }

      if (overlayMode === "ma") {
        priceChart.addLineSeries(lineOptions("#f59e0b")).setData(movingAverageData(bars, 5, "close", period));
        priceChart.addLineSeries(lineOptions("#8b5cf6")).setData(movingAverageData(bars, 10, "close", period));
        priceChart.addLineSeries(lineOptions("#2563eb")).setData(movingAverageData(bars, 20, "close", period));
        priceChart.addLineSeries(lineOptions("#475569")).setData(movingAverageData(bars, 60, "close", period));
      }

      if (overlayMode === "boll") {
        priceChart.addLineSeries(lineOptions("#0f766e")).setData(bollingerData(bars, "upper", period));
        priceChart.addLineSeries(lineOptions("#64748b")).setData(bollingerData(bars, "mid", period));
        priceChart.addLineSeries(lineOptions("#0f766e")).setData(bollingerData(bars, "lower", period));
      }

      renderIndicatorChart(indicatorChart, bars, indicatorMode, period);
      syncCharts(priceChart, indicatorChart);
      applyDefaultVisibleRange(priceChart, indicatorChart, bars.length, priceContainerRef.current.clientWidth);

      priceChart.subscribeCrosshairMove((param) => {
        const bar = findBarByTime(bars, period, param.time as Time | undefined);
        setActiveBar(bar);
      });

      const clickHandler: MouseEventHandler<Time> = (param) => {
        const marker = findMarkerFromClick(markers, period, param.hoveredObjectId, param.time as Time | undefined);
        if (marker) {
          onMarkerClick?.(marker);
        }
      };
      priceChart.subscribeClick(clickHandler);

      const observer = new ResizeObserver((entries) => {
        for (const entry of entries) {
          priceChart.applyOptions({ width: entry.contentRect.width });
          indicatorChart.applyOptions({ width: entry.contentRect.width });
          applyDefaultVisibleRange(priceChart, indicatorChart, bars.length, entry.contentRect.width);
      }
    });
      observer.observe(priceContainerRef.current);

      return () => observer.disconnect();
    } catch (err) {
      // Graceful degradation: if chart rendering fails (e.g. NaN times),
      // destroy partial charts and let React show the data anyway.
      console.error("K-line chart render error:", err);
      destroyCharts(chartsRef.current);
      chartsRef.current = null;
    }
  }, [bars, barsQuery.isLoading, indicatorMode, markers, onMarkerClick, overlayMode, period, selectedMarkerId, vtSymbol, palette]);

  if (barsQuery.isLoading) {
    return (
      <div className="space-y-2">
        <CardSkeleton />
        <CardSkeleton />
      </div>
    );
  }

  if (barsQuery.isError) {
    return (
      <ErrorState
        message={barsQuery.error instanceof Error ? barsQuery.error.message : "K 线加载失败"}
        onRetry={() => barsQuery.refetch()}
      />
    );
  }

  if (bars.length === 0) {
    return <EmptyState message="暂无 K 线数据" description="真实行情源暂时没有返回该周期 K 线" />;
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <ButtonGroup items={PERIODS} value={period} onChange={(value) => setPeriod(value)} />
        <ButtonGroup items={OVERLAYS} value={overlayMode} onChange={(value) => setOverlayMode(value as OverlayMode)} />
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span>{formatTradeTime(latest?.trade_date)}</span>
        <span>开 {formatPrice(latest?.open)}</span>
        <span>高 {formatPrice(latest?.high)}</span>
        <span>低 {formatPrice(latest?.low)}</span>
        <span className={priceColorClass(latest?.change_pct)}>收 {formatPrice(latest?.close)}</span>
        <span>量 {formatAmount(latest?.volume)}</span>
        <span>额 {formatAmount(latest?.turnover)}</span>
      </div>

      <OverlayLegend mode={overlayMode} values={latestIndicators} />
      {markers.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 border-t pt-2 text-xs text-muted-foreground">
          <span>回测买卖点已标注在图表上</span>
          <span>{markers.length} 个</span>
          <span>点击买/卖箭头或对应 K 线查看策略说明</span>
        </div>
      )}
      <div ref={priceContainerRef} className="h-[430px] w-full" />

      {markers.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {markers.map((marker) => {
            const isSelected = selectedMarkerId && marker.id === selectedMarkerId;
            const isBuy = marker.side === "BUY";
            return (
              <button
                key={marker.id ?? `${marker.time}-${marker.side}-${marker.price ?? ""}`}
                type="button"
                className={cn(
                  "rounded-md border px-2 py-1 text-xs tabular-nums transition-colors hover:bg-muted",
                  isSelected && "border-primary bg-muted text-foreground",
                  !isSelected && (isBuy ? "text-rise" : "text-fall")
                )}
                onClick={() => onMarkerClick?.(marker)}
              >
                {marker.time.slice(0, 10)} {isBuy ? "买" : "卖"} {formatPrice(marker.price)}
              </button>
            );
          })}
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-3">
        <ButtonGroup items={INDICATORS} value={indicatorMode} onChange={(value) => setIndicatorMode(value as IndicatorMode)} />
        <SubIndicatorText mode={indicatorMode} values={latestIndicators} />
      </div>
      <div ref={indicatorContainerRef} className="h-[150px] w-full" />

      <div className="flex flex-wrap gap-1.5">
        <Badge variant="outline">真实周期: {barsQuery.data?.interval ?? period}</Badge>
        {barsQuery.data?.source && (
          <Badge variant={isLocalBars(barsQuery.data.source) ? "secondary" : "outline"} className="rounded-md gap-1">
            {isLocalBars(barsQuery.data.source) ? <Database size={13} /> : <Radio size={13} />}
            {isLocalBars(barsQuery.data.source) ? "本地历史库" : "实时历史源"}
          </Badge>
        )}
        <Badge variant="secondary">{bars.length} 根</Badge>
        <Badge variant="secondary">{formatDateRange(bars)}</Badge>
      </div>
    </div>
  );
}

function isLocalBars(source?: string) {
  return Boolean(source?.startsWith("postgresql"));
}

function createBaseChart(container: HTMLDivElement, height: number, period: string, palette: ChartPalette) {
  return createChart(container, {
    layout: {
      background: { type: ColorType.Solid, color: "transparent" },
      textColor: palette.text,
      fontSize: 12,
    },
    grid: {
      vertLines: { color: palette.grid },
      horzLines: { color: palette.grid },
    },
    width: container.clientWidth,
    height,
    crosshair: { mode: CrosshairMode.Normal },
    rightPriceScale: { borderColor: palette.axis },
    timeScale: {
      borderColor: palette.axis,
      timeVisible: period.endsWith("m"),
      secondsVisible: false,
      tickMarkFormatter: (time: Time) => formatAxisTime(time, period),
    },
    localization: {
      locale: "zh-CN",
      timeFormatter: (time: Time) => formatAxisTime(time, period),
    },
  });
}

function destroyCharts(charts: { price: IChartApi; indicator: IChartApi } | null) {
  charts?.price.remove();
  charts?.indicator.remove();
}

function syncCharts(priceChart: IChartApi, indicatorChart: IChartApi) {
  let syncing = false;
  priceChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
    if (syncing || !range) return;
    syncing = true;
    indicatorChart.timeScale().setVisibleLogicalRange(range);
    syncing = false;
  });
  indicatorChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
    if (syncing || !range) return;
    syncing = true;
    priceChart.timeScale().setVisibleLogicalRange(range);
    syncing = false;
  });
}

function applyDefaultVisibleRange(priceChart: IChartApi, indicatorChart: IChartApi, totalBars: number, width: number) {
  if (totalBars <= 0) return;
  const targetBars = width < 480 ? MOBILE_VISIBLE_BARS : VISIBLE_BARS;
  const visibleBars = Math.min(totalBars, targetBars);
  const range = {
    from: Math.max(0, totalBars - visibleBars),
    to: totalBars - 1,
  };
  priceChart.timeScale().setVisibleLogicalRange(range);
  indicatorChart.timeScale().setVisibleLogicalRange(range);
}

function renderIndicatorChart(chart: IChartApi, bars: Bar[], mode: IndicatorMode, period: string) {
  if (mode === "volume") {
    chart
      .addHistogramSeries({ priceFormat: { type: "volume" } })
      .setData(
        bars.map((bar) => ({
          time: chartTime(bar.trade_date, period),
          value: bar.volume,
          color: bar.close >= bar.open ? "rgba(239,68,68,0.42)" : "rgba(34,197,94,0.42)",
        }))
    );
    chart.addLineSeries(lineOptions("#f59e0b")).setData(movingAverageData(bars, 5, "volume", period));
    chart.addLineSeries(lineOptions("#2563eb")).setData(movingAverageData(bars, 10, "volume", period));
    return;
  }

  if (mode === "macd") {
    const macd = macdData(bars, period);
    chart.addHistogramSeries().setData(macd.histogram);
    chart.addLineSeries(lineOptions("#f59e0b")).setData(macd.dif);
    chart.addLineSeries(lineOptions("#2563eb")).setData(macd.dea);
    return;
  }

  if (mode === "kdj") {
    const kdj = kdjData(bars, period);
    chart.addLineSeries(lineOptions("#f59e0b")).setData(kdj.k);
    chart.addLineSeries(lineOptions("#2563eb")).setData(kdj.d);
    chart.addLineSeries(lineOptions("#dc2626")).setData(kdj.j);
    return;
  }

  const rsi = rsiData(bars, period);
  chart.addLineSeries(lineOptions("#f59e0b")).setData(rsi.rsi6);
  chart.addLineSeries(lineOptions("#2563eb")).setData(rsi.rsi12);
  chart.addLineSeries(lineOptions("#7c3aed")).setData(rsi.rsi24);
}

function ButtonGroup<T extends string>({
  items,
  value,
  onChange,
}: {
  items: { value: T; label: string }[];
  value: string;
  onChange: (value: T) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((item) => (
        <Button
          key={item.value}
          type="button"
          size="sm"
          variant={value === item.value ? "default" : "outline"}
          className="h-8 px-2.5 text-xs"
          onClick={() => onChange(item.value)}
        >
          {item.label}
        </Button>
      ))}
    </div>
  );
}

function toCandles(bars: Bar[], period: string): CandlestickData<Time>[] {
  return bars.map((bar) => ({
    time: chartTime(bar.trade_date, period),
    open: bar.open,
    high: bar.high,
    low: bar.low,
    close: bar.close,
  }));
}

function toSeriesMarkers(
  markers: KlineMarker[],
  bars: Bar[],
  period: string,
  selectedMarkerId?: string | null
): SeriesMarker<Time>[] {
  const barTimes = new Set(bars.map((bar) => normalizeChartTime(chartTime(bar.trade_date, period))));
  return markers
    .filter((marker) => barTimes.has(normalizeChartTime(chartTime(marker.time, period))))
    .map((marker) => {
      const isBuy = marker.side === "BUY";
      const isSelected = selectedMarkerId && marker.id === selectedMarkerId;
      return {
        id: marker.id,
        time: chartTime(marker.time, period),
        position: isBuy ? "belowBar" : "aboveBar",
        color: isSelected ? "#111827" : isBuy ? "#ef4444" : "#16a34a",
        shape: isBuy ? "arrowUp" : "arrowDown",
        text: isSelected ? marker.text || (isBuy ? "已选买" : "已选卖") : marker.text || (isBuy ? "买" : "卖"),
      };
    });
}

function findMarkerFromClick(markers: KlineMarker[], period: string, objectId: unknown, time?: Time) {
  const objectKey = typeof objectId === "string" ? objectId : objectId == null ? "" : String(objectId);
  if (objectKey) {
    const byId = markers.find((marker) => marker.id === objectKey);
    if (byId) return byId;
  }
  if (!time) return null;
  const target = normalizeChartTime(time);
  const sameTime = markers.filter((marker) => normalizeChartTime(chartTime(marker.time, period)) === target);
  if (sameTime.length === 0) return null;
  return sameTime.length === 1 ? sameTime[0] : sameTime.find((marker) => marker.side === "BUY") ?? sameTime[0];
}

function lineOptions(color: string) {
  return { color, lineWidth: 1 as const, priceLineVisible: false, lastValueVisible: false };
}

function chartTime(value: string, period: string): Time {
  if (!period.endsWith("m")) return value.slice(0, 10);
  // Minute-level: parse datetime string like "2026-06-11 14:15:00" → unix seconds
  const iso = value.includes("T") ? value : value.replace(" ", "T");
  // Ensure proper ISO-8601 with timezone so Date.parse doesn't produce NaN
  const withTz = iso.includes("+") || iso.endsWith("Z") ? iso : iso + "+08:00";
  const parsed = new Date(withTz).getTime();
  if (!Number.isFinite(parsed)) {
    // Fallback: treat as UTC midnight if time component is missing
    return value.slice(0, 10) as Time;
  }
  return Math.floor(parsed / 1000) as Time;
}

function formatAxisTime(value: Time, period: string): string {
  if (typeof value === "number") {
    const date = new Date(value * 1000);
    return period.endsWith("m")
      ? `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
      : `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  }
  if (typeof value === "string") {
    return value.length >= 10 ? value.slice(0, 10) : value;
  }
  return `${value.year}-${pad(value.month)}-${pad(value.day)}`;
}

function normalizeChartTime(value: Time): string {
  if (typeof value === "string") return value;
  if (typeof value === "number") return String(value);
  return `${value.year}-${pad(value.month)}-${pad(value.day)}`;
}

function findBarByTime(bars: Bar[], period: string, time?: Time): Bar | null {
  if (!time) return null;
  const target = normalizeChartTime(time);
  return bars.find((bar) => normalizeChartTime(chartTime(bar.trade_date, period)) === target) ?? null;
}

function movingAverageData(bars: Bar[], window: number, field: "close" | "volume", period: string): LineData<Time>[] {
  const result: LineData<Time>[] = [];
  for (let index = window - 1; index < bars.length; index += 1) {
    const slice = bars.slice(index - window + 1, index + 1);
    const value = slice.reduce((sum, bar) => sum + bar[field], 0) / window;
    result.push({ time: chartTime(bars[index].trade_date, period), value });
  }
  return result;
}

function bollingerData(bars: Bar[], band: "upper" | "mid" | "lower", period: string): LineData<Time>[] {
  const result: LineData<Time>[] = [];
  const window = 20;
  for (let index = window - 1; index < bars.length; index += 1) {
    const closes = bars.slice(index - window + 1, index + 1).map((bar) => bar.close);
    const mid = closes.reduce((sum, value) => sum + value, 0) / window;
    const variance = closes.reduce((sum, value) => sum + (value - mid) ** 2, 0) / window;
    const std = Math.sqrt(variance);
    const value = band === "upper" ? mid + 2 * std : band === "lower" ? mid - 2 * std : mid;
    result.push({ time: chartTime(bars[index].trade_date, period), value });
  }
  return result;
}

function ema(values: number[], period: number): number[] {
  if (values.length === 0) return [];
  const alpha = 2 / (period + 1);
  const result = [values[0]];
  for (let index = 1; index < values.length; index += 1) {
    result.push(values[index] * alpha + result[index - 1] * (1 - alpha));
  }
  return result;
}

function macdData(bars: Bar[], period: string) {
  const closes = bars.map((bar) => bar.close);
  const ema12 = ema(closes, 12);
  const ema26 = ema(closes, 26);
  const difValues = ema12.map((value, index) => value - ema26[index]);
  const deaValues = ema(difValues, 9);
  const dif: LineData<Time>[] = [];
  const dea: LineData<Time>[] = [];
  const histogram: HistogramData<Time>[] = [];
  for (let index = 26; index < bars.length; index += 1) {
    const time = chartTime(bars[index].trade_date, period);
    const macd = (difValues[index] - deaValues[index]) * 2;
    dif.push({ time, value: difValues[index] });
    dea.push({ time, value: deaValues[index] });
    histogram.push({
      time,
      value: macd,
      color: macd >= 0 ? "rgba(239,68,68,0.45)" : "rgba(34,197,94,0.45)",
    });
  }
  return { dif, dea, histogram };
}

function kdjData(bars: Bar[], period: string) {
  const k: LineData<Time>[] = [];
  const d: LineData<Time>[] = [];
  const j: LineData<Time>[] = [];
  let kValue = 50;
  let dValue = 50;
  for (let index = 8; index < bars.length; index += 1) {
    const window = bars.slice(index - 8, index + 1);
    const high = Math.max(...window.map((bar) => bar.high));
    const low = Math.min(...window.map((bar) => bar.low));
    const rsv = high === low ? 50 : ((bars[index].close - low) / (high - low)) * 100;
    kValue = (2 * kValue) / 3 + rsv / 3;
    dValue = (2 * dValue) / 3 + kValue / 3;
    const jValue = 3 * kValue - 2 * dValue;
    const time = chartTime(bars[index].trade_date, period);
    k.push({ time, value: kValue });
    d.push({ time, value: dValue });
    j.push({ time, value: jValue });
  }
  return { k, d, j };
}

function rsiData(bars: Bar[], period: string) {
  return {
    rsi6: rsiLineData(bars, 6, period),
    rsi12: rsiLineData(bars, 12, period),
    rsi24: rsiLineData(bars, 24, period),
  };
}

function rsiLineData(bars: Bar[], window: number, period: string): LineData<Time>[] {
  const result: LineData<Time>[] = [];
  for (let index = window; index < bars.length; index += 1) {
    const closes = bars.slice(index - window, index + 1).map((bar) => bar.close);
    const changes = closes.slice(1).map((close, closeIndex) => close - closes[closeIndex]);
    const gains = changes.map((change) => Math.max(change, 0));
    const losses = changes.map((change) => Math.abs(Math.min(change, 0)));
    const avgGain = gains.reduce((sum, value) => sum + value, 0) / window;
    const avgLoss = losses.reduce((sum, value) => sum + value, 0) / window;
    const value = avgLoss === 0 ? (avgGain > 0 ? 100 : 50) : 100 - 100 / (1 + avgGain / avgLoss);
    result.push({ time: chartTime(bars[index].trade_date, period), value });
  }
  return result;
}

function latestIndicatorValues(bars: Bar[]) {
  const latestMa = (window: number) => {
    if (bars.length < window) return null;
    return bars.slice(-window).reduce((sum, bar) => sum + bar.close, 0) / window;
  };
  const boll = latestBollinger(bars);
  const macd = latestMacd(bars);
  const kdj = latestKdj(bars);
  const rsi = latestRsi(bars);
  return {
    ma5: latestMa(5),
    ma10: latestMa(10),
    ma20: latestMa(20),
    ma60: latestMa(60),
    bollUpper: boll.upper,
    bollMid: boll.mid,
    bollLower: boll.lower,
    macd,
    kdj,
    rsi,
  };
}

function latestBollinger(bars: Bar[]) {
  if (bars.length < 20) return { upper: null, mid: null, lower: null };
  const closes = bars.slice(-20).map((bar) => bar.close);
  const mid = closes.reduce((sum, value) => sum + value, 0) / 20;
  const std = Math.sqrt(closes.reduce((sum, value) => sum + (value - mid) ** 2, 0) / 20);
  return { upper: mid + 2 * std, mid, lower: mid - 2 * std };
}

function latestMacd(bars: Bar[]) {
  const values = macdData(bars, "1d");
  return { dif: lastValue(values.dif), dea: lastValue(values.dea), macd: lastValue(values.histogram) };
}

function latestKdj(bars: Bar[]) {
  const values = kdjData(bars, "1d");
  return { k: lastValue(values.k), d: lastValue(values.d), j: lastValue(values.j) };
}

function latestRsi(bars: Bar[]) {
  const values = rsiData(bars, "1d");
  return { rsi6: lastValue(values.rsi6), rsi12: lastValue(values.rsi12), rsi24: lastValue(values.rsi24) };
}

function lastValue<T extends { value: number }>(items: T[]): number | null {
  if (items.length === 0) return null;
  return items[items.length - 1]?.value ?? null;
}

function OverlayLegend({ mode, values }: { mode: OverlayMode; values: ReturnType<typeof latestIndicatorValues> }) {
  if (mode === "none") {
    return <div className="h-6 text-xs text-muted-foreground">K 线</div>;
  }
  if (mode === "boll") {
    return (
      <div className="flex h-6 flex-wrap gap-1.5 text-xs">
        <IndicatorBadge label="BOLL上" value={values.bollUpper} className="text-teal-700 dark:text-teal-400" />
        <IndicatorBadge label="BOLL中" value={values.bollMid} />
        <IndicatorBadge label="BOLL下" value={values.bollLower} className="text-teal-700 dark:text-teal-400" />
      </div>
    );
  }
  return (
    <div className="flex h-6 flex-wrap gap-1.5 text-xs">
      <IndicatorBadge label="MA5" value={values.ma5} className="text-amber-600 dark:text-amber-400" />
      <IndicatorBadge label="MA10" value={values.ma10} className="text-violet-600 dark:text-violet-400" />
      <IndicatorBadge label="MA20" value={values.ma20} className="text-blue-600 dark:text-blue-400" />
      <IndicatorBadge label="MA60" value={values.ma60} className="text-slate-600 dark:text-slate-400" />
    </div>
  );
}

function IndicatorBadge({ label, value, className }: { label: string; value: number | null; className?: string }) {
  return (
    <span className={cn("tabular-nums", className)}>
      {label} {formatPrice(value)}
    </span>
  );
}

function SubIndicatorText({
  mode,
  values,
}: {
  mode: IndicatorMode;
  values: ReturnType<typeof latestIndicatorValues>;
}) {
  if (mode === "macd") {
    return (
      <p className="text-xs text-muted-foreground">
        DIF {formatPrice(values.macd.dif)} DEA {formatPrice(values.macd.dea)} MACD{" "}
        <span className={priceColorClass(values.macd.macd)}>{formatPrice(values.macd.macd)}</span>
      </p>
    );
  }
  if (mode === "kdj") {
    return (
      <p className="text-xs text-muted-foreground">
        K {formatPrice(values.kdj.k)} D {formatPrice(values.kdj.d)} J {formatPrice(values.kdj.j)}
      </p>
    );
  }
  if (mode === "rsi") {
    return (
      <p className="text-xs text-muted-foreground">
        RSI6 {formatPrice(values.rsi.rsi6)} RSI12 {formatPrice(values.rsi.rsi12)} RSI24{" "}
        {formatPrice(values.rsi.rsi24)}
      </p>
    );
  }
  return <p className="text-xs text-muted-foreground">成交量 MA5 / MA10</p>;
}

function formatTradeTime(value?: string) {
  if (!value) return "--";
  return value.length >= 16 ? value.slice(0, 16) : value.slice(0, 10);
}

function formatDateRange(bars: Bar[]) {
  if (bars.length === 0) return "--";
  return `${formatTradeTime(bars[0].trade_date)} 至 ${formatTradeTime(bars[bars.length - 1].trade_date)}`;
}

function pad(value: number) {
  return String(value).padStart(2, "0");
}
