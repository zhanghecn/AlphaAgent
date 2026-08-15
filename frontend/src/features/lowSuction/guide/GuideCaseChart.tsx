import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  createChart,
  ColorType,
  CrosshairMode,
  type CandlestickData,
  type HistogramData,
  type LineData,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";

import { fetchLocalDailyBars } from "@/api/localBars";
import { EmptyState } from "@/components/EmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import { useChartColors, RISE_COLOR, FALL_COLOR, BRAND_COLOR } from "@/lib/chart-theme";
import { cn, formatPct, priceColorClass } from "@/lib/utils";

import type { GuideCase } from "./guideContent";
import {
  buildFetchWindow,
  displayWindowRange,
  smaSeries,
} from "./guideKline";
import { usePrefersReducedMotion } from "./usePrefersReducedMotion";

/**
 * 说明书案例 K 线：daily-only 精简图表（蜡烛 + MA5/10/20/30 + 量副图）。
 * 与 StockKlineChart 刻意分家：那个组件服务详情页全周期（分钟时区/多
 * 指标/BOLL），本组件只做「底盘 → 信号 → 效果」窗口的只读演示，并把
 * 低吸规则体系需要的 MA30 补上（详情页组件没有 MA30）。
 */

/** MA 配色与 StockKlineChart 一致；MA30 为本组件新增（低吸规则就是 MA5/10/20/30 体系）。 */
const MA_SPECS = [
  { window: 5, color: "#f59e0b", label: "MA5" },
  { window: 10, color: "#8b5cf6", label: "MA10" },
  { window: 20, color: "#2563eb", label: "MA20" },
  { window: 30, color: "#0d9488", label: "MA30" },
] as const;

const MAIN_HEIGHT = 280;
const VOLUME_HEIGHT = 85;
/** 渐进绘制：首帧直接给到 40%，随后 ease-out 补完（用户明确要求动画，本组件是有界豁免点）。 */
const REVEAL_INITIAL_RATIO = 0.4;
const REVEAL_DURATION_MS = 700;

const RETURNS_STATUS_TEXT: Record<string, string> = {
  missing_exit_session: "信号日后交易日不足",
  raw_price_limit_outlier: "窗口内有除权跳变，收益不展示（raw 口径诚实边界）",
  signal_date_not_found: "信号日不在本地日线序列中",
  bars_unavailable: "本地历史库暂无该票数据",
};

interface GuideCaseChartProps {
  caseItem: GuideCase;
  /** 规则节点上的看点提示（展示在图上方）。 */
  chartHint?: string;
}

export function GuideCaseChart({ caseItem, chartHint }: GuideCaseChartProps) {
  const palette = useChartColors();
  const reducedMotion = usePrefersReducedMotion();
  const priceRef = useRef<HTMLDivElement>(null);
  const volumeRef = useRef<HTMLDivElement>(null);
  const signalLineRef = useRef<HTMLDivElement>(null);
  const [maLegend, setMaLegend] = useState<Record<number, number | null>>({});

  const window_ = useMemo(
    () => buildFetchWindow(caseItem.signalDate, caseItem.narrativeStartDate),
    [caseItem.signalDate, caseItem.narrativeStartDate],
  );
  const barsQuery = useQuery({
    queryKey: ["local-bars", caseItem.vtSymbol, window_.fetchStart, window_.fetchEnd],
    queryFn: () =>
      fetchLocalDailyBars(caseItem.vtSymbol, window_.fetchStart, window_.fetchEnd),
    staleTime: 300_000, // 历史日线一天一变
  });

  // 宽拉窄显：MA 在全量序列上计算，显示窗口在交易日索引空间切片。
  const scene = useMemo(() => {
    const bars = barsQuery.data?.items ?? [];
    if (bars.length === 0) return null;
    const range = displayWindowRange(
      bars,
      caseItem.signalDate,
      caseItem.narrativeStartDate,
    );
    if (!range) return null;
    const closes = bars.map((bar) => bar.close);
    const volumes = bars.map((bar) => bar.volume);
    return {
      bars,
      range,
      ma: MA_SPECS.map((spec) => ({
        ...spec,
        values: smaSeries(closes, spec.window),
      })),
      volumeMa5: smaSeries(volumes, 5),
      volumeMa10: smaSeries(volumes, 10),
    };
  }, [barsQuery.data, caseItem.signalDate, caseItem.narrativeStartDate]);

  useEffect(() => {
    if (!scene || !priceRef.current || !volumeRef.current) return;
    const { bars, range } = scene;
    const displayBars = bars.slice(range.start, range.end + 1);

    const priceChart = createChart(priceRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: palette.text,
        fontSize: 11,
      },
      grid: {
        vertLines: { color: palette.grid },
        horzLines: { color: palette.grid },
      },
      width: priceRef.current.clientWidth,
      height: MAIN_HEIGHT,
      crosshair: { mode: CrosshairMode.Normal },
      // minimumWidth 对齐主副图绘图区宽度，避免同一日期 x 像素错位。
      rightPriceScale: { borderColor: palette.axis, minimumWidth: 64 },
      timeScale: { visible: false, borderColor: palette.axis },
      localization: { locale: "zh-CN" },
    });
    const volumeChart = createChart(volumeRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: palette.text,
        fontSize: 11,
      },
      grid: {
        vertLines: { color: palette.grid },
        horzLines: { color: palette.grid },
      },
      width: volumeRef.current.clientWidth,
      height: VOLUME_HEIGHT,
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: palette.axis, minimumWidth: 64 },
      timeScale: { borderColor: palette.axis },
      localization: { locale: "zh-CN" },
    });

    try {
      const candleSeries = priceChart.addCandlestickSeries({
        upColor: RISE_COLOR,
        downColor: FALL_COLOR,
        borderUpColor: RISE_COLOR,
        borderDownColor: FALL_COLOR,
        wickUpColor: RISE_COLOR,
        wickDownColor: FALL_COLOR,
      });
      const candles: CandlestickData<Time>[] = displayBars.map((bar) => ({
        time: bar.trade_date as Time,
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
      }));

      const maSeriesList = scene.ma.map((spec) => {
        const series = priceChart.addLineSeries({
          color: spec.color,
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });
        const data: LineData<Time>[] = [];
        for (let index = range.start; index <= range.end; index += 1) {
          const value = spec.values[index];
          if (value != null) {
            data.push({ time: bars[index].trade_date as Time, value });
          }
        }
        return { series, data, window: spec.window };
      });

      const volumeSeries = volumeChart.addHistogramSeries({
        priceFormat: { type: "volume" },
      });
      const volumes: HistogramData<Time>[] = displayBars.map((bar) => ({
        time: bar.trade_date as Time,
        value: bar.volume,
        // 信号日量柱加重不透明度，配合缩量因子的看点演示。
        color:
          bar.trade_date === caseItem.signalDate
            ? bar.close >= bar.open
              ? "rgba(239,68,68,0.9)"
              : "rgba(34,197,94,0.9)"
            : bar.close >= bar.open
              ? "rgba(239,68,68,0.42)"
              : "rgba(34,197,94,0.42)",
      }));
      const volumeMaSeries = [
        { values: scene.volumeMa5, color: "#f59e0b" },
        { values: scene.volumeMa10, color: "#2563eb" },
      ].map((spec) => {
        const series = volumeChart.addLineSeries({
          color: spec.color,
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });
        const data: LineData<Time>[] = [];
        for (let index = range.start; index <= range.end; index += 1) {
          const value = spec.values[index];
          if (value != null) {
            data.push({ time: bars[index].trade_date as Time, value });
          }
        }
        return { series, data };
      });

      // 买入信号 / 预期启动标记（文字写进 marker 的 text，与详情页 markers 惯例一致）。
      const markers: SeriesMarker<Time>[] = [
        {
          time: caseItem.signalDate as Time,
          position: "belowBar",
          shape: "arrowUp",
          color: RISE_COLOR,
          text: "信号",
        },
      ];
      if (caseItem.expectedLaunchDate) {
        markers.push({
          time: caseItem.expectedLaunchDate as Time,
          position: "aboveBar",
          shape: "circle",
          color: BRAND_COLOR,
          text: "启动",
        });
      }
      markers.sort((a, b) => String(a.time).localeCompare(String(b.time)));
      candleSeries.setMarkers(markers);

      // 主副图 x 轴双向同步（syncing 哨兵防反馈循环）。
      let syncing = false;
      priceChart.timeScale().subscribeVisibleLogicalRangeChange((next) => {
        if (syncing || !next) return;
        syncing = true;
        volumeChart.timeScale().setVisibleLogicalRange(next);
        syncing = false;
      });
      volumeChart.timeScale().subscribeVisibleLogicalRangeChange((next) => {
        if (syncing || !next) return;
        syncing = true;
        priceChart.timeScale().setVisibleLogicalRange(next);
        syncing = false;
      });

      // 图例初始值 = 窗口末根 K 线的 MA 值。
      const legend: Record<number, number | null> = {};
      for (const spec of scene.ma) {
        legend[spec.window] = spec.values[range.end] ?? null;
      }
      setMaLegend(legend);

      // 信号日竖分隔线：HTML overlay，随视野/尺寸变化重算 x 坐标。
      const updateSignalLine = () => {
        const line = signalLineRef.current;
        if (!line) return;
        const x = priceChart.timeScale().timeToCoordinate(
          caseItem.signalDate as Time,
        );
        if (x == null) {
          line.style.display = "none";
          return;
        }
        line.style.display = "";
        line.style.left = `${x}px`;
      };
      priceChart
        .timeScale()
        .subscribeVisibleLogicalRangeChange(updateSignalLine);
      const resizeObserver = new ResizeObserver(() => {
        const width = priceRef.current?.clientWidth ?? 0;
        if (width > 0) {
          priceChart.applyOptions({ width });
          volumeChart.applyOptions({ width });
        }
        updateSignalLine();
      });
      resizeObserver.observe(priceRef.current);

      // 渐进绘制：所有 series 同步切同一前缀长度；reduced-motion 下一次性呈现。
      const allSeries = [
        { series: candleSeries, data: candles },
        ...maSeriesList,
        { series: volumeSeries, data: volumes },
        ...volumeMaSeries,
      ];
      let frame = 0;
      const revealAll = () => {
        for (const item of allSeries) {
          item.series.setData(item.data as never);
        }
        updateSignalLine();
      };
      if (reducedMotion || candles.length <= 8) {
        revealAll();
      } else {
        const total = candles.length;
        const initialCount = Math.max(1, Math.floor(total * REVEAL_INITIAL_RATIO));
        const startedAt = performance.now();
        const step = (now: number) => {
          const progress = Math.min(1, (now - startedAt) / REVEAL_DURATION_MS);
          const eased = 1 - Math.pow(1 - progress, 3);
          const count = Math.max(
            initialCount,
            Math.floor(initialCount + (total - initialCount) * eased),
          );
          for (const item of allSeries) {
            item.series.setData(item.data.slice(0, count) as never);
          }
          updateSignalLine();
          if (progress < 1) {
            frame = requestAnimationFrame(step);
          }
        };
        for (const item of allSeries) {
          item.series.setData(item.data.slice(0, initialCount) as never);
        }
        frame = requestAnimationFrame(step);
      }

      return () => {
        cancelAnimationFrame(frame);
        resizeObserver.disconnect();
        priceChart.remove();
        volumeChart.remove();
      };
    } catch (error) {
      // 渲染失败时销毁半图表，由外层继续展示文案/ chips（不白屏）。
      console.error("guide case chart render error:", error);
      priceChart.remove();
      volumeChart.remove();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scene, palette, caseItem.signalDate, caseItem.expectedLaunchDate, reducedMotion]);

  const returnsChips = (
    <div className="flex flex-wrap items-center gap-1.5 text-[11px] tabular-nums">
      {(
        [
          ["D+1", caseItem.returns.d1],
          ["D+3", caseItem.returns.d3],
          ["D+5", caseItem.returns.d5],
        ] as const
      ).map(([label, value]) => (
        <span
          key={label}
          className={cn(
            "rounded border px-1.5 py-0.5",
            value == null
              ? "text-muted-foreground"
              : priceColorClass(value),
          )}
          title={
            value == null
              ? (RETURNS_STATUS_TEXT[caseItem.returns.status] ??
                caseItem.returns.status)
              : undefined
          }
        >
          {label} {value == null ? "--" : formatPct(value)}
        </span>
      ))}
      {caseItem.narrativeStatus === "research_pending" && (
        <span className="rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-amber-600">
          未成规则·待验证
        </span>
      )}
    </div>
  );

  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <div className="flex items-center gap-1.5 text-xs font-medium">
          <span className="text-foreground">{caseItem.name}</span>
          <span className="tabular-nums text-muted-foreground">
            {caseItem.signalDate}
          </span>
        </div>
        {returnsChips}
      </div>
      {chartHint && (
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          📈 看点：{chartHint}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[10px] tabular-nums text-muted-foreground">
        {MA_SPECS.map((spec) => (
          <span key={spec.window} className="flex items-center gap-1">
            <span
              className="inline-block h-1.5 w-3 rounded-sm"
              style={{ backgroundColor: spec.color }}
            />
            {spec.label}
            {maLegend[spec.window] != null && (
              <span>{maLegend[spec.window]?.toFixed(2)}</span>
            )}
          </span>
        ))}
      </div>
      {barsQuery.isLoading ? (
        <Skeleton className="h-[280px] w-full" />
      ) : barsQuery.isError || !scene ? (
        <EmptyState
          message="案例 K 线暂不可用"
          description={
            barsQuery.data?.status === "unavailable"
              ? "本地历史库未配置"
              : "信号日不在本地日线序列或窗口无数据"
          }
        />
      ) : (
        <div className="overflow-hidden rounded-md border">
          <div className="relative">
            <div ref={priceRef} className="h-[280px] w-full" />
            {/* 信号日竖分隔线（HTML overlay，不画假 series 污染价格轴） */}
            <div
              ref={signalLineRef}
              className="pointer-events-none absolute inset-y-0 w-px bg-primary/60"
            >
              <span className="absolute -top-0 left-1 rounded bg-primary/10 px-1 text-[9px] text-primary">
                信号日
              </span>
            </div>
          </div>
          <div ref={volumeRef} className="h-[85px] w-full border-t" />
        </div>
      )}
      <p className="text-[10px] text-muted-foreground/80">
        窗口：底盘起点 → 信号日后 10 个交易日 · raw 不复权（与回测同口径，除权日可见跳空）
      </p>
    </div>
  );
}
