import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchStockBars } from "@/api/stocks";
import { fetchIndexBars } from "@/api/indices";
import type { Bar } from "@/api/types";
import type { SymbolMarketLinePoint } from "@/api/quant";
import { CardSkeleton } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState } from "@/components/EmptyState";
import {
  createChart,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type MouseEventHandler,
  type MouseEventParams,
  type SeriesMarker,
  type SeriesType,
  type Time,
  ColorType,
  CrosshairMode,
} from "lightweight-charts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, formatAmount, formatPct, formatPrice, priceColorClass } from "@/lib/utils";
import { useChartColors, type ChartPalette } from "@/lib/chart-theme";
import { diagnosticForBar, type ChartBarDiagnostic } from "@/features/stocks/stockChartDiagnostics";
import { Database, Radio } from "lucide-react";

interface StockKlineChartProps {
  vtSymbol: string;
  isIndex?: boolean;
  markers?: KlineMarker[];
  marketLine?: SymbolMarketLinePoint[];
  markersLoading?: boolean;
  marketLineLoading?: boolean;
  selectedMarkerId?: string | null;
  onMarkerClick?: (marker: KlineMarker) => void;
}

export interface KlineMarker {
  id?: string;
  time: string;
  side: "BUY" | "SELL" | string;
  markerKind?: "signal" | "trade" | "rejected";
  status?: "signal" | "filled" | "rejected" | "research" | string;
  reason?: string | null;
  reasonLabel?: string | null;
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
  returnPct?: number | null;
  evidence?: Array<{ label: string; value: string; valueClass?: string }>;
  raw?: Record<string, unknown>;
}

type OverlayMode = "ma" | "boll" | "none";
type IndicatorMode = "volume" | "macd" | "kdj" | "rsi";
type MarketLinePosition = "above" | "below";
type MarketLineDirection = "rising" | "falling" | "flat";
type MarketLineAdviceTone = "positive" | "warning" | "risk" | "neutral";

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
const EMPTY_MARKET_LINE: SymbolMarketLinePoint[] = [];

interface MarketLineOverlayStatus {
  point: SymbolMarketLinePoint;
  tradeDate: string;
  lineValue: number;
  close: number;
  distancePct: number;
  slopePct: number | null;
  position: MarketLinePosition;
  direction: MarketLineDirection;
  advice: string;
  adviceTone: MarketLineAdviceTone;
}

interface MarketLineOverlayResult {
  data: LineData<Time>[];
  byDate: Map<string, MarketLineOverlayStatus>;
}

export function StockKlineChart({
  vtSymbol,
  isIndex = false,
  markers = EMPTY_MARKERS,
  marketLine = EMPTY_MARKET_LINE,
  markersLoading = false,
  marketLineLoading = false,
  selectedMarkerId,
  onMarkerClick,
}: StockKlineChartProps) {
  const [period, setPeriod] = useState("1d");
  const [overlayMode, setOverlayMode] = useState<OverlayMode>("ma");
  const [indicatorMode, setIndicatorMode] = useState<IndicatorMode>("volume");
  const [activeBar, setActiveBar] = useState<Bar | null>(null);
  const [selectedBar, setSelectedBar] = useState<Bar | null>(null);
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
  const focusedBar = selectedBar ?? activeBar ?? bars[bars.length - 1] ?? null;
  const focusedDiagnostic = useMemo(() => diagnosticForBar(bars, focusedBar), [bars, focusedBar]);
  const latestIndicators = useMemo(() => latestIndicatorValues(bars), [bars]);
  const marketLineOverlay = useMemo(() => buildMarketLineOverlay(marketLine, bars, period), [marketLine, bars, period]);
  const focusedMarketLineStatus = useMemo(
    () => marketLineStatusForBar(marketLineOverlay, focusedBar),
    [focusedBar, marketLineOverlay]
  );
  const focusedMarketLine = useMemo(
    () => focusedMarketLineStatus?.point ?? marketLinePointForBar(marketLine, focusedBar) ?? marketLine[marketLine.length - 1] ?? null,
    [focusedBar, focusedMarketLineStatus, marketLine]
  );

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
      const priceChart = createBaseChart(priceContainerRef.current, 430, period, palette, true);
      const indicatorChart = createBaseChart(indicatorContainerRef.current, 150, period, palette);
      chartsRef.current = { price: priceChart, indicator: indicatorChart };
      setActiveBar(null);
      setSelectedBar(null);

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

      if (marketLineOverlay.data.length > 0) {
        priceChart.addLineSeries({
          color: "#57534e",
          lineWidth: 2,
          priceLineVisible: false,
          lastValueVisible: false,
        }).setData(marketLineOverlay.data);
      }

      if (overlayMode === "boll") {
        priceChart.addLineSeries(lineOptions("#0f766e")).setData(bollingerData(bars, "upper", period));
        priceChart.addLineSeries(lineOptions("#64748b")).setData(bollingerData(bars, "mid", period));
        priceChart.addLineSeries(lineOptions("#0f766e")).setData(bollingerData(bars, "lower", period));
      }

      const indicatorResult = renderIndicatorChart(indicatorChart, bars, indicatorMode, period);
      syncCharts(priceChart, indicatorChart);
      applyDefaultVisibleRange(priceChart, indicatorChart, bars.length, priceContainerRef.current.clientWidth);

      // 收盘价 time→value 映射，用于副图悬停时把十字线同步回主图（定位到当日收盘高度）
      const closeByTime = new Map<string, number>();
      for (const bar of bars) {
        closeByTime.set(normalizeChartTime(chartTime(bar.trade_date, period)), bar.close);
      }

      // 双图十字线贯穿联动：syncingCrosshair 防止 setCrosshairPosition 反向触发的反馈循环
      let syncingCrosshair = false;
      priceChart.subscribeCrosshairMove((param) => {
        const bar = findBarByTime(bars, period, param.time as Time | undefined);
        setActiveBar(bar);
        if (syncingCrosshair) return;
        syncingCrosshair = true;
        syncCrosshair(param, indicatorChart, indicatorResult.mainSeries, indicatorResult.valueByTime);
        syncingCrosshair = false;
      });

      indicatorChart.subscribeCrosshairMove((param) => {
        const bar = findBarByTime(bars, period, param.time as Time | undefined);
        setActiveBar(bar);
        if (syncingCrosshair) return;
        syncingCrosshair = true;
        syncCrosshair(param, priceChart, candleSeries, closeByTime);
        syncingCrosshair = false;
      });

      const clickHandler: MouseEventHandler<Time> = (param) => {
        const marker = findMarkerFromClick(markers, period, param.hoveredObjectId, param.time as Time | undefined);
        if (marker) {
          onMarkerClick?.(marker);
        }
        const bar = findBarByTime(bars, period, param.time as Time | undefined);
        if (bar) {
          setSelectedBar(bar);
        }
      };
      priceChart.subscribeClick(clickHandler);
      const indicatorClickHandler: MouseEventHandler<Time> = (param) => {
        const bar = findBarByTime(bars, period, param.time as Time | undefined);
        if (bar) {
          setSelectedBar(bar);
        }
      };
      indicatorChart.subscribeClick(indicatorClickHandler);

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
  }, [bars, barsQuery.isLoading, indicatorMode, markers, marketLineOverlay.data, onMarkerClick, overlayMode, period, selectedMarkerId, vtSymbol, palette]);

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
        <div className="flex flex-wrap items-center gap-1.5">
          <ButtonGroup items={OVERLAYS} value={overlayMode} onChange={(value) => setOverlayMode(value as OverlayMode)} />
          <ButtonGroup items={INDICATORS} value={indicatorMode} onChange={(value) => setIndicatorMode(value as IndicatorMode)} />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span>{formatTradeTime(focusedBar?.trade_date)}</span>
        <span>开 {formatPrice(focusedBar?.open)}</span>
        <span>高 {formatPrice(focusedBar?.high)}</span>
        <span>低 {formatPrice(focusedBar?.low)}</span>
        <span className={priceColorClass(focusedDiagnostic?.changePct)}>收 {formatPrice(focusedBar?.close)}</span>
        <span>量 {formatAmount(focusedBar?.volume)}</span>
        <span>额 {formatAmount(focusedBar?.turnover)}</span>
      </div>

      <ChartAsyncStatus
        barsLoading={barsQuery.isLoading}
        markersLoading={markersLoading}
        marketLineLoading={marketLineLoading}
        markerCount={markers.length}
        hasMarketLine={marketLine.length > 0}
      />
      <MarketLineLegend point={focusedMarketLine} status={focusedMarketLineStatus} loading={marketLineLoading} />
      <OverlayLegend mode={overlayMode} values={latestIndicators} />
      {markers.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 border-t pt-2 text-xs text-muted-foreground">
          <span>买入、拒买、卖出已标注在图表上</span>
          <span>{markers.length} 个</span>
          <span>点击标记、K 线或指标柱查看细节</span>
        </div>
      )}
      {/* 价格主图与成交量副图紧贴同一容器，十字线贯穿联动（同花顺式） */}
      <div className="overflow-hidden rounded-md border">
        <div ref={priceContainerRef} className="h-[430px] w-full" />
        <div ref={indicatorContainerRef} className="h-[150px] w-full border-t" />
      </div>

      <SubIndicatorText mode={indicatorMode} values={latestIndicators} />

      {markers.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {markers.map((marker) => {
            const isSelected = selectedMarkerId && marker.id === selectedMarkerId;
            return (
              <button
                key={marker.id ?? `${marker.time}-${marker.side}-${marker.price ?? ""}`}
                type="button"
                className={cn(
                  "rounded-md border px-2 py-1 text-xs tabular-nums transition-colors hover:bg-muted",
                  isSelected && "border-primary bg-muted text-foreground",
                  !isSelected && markerToneClass(marker)
                )}
                onClick={() => onMarkerClick?.(marker)}
              >
                {marker.time.slice(0, 10)} {markerListLabel(marker)}
              </button>
            );
          })}
        </div>
      )}

      {focusedDiagnostic && (
        <BarDiagnosticPanel
          bar={focusedBar}
          diagnostic={focusedDiagnostic}
          markers={markers.filter((marker) => sameChartDay(marker.time, focusedBar?.trade_date))}
        />
      )}

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

function createBaseChart(container: HTMLDivElement, height: number, period: string, palette: ChartPalette, hideTimeAxis = false) {
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
    // minimumWidth 固定价格轴宽度，保证主图与副图绘图区宽度一致，
    // 否则两个独立 chart 的价格轴宽度不同(价格短/成交量长)会导致同一日期 x 像素错位、十字竖线分裂。
    rightPriceScale: { borderColor: palette.axis, minimumWidth: 80 },
    timeScale: {
      visible: !hideTimeAxis,
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
  const syncTo = (source: IChartApi, targets: IChartApi[]) => {
    source.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (syncing || !range) return;
      syncing = true;
      for (const target of targets) {
        target.timeScale().setVisibleLogicalRange(range);
      }
      syncing = false;
    });
  };
  priceChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
    if (syncing || !range) return;
    syncing = true;
    indicatorChart.timeScale().setVisibleLogicalRange(range);
    syncing = false;
  });
  syncTo(indicatorChart, [priceChart]);
}

/**
 * 双图十字线联动：把源图当前悬停的时间点，同步到目标图的十字线上，
 * 实现"一条竖线贯穿价格主图与成交量副图"的同花顺式体验。
 * setCrosshairPosition 可能反向触发目标图的 crosshairMove 回调，
 * 因此调用方需用 syncingCrosshair 标志位防止反馈循环（与 syncCharts 同思路）。
 */
function syncCrosshair(
  param: MouseEventParams<Time>,
  targetChart: IChartApi,
  targetSeries: ISeriesApi<SeriesType>,
  targetValueByTime: Map<string, number>
) {
  if (!param.time) {
    targetChart.clearCrosshairPosition();
    return;
  }
  const value = targetValueByTime.get(normalizeChartTime(param.time));
  if (value == null || !Number.isFinite(value)) {
    targetChart.clearCrosshairPosition();
    return;
  }
  targetChart.setCrosshairPosition(value, param.time, targetSeries);
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

type IndicatorRenderResult = {
  mainSeries: ISeriesApi<SeriesType>;
  valueByTime: Map<string, number>;
};

function renderIndicatorChart(chart: IChartApi, bars: Bar[], mode: IndicatorMode, period: string): IndicatorRenderResult {
  if (mode === "volume") {
    const hist = chart.addHistogramSeries({ priceFormat: { type: "volume" } });
    hist.setData(
      bars.map((bar) => ({
        time: chartTime(bar.trade_date, period),
        value: bar.volume,
        color: bar.close >= bar.open ? "rgba(239,68,68,0.42)" : "rgba(34,197,94,0.42)",
      }))
    );
    chart.addLineSeries(lineOptions("#f59e0b")).setData(movingAverageData(bars, 5, "volume", period));
    chart.addLineSeries(lineOptions("#2563eb")).setData(movingAverageData(bars, 10, "volume", period));
    const valueByTime = new Map<string, number>();
    for (const bar of bars) {
      valueByTime.set(normalizeChartTime(chartTime(bar.trade_date, period)), bar.volume);
    }
    return { mainSeries: hist, valueByTime };
  }

  if (mode === "macd") {
    const macd = macdData(bars, period);
    const hist = chart.addHistogramSeries();
    hist.setData(macd.histogram);
    chart.addLineSeries(lineOptions("#f59e0b")).setData(macd.dif);
    chart.addLineSeries(lineOptions("#2563eb")).setData(macd.dea);
    const valueByTime = new Map(macd.histogram.map((point) => [normalizeChartTime(point.time), point.value]));
    return { mainSeries: hist, valueByTime };
  }

  if (mode === "kdj") {
    const kdj = kdjData(bars, period);
    chart.addLineSeries(lineOptions("#f59e0b")).setData(kdj.k);
    chart.addLineSeries(lineOptions("#2563eb")).setData(kdj.d);
    const jSeries = chart.addLineSeries(lineOptions("#dc2626"));
    jSeries.setData(kdj.j);
    const valueByTime = new Map(kdj.j.map((point) => [normalizeChartTime(point.time), point.value]));
    return { mainSeries: jSeries, valueByTime };
  }

  const rsi = rsiData(bars, period);
  const rsi6Series = chart.addLineSeries(lineOptions("#f59e0b"));
  rsi6Series.setData(rsi.rsi6);
  chart.addLineSeries(lineOptions("#2563eb")).setData(rsi.rsi12);
  chart.addLineSeries(lineOptions("#7c3aed")).setData(rsi.rsi24);
  const valueByTime = new Map(rsi.rsi6.map((point) => [normalizeChartTime(point.time), point.value]));
  return { mainSeries: rsi6Series, valueByTime };
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
      const isSelected = selectedMarkerId && marker.id === selectedMarkerId;
      const style = markerChartStyle(marker);
      return {
        id: marker.id,
        time: chartTime(marker.time, period),
        position: style.position,
        color: isSelected ? "#111827" : style.color,
        shape: style.shape,
        text: isSelected ? `已选${style.text}` : style.text,
      };
    });
}

function markerChartStyle(marker: KlineMarker): {
  position: "aboveBar" | "belowBar" | "inBar";
  color: string;
  shape: "circle" | "square" | "arrowUp" | "arrowDown";
  text: string;
} {
  if (marker.status === "research") {
    return { position: "belowBar", color: "#2563eb", shape: "circle", text: "研究" };
  }
  if (marker.markerKind === "signal" || marker.status === "signal") {
    return { position: "belowBar", color: "#ef4444", shape: "circle", text: "买入" };
  }
  if (marker.markerKind === "rejected" || marker.status === "rejected") {
    return { position: "belowBar", color: "#d97706", shape: "square", text: "拒买" };
  }
  if (String(marker.side).toUpperCase() === "BUY") {
    return { position: "belowBar", color: "#ef4444", shape: "arrowUp", text: "买入" };
  }
  return { position: "aboveBar", color: "#16a34a", shape: "arrowDown", text: "卖出" };
}

function markerListLabel(marker: KlineMarker) {
  const label = marker.text || marker.title || markerChartStyle(marker).text;
  const price = marker.price == null ? "" : ` ${formatPrice(marker.price)}`;
  const returnText = marker.returnPct == null ? "" : ` ${formatPct(marker.returnPct)}`;
  return `${label}${price}${returnText}`;
}

function markerToneClass(marker: KlineMarker) {
  if (marker.status === "research") return "border-blue-200 text-blue-700 dark:border-blue-500/30 dark:text-blue-300";
  if (marker.markerKind === "signal" || marker.status === "signal") return "border-blue-200 text-blue-700 dark:border-blue-500/30 dark:text-blue-300";
  if (marker.markerKind === "rejected" || marker.status === "rejected") return "border-amber-200 text-amber-700 dark:border-amber-500/30 dark:text-amber-300";
  return String(marker.side).toUpperCase() === "BUY" ? "text-rise" : "text-fall";
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

function buildMarketLineOverlay(items: SymbolMarketLinePoint[], bars: Bar[], period: string): MarketLineOverlayResult {
  const empty = { data: [], byDate: new Map<string, MarketLineOverlayStatus>() };
  if (!items.length || !bars.length || period !== "1d") return empty;

  const pointByDate = new Map(
    items
      .filter((item) => item.trade_date)
      .map((item) => [item.trade_date.slice(0, 10), item])
  );
  const closes = bars.map((bar) => bar.close);
  const ema20 = ema(closes, 20);
  const ma5 = movingAverageValues(closes, 5);
  const ma10 = movingAverageValues(closes, 10);
  const rows: Array<{
    bar: Bar;
    point: SymbolMarketLinePoint;
    lineValue: number;
  }> = [];
  let previousLine: number | null = null;

  for (let index = 0; index < bars.length; index += 1) {
    const bar = bars[index];
    const tradeDate = bar.trade_date.slice(0, 10);
    const point = pointByDate.get(tradeDate);
    if (!point) continue;

    const base = ema20[index] ?? bar.close;
    const target = marketLineTargetValue(point, base, trailingVolatilityPct(bars, index));
    const nextLine = previousLine == null ? target : previousLine * 0.58 + target * 0.42;
    const smoothedLine = Number.isFinite(nextLine) ? nextLine : target;
    const riskFloor = retreatRiskFloor(point, bar, ma5[index], ma10[index]);
    const lineValue: number = riskFloor == null ? smoothedLine : Math.max(smoothedLine, riskFloor);
    previousLine = lineValue;
    rows.push({ bar, point, lineValue });
  }

  const data: LineData<Time>[] = [];
  const byDate = new Map<string, MarketLineOverlayStatus>();
  for (let index = 0; index < rows.length; index += 1) {
    const row = rows[index];
    const tradeDate = row.bar.trade_date.slice(0, 10);
    const slopeBase = rows[Math.max(0, index - 5)];
    const slopePct =
      slopeBase && slopeBase !== row && slopeBase.lineValue > 0
        ? ((row.lineValue - slopeBase.lineValue) / slopeBase.lineValue) * 100
        : null;
    const previousPoint = rows[Math.max(0, index - 1)]?.point ?? null;
    const direction = marketLineDirection(row.point, slopePct, previousPoint);
    const distancePct = ((row.bar.close - row.lineValue) / row.lineValue) * 100;
    const position: MarketLinePosition = row.bar.close >= row.lineValue ? "above" : "below";
    const advice = marketLineAdvice(row.point, position, direction);

    data.push({
      time: chartTime(row.bar.trade_date, period),
      value: row.lineValue,
      color: marketLinePointColor(row.point),
    });
    byDate.set(tradeDate, {
      point: row.point,
      tradeDate,
      lineValue: row.lineValue,
      close: row.bar.close,
      distancePct,
      slopePct,
      position,
      direction,
      advice: advice.text,
      adviceTone: advice.tone,
    });
  }

  return { data, byDate };
}

function normalizedMarketLineScore(point: SymbolMarketLinePoint) {
  const score = typeof point.score === "number" && Number.isFinite(point.score)
    ? point.score
    : point.state === "bull" ? 76
      : point.state === "warming" ? 62
        : point.state === "bear" ? 24
          : 48;
  return Math.max(0.12, Math.min(0.9, score / 100));
}

function trailingVolatilityPct(bars: Bar[], index: number) {
  const start = Math.max(0, index - 19);
  const window = bars.slice(start, index + 1);
  if (window.length === 0) return 0.025;
  const averageRangePct =
    window.reduce((sum, bar) => {
      const close = Math.max(Math.abs(bar.close), 0.01);
      return sum + Math.max(bar.high - bar.low, 0) / close;
    }, 0) / window.length;
  return clamp(averageRangePct, 0.012, 0.07);
}

function movingAverageValues(values: number[], window: number): Array<number | null> {
  return values.map((_, index) => {
    if (index + 1 < window) return null;
    const slice = values.slice(index - window + 1, index + 1);
    return slice.reduce((sum, value) => sum + value, 0) / window;
  });
}

function marketLineTargetValue(point: SymbolMarketLinePoint, base: number, volatilityPct: number) {
  const score = normalizedMarketLineScore(point) * 100;
  const scorePressurePct = ((50 - score) / 50) * volatilityPct * 1.15;
  const phasePressurePct = marketLinePhasePressure(point) * volatilityPct;
  const maxOffset = Math.max(volatilityPct * 1.8, 0.025);
  const offsetPct = clamp(scorePressurePct + phasePressurePct, -maxOffset, maxOffset);
  return base * (1 + offsetPct);
}

function marketLinePhasePressure(point: SymbolMarketLinePoint) {
  const phase = String(point.phase || point.state || "");
  if (phase === "uptrend" || phase === "bull") return -0.35;
  if (phase === "warming") return -0.16;
  if (phase === "retreat" || phase === "bear") return 0.38;
  if (phase === "rotation" || phase === "range") return 0.06;
  return 0;
}

function retreatRiskFloor(point: SymbolMarketLinePoint, bar: Bar, ma5: number | null, ma10: number | null) {
  if (!isRetreatMarketLine(point)) return null;
  const closeBelowMa5 = ma5 != null && bar.close < ma5;
  const closeLocation = bar.high > bar.low ? (bar.close - bar.low) / (bar.high - bar.low) : 0.5;
  const intradayReturnPct = bar.open > 0 ? ((bar.close - bar.open) / bar.open) * 100 : 0;
  const bearishLowClose = intradayReturnPct <= -3 && closeLocation <= 0.25;
  if (!closeBelowMa5 && !bearishLowClose) return null;

  const candidates = [ma5];
  if (ma10 != null && (bar.close < ma10 || bearishLowClose || marketLineScoreValue(point) <= 32)) {
    candidates.push(ma10);
  }
  const valid = candidates.filter((value): value is number => value != null && Number.isFinite(value));
  if (valid.length === 0) return null;
  return Math.max(...valid);
}

function marketLineDirection(
  point: SymbolMarketLinePoint,
  slopePct: number | null,
  previousPoint: SymbolMarketLinePoint | null
): MarketLineDirection {
  if (isRetreatMarketLine(point)) return "falling";
  const phase = String(point.phase || point.state || "");
  if (phase === "warming") return "rising";
  if (phase === "uptrend" || phase === "bull") return "rising";

  const score = marketLineScoreValue(point);
  const previousScore = previousPoint ? marketLineScoreValue(previousPoint) : null;
  if (previousScore != null) {
    if (score - previousScore >= 5) return "rising";
    if (score - previousScore <= -5) return "falling";
  }
  if (slopePct == null) return "flat";
  if (slopePct >= 0.35) return "rising";
  if (slopePct <= -0.35) return "falling";
  return "flat";
}

function isRetreatMarketLine(point: SymbolMarketLinePoint) {
  const phase = String(point.phase || point.state || "");
  return phase === "retreat" || phase === "bear";
}

function marketLineScoreValue(point: SymbolMarketLinePoint) {
  if (typeof point.score === "number" && Number.isFinite(point.score)) return point.score;
  return normalizedMarketLineScore(point) * 100;
}

function marketLineAdvice(
  point: SymbolMarketLinePoint,
  position: MarketLinePosition,
  direction: MarketLineDirection
): { text: string; tone: MarketLineAdviceTone } {
  const phase = String(point.phase || point.state || "");
  const isWeakPhase = phase === "retreat" || phase === "bear";
  const isRecoveryPhase = phase === "warming";
  const isStrongPhase = phase === "uptrend" || phase === "bull";

  if (position === "below" && direction === "falling") {
    return { text: isWeakPhase ? "空仓优先" : "防守观望", tone: "risk" };
  }
  if (position === "below" && direction === "rising") {
    return { text: isRecoveryPhase ? "观察修复" : "等站回线", tone: "warning" };
  }
  if (position === "below") {
    return { text: "等站回线", tone: "warning" };
  }
  if (direction === "rising") {
    return { text: isStrongPhase || isRecoveryPhase ? "顺势关注" : "可观察", tone: "positive" };
  }
  if (direction === "falling") {
    return { text: "谨慎防回落", tone: "warning" };
  }
  return { text: "可观察", tone: "neutral" };
}

function marketLinePointColor(point: SymbolMarketLinePoint) {
  if (point.state === "bull") return "#ef4444";
  if (point.state === "bear") return "#16a34a";
  if (point.state === "warming") return "#d97706";
  if (point.state === "range") return "#64748b";
  return "#57534e";
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

function ChartAsyncStatus({
  barsLoading,
  markersLoading,
  marketLineLoading,
  markerCount,
  hasMarketLine,
}: {
  barsLoading: boolean;
  markersLoading: boolean;
  marketLineLoading: boolean;
  markerCount: number;
  hasMarketLine: boolean;
}) {
  if (!barsLoading && !markersLoading && !marketLineLoading && markerCount === 0 && !hasMarketLine) {
    return null;
  }
  const items = [
    {
      label: "K线",
      state: barsLoading ? "加载中" : "已加载",
      loading: barsLoading,
      done: !barsLoading,
    },
    {
      label: "买卖点",
      state: markersLoading ? "生成中" : markerCount > 0 ? `${markerCount} 个` : "暂无",
      loading: markersLoading,
      done: !markersLoading && markerCount > 0,
    },
    {
      label: "牛熊线",
      state: marketLineLoading ? "计算中" : hasMarketLine ? "已加载" : "暂无",
      loading: marketLineLoading,
      done: !marketLineLoading && hasMarketLine,
    },
  ];

  return (
    <div className="flex min-h-7 flex-wrap items-center gap-2 rounded-md border bg-muted/20 px-2 py-1.5 text-xs text-muted-foreground">
      {items.map((item) => (
        <span key={item.label} className="inline-flex items-center gap-1.5">
          {item.loading ? <Skeleton className="h-2 w-2 rounded-full" /> : <span className={cn("h-2 w-2 rounded-full", item.done ? "bg-rise" : "bg-muted-foreground/35")} />}
          <span>{item.label}</span>
          <span className={item.done ? "text-foreground" : undefined}>{item.state}</span>
        </span>
      ))}
    </div>
  );
}

function MarketLineLegend({
  point,
  status,
  loading,
}: {
  point: SymbolMarketLinePoint | null;
  status: MarketLineOverlayStatus | null;
  loading: boolean;
}) {
  if (loading && !point) {
    return (
      <div className="flex min-h-6 flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span>牛熊线</span>
        <Skeleton className="h-3 w-28" />
      </div>
    );
  }
  if (!point) {
    return <div className="h-6 text-xs text-muted-foreground">牛熊线 --</div>;
  }
  return (
    <div className="flex min-h-6 flex-wrap items-center gap-x-2 gap-y-1 text-xs">
      <span className={cn("font-medium", marketLineToneClass(point.state))}>牛熊线 {marketPhaseLabel(point.phase ?? point.state ?? "")}</span>
      <span className="tabular-nums text-muted-foreground">强度 {formatPrice(point.score)}</span>
      {status ? (
        <>
          <span className="tabular-nums text-muted-foreground">线价 {formatPrice(status.lineValue)}</span>
          <span className={cn("tabular-nums", priceColorClass(status.distancePct))}>
            {marketLinePositionLabel(status.position)} {formatPct(status.distancePct)}
          </span>
          <span className={marketLineDirectionToneClass(status.direction)}>{marketLineDirectionLabel(status.direction)}</span>
          <span className={marketLineAdviceToneClass(status.adviceTone)}>{status.advice}</span>
        </>
      ) : null}
      {point.label ? <span className="text-muted-foreground">{point.label}</span> : null}
    </div>
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

function BarDiagnosticPanel({
  bar,
  diagnostic,
  markers,
}: {
  bar: Bar | null;
  diagnostic: ChartBarDiagnostic;
  markers: KlineMarker[];
}) {
  if (!bar) return null;
  return (
    <div className="rounded-md border p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-sm font-medium tabular-nums">{formatTradeTime(bar.trade_date)}</div>
          <div className="mt-1 text-xs text-muted-foreground">点击 K 线或指标柱切换当日明细</div>
        </div>
        {markers.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {markers.map((marker) => (
              <Badge key={marker.id ?? `${marker.time}-${marker.side}`} variant="outline" className={cn("rounded-md", markerToneClass(marker))}>
                {markerListLabel(marker)}
              </Badge>
            ))}
          </div>
        )}
      </div>

      <div className="mt-3 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-6">
        <ChartInfoCell label="开盘" value={formatPrice(bar.open)} />
        <ChartInfoCell label="最高" value={formatPrice(bar.high)} />
        <ChartInfoCell label="最低" value={formatPrice(bar.low)} />
        <ChartInfoCell label="收盘" value={formatPrice(bar.close)} valueClass={priceColorClass(diagnostic.changePct)} />
        <ChartInfoCell label="较前收" value={`${formatPrice(diagnostic.changeAmount)} / ${formatPct(diagnostic.changePct)}`} valueClass={priceColorClass(diagnostic.changePct)} />
        <ChartInfoCell label="开盘跳空" value={formatPct(diagnostic.gapOpenPct)} valueClass={priceColorClass(diagnostic.gapOpenPct)} />
        <ChartInfoCell label="振幅" value={formatPct(diagnostic.amplitudePct)} />
        <ChartInfoCell label="实体涨跌" value={formatPct(diagnostic.intradayReturnPct)} valueClass={priceColorClass(diagnostic.intradayReturnPct)} />
        <ChartInfoCell label="成交量" value={formatAmount(bar.volume)} />
        <ChartInfoCell label="成交额" value={formatAmount(bar.turnover)} />
        <ChartInfoCell label="量比 MA5" value={formatRatio(diagnostic.volumeRatio5)} />
        <ChartInfoCell label="量比 MA20" value={formatRatio(diagnostic.volumeRatio20)} />
      </div>

      <div className="mt-3 grid gap-3 border-t pt-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
        <ChartInfoCell label="MA5 / 距离" value={`${formatPrice(diagnostic.ma5)} / ${formatPct(diagnostic.closeToMa5Pct)}`} valueClass={priceColorClass(diagnostic.closeToMa5Pct)} />
        <ChartInfoCell label="MA10 / 距离" value={`${formatPrice(diagnostic.ma10)} / ${formatPct(diagnostic.closeToMa10Pct)}`} valueClass={priceColorClass(diagnostic.closeToMa10Pct)} />
        <ChartInfoCell label="MA20 / 距离" value={`${formatPrice(diagnostic.ma20)} / ${formatPct(diagnostic.closeToMa20Pct)}`} valueClass={priceColorClass(diagnostic.closeToMa20Pct)} />
        <ChartInfoCell label="MA60 / 距离" value={`${formatPrice(diagnostic.ma60)} / ${formatPct(diagnostic.closeToMa60Pct)}`} valueClass={priceColorClass(diagnostic.closeToMa60Pct)} />
      </div>
    </div>
  );
}

function ChartInfoCell({ label, value, valueClass }: { label: string; value: string; valueClass?: string }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={cn("mt-0.5 font-medium tabular-nums", valueClass)}>{value}</div>
    </div>
  );
}

function formatRatio(value: number | null | undefined) {
  if (value == null) return "--";
  return `${value.toFixed(2)}x`;
}

function sameChartDay(left?: string | null, right?: string | null) {
  if (!left || !right) return false;
  return left.slice(0, 10) === right.slice(0, 10);
}

function marketLineStatusForBar(overlay: MarketLineOverlayResult, bar: Bar | null): MarketLineOverlayStatus | null {
  if (!bar) return null;
  return overlay.byDate.get(bar.trade_date.slice(0, 10)) ?? null;
}

function marketLinePointForBar(items: SymbolMarketLinePoint[], bar: Bar | null): SymbolMarketLinePoint | null {
  if (!bar) return null;
  return items.find((item) => sameChartDay(item.trade_date, bar.trade_date)) ?? null;
}

function marketLineToneClass(state?: string | null) {
  if (state === "bull") return "text-rise";
  if (state === "bear") return "text-fall";
  if (state === "warming") return "text-amber-700 dark:text-amber-300";
  return "text-muted-foreground";
}

function marketLinePositionLabel(position: MarketLinePosition) {
  return position === "above" ? "线上" : "线下";
}

function marketLineDirectionLabel(direction: MarketLineDirection) {
  if (direction === "rising") return "上行";
  if (direction === "falling") return "下行";
  return "走平";
}

function marketLineDirectionToneClass(direction: MarketLineDirection) {
  if (direction === "rising") return "text-rise";
  if (direction === "falling") return "text-fall";
  return "text-muted-foreground";
}

function marketLineAdviceToneClass(tone: MarketLineAdviceTone) {
  if (tone === "positive") return "font-medium text-rise";
  if (tone === "risk") return "font-medium text-fall";
  if (tone === "warning") return "font-medium text-amber-700 dark:text-amber-300";
  return "font-medium text-muted-foreground";
}

function marketPhaseLabel(phase: string) {
  const labels: Record<string, string> = {
    uptrend: "主升",
    warming: "回暖",
    rotation: "震荡",
    retreat: "退潮",
  };
  return labels[phase] ?? phase;
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

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}
