import { useEffect, useRef } from "react";
import {
  createChart,
  ColorType,
  CrosshairMode,
  LineStyle,
  type CandlestickData,
  type HistogramData,
  type IPriceLine,
  type LineData,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";

import type { HprQuizBar } from "@/api/highRelay";
import { useChartColors, RISE_COLOR, FALL_COLOR, BRAND_COLOR } from "@/lib/chart-theme";
import { smaSeries } from "@/components/shared/guideKline";

/**
 * 答题训练 K 线(受控组件,bars 由 props 给,不发请求):
 * - 作答态:末板前 ~30 根 + 决策日一根「今开十字」(O=H=L=C=今开价) + 今开虚线
 * - 揭示态:瞬时补决策日全天+持有期K线(零动画),买/卖 marker + 买入价线
 * MA 在 暖机段+揭示段 全序列上算,显示窗切末 ~46 根;主图+量副图 x 轴同步。
 */

const MAIN_HEIGHT = 280;
const VOLUME_HEIGHT = 85;
const BEFORE_VISIBLE = 30;   // 作答态展示的末板前根数
const VISIBLE_BARS = 48;     // 显示窗宽度(揭示后含持有期)

/** 窄容器按 ~8px/根收紧显示窗(手机 375px → ~32 根);≥448px 绘图区维持 48 根 → 桌面零变化。
 * 下限 24:决策日恒在序列右锚窗内(作答 31 根/揭示最长 47 根),必含。导出供单测。 */
export function visibleBarsForWidth(plotWidth: number): number {
  return Math.max(24, Math.min(VISIBLE_BARS, Math.floor(plotWidth / 8)));
}
const MA_SPECS = [
  { window: 5, color: "#f59e0b" },
  { window: 10, color: "#8b5cf6" },
  { window: 20, color: "#2563eb" },
] as const;

interface QuizKlineChartProps {
  barsBefore: HprQuizBar[];   // 末根=末板收盘(决策日前一天)
  decisionDate: string;
  decisionOpen: number;       // 今开价
  auctionPct: number;         // 今开%
  revealed: boolean;
  barsAfter?: HprQuizBar[];   // 首根=决策日全天
  buyPrice?: number | null;
  exitDate?: string | null;
  exitPrice?: number | null;
  retPct?: number | null;
}

// 签名直接解构:effect 依赖原始字段而非 props 对象(内联字面量每次渲染都是新引用,
// 会让无关 setState 也整图销毁重建,低端手机卡顿;bars 来自 react-query 缓存引用稳定)
export function QuizKlineChart({
  barsBefore,
  decisionDate,
  decisionOpen,
  auctionPct,
  revealed,
  barsAfter = [],
  buyPrice,
  exitDate,
  exitPrice,
  retPct,
}: QuizKlineChartProps) {
  const palette = useChartColors();
  const priceRef = useRef<HTMLDivElement>(null);
  const volumeRef = useRef<HTMLDivElement>(null);
  const lineRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!priceRef.current || !volumeRef.current) return;
    if (barsBefore.length === 0) return;

    // MA 在全序列(暖机段+揭示段)上算,显示只切窗口
    const allBars: HprQuizBar[] = revealed ? [...barsBefore, ...barsAfter] : barsBefore;
    const closes = allBars.map((b) => b.c);
    const maList = MA_SPECS.map((spec) => ({
      ...spec,
      values: smaSeries(closes, spec.window),
    }));

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
      // 手机:单指竖滑穿透回页面滚动(不 preventDefault);横滑平移/双指缩放/桌面鼠标全保留
      handleScroll: { vertTouchDrag: false },
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
      handleScroll: { vertTouchDrag: false },
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

      const toCandle = (b: HprQuizBar): CandlestickData<Time> => ({
        time: b.d as Time, open: b.o, high: b.h, low: b.l, close: b.c,
      });
      const showBefore = barsBefore.slice(-BEFORE_VISIBLE);
      const candles: CandlestickData<Time>[] = showBefore.map(toCandle);
      if (revealed) {
        for (const b of barsAfter) candles.push(toCandle(b));
      } else {
        // 今开十字:全天还没走,只有竞价开盘价
        candles.push({
          time: decisionDate as Time,
          open: decisionOpen, high: decisionOpen,
          low: decisionOpen, close: decisionOpen,
        });
      }
      candleSeries.setData(candles);

      // MA 线:显示段 = showBefore(全序列末30根) + 揭示段
      const maStart = barsBefore.length - showBefore.length;
      for (const spec of maList) {
        const series = priceChart.addLineSeries({
          color: spec.color,
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });
        const data: LineData<Time>[] = [];
        for (let idx = Math.max(0, maStart); idx < allBars.length; idx += 1) {
          const value = spec.values[idx];
          if (value != null) data.push({ time: allBars[idx].d as Time, value });
        }
        series.setData(data);
      }

      // 量副图
      const volumeSeries = volumeChart.addHistogramSeries({
        priceFormat: { type: "volume" },
      });
      const toVol = (b: HprQuizBar, dim: boolean): HistogramData<Time> => ({
        time: b.d as Time,
        value: b.v,
        color: b.c >= b.o
          ? `rgba(239,68,68,${dim ? 0.18 : 0.42})`
          : `rgba(34,197,94,${dim ? 0.18 : 0.42})`,
      });
      const volumes: HistogramData<Time>[] = showBefore.map((b) => toVol(b, false));
      if (revealed) {
        for (const b of barsAfter) volumes.push(toVol(b, false));
      } else {
        volumes.push({
          time: decisionDate as Time, value: 0,
          color: "rgba(148,163,184,0.25)",
        });
      }
      volumeSeries.setData(volumes);

      // 价格线:作答态=今开虚线;揭示态=买入价实线
      const priceLines: IPriceLine[] = [];
      if (!revealed) {
        priceLines.push(candleSeries.createPriceLine({
          price: decisionOpen,
          color: BRAND_COLOR,
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: `今开 ${auctionPct >= 0 ? "+" : ""}${auctionPct.toFixed(1)}%`,
        }));
      } else if (buyPrice != null) {
        priceLines.push(candleSeries.createPriceLine({
          price: buyPrice,
          color: BRAND_COLOR,
          lineWidth: 1,
          lineStyle: LineStyle.Solid,
          axisLabelVisible: true,
          title: `买入 ${buyPrice.toFixed(2)}`,
        }));
      }

      // 买卖 marker(揭示态)
      if (revealed) {
        const markers: SeriesMarker<Time>[] = [];
        if (buyPrice != null) {
          markers.push({
            time: decisionDate as Time,
            position: "belowBar",
            shape: "arrowUp",
            color: RISE_COLOR,
            text: `买 ${buyPrice.toFixed(2)}`,
          });
        }
        if (exitDate && exitPrice != null) {
          markers.push({
            time: exitDate as Time,
            position: "aboveBar",
            shape: "arrowDown",
            color: FALL_COLOR,
            text: retPct != null
              ? `卖 ${retPct >= 0 ? "+" : ""}${retPct.toFixed(1)}%`
              : "卖",
          });
        }
        markers.sort((a, b) => String(a.time).localeCompare(String(b.time)));
        candleSeries.setMarkers(markers);
      }

      // 主副图 x 轴双向同步(syncing 哨兵)
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

      // 显示窗:末 visibleBars 根(揭示段全在窗内);窄容器按绘图宽收紧,桌面 ≥448px 维持 48 根
      const total = candles.length;
      const containerWidth = priceRef.current.clientWidth;
      const visibleBars = containerWidth > 0
        ? visibleBarsForWidth(containerWidth - 64)  // 64=右侧价格轴预留
        : VISIBLE_BARS;
      const from = Math.max(0, total - visibleBars);
      priceChart.timeScale().setVisibleLogicalRange({ from, to: total + 1 });
      volumeChart.timeScale().setVisibleLogicalRange({ from, to: total + 1 });

      // 决策日竖分隔线(HTML overlay)
      const updateLine = () => {
        const line = lineRef.current;
        if (!line) return;
        const x = priceChart.timeScale().timeToCoordinate(decisionDate as Time);
        if (x == null) {
          line.style.display = "none";
          return;
        }
        line.style.display = "";
        line.style.left = `${x}px`;
      };
      updateLine();
      priceChart.timeScale().subscribeVisibleLogicalRangeChange(updateLine);

      const resizeObserver = new ResizeObserver(() => {
        const width = priceRef.current?.clientWidth ?? 0;
        if (width > 0) {
          priceChart.applyOptions({ width });
          volumeChart.applyOptions({ width });
        }
        updateLine();
      });
      resizeObserver.observe(priceRef.current);

      return () => {
        resizeObserver.disconnect();
        priceChart.remove();
        volumeChart.remove();
      };
    } catch (error) {
      console.error("quiz kline chart render error:", error);
      priceChart.remove();
      volumeChart.remove();
    }
  }, [barsBefore, decisionDate, decisionOpen, auctionPct, revealed,
      barsAfter, buyPrice, exitDate, exitPrice, retPct, palette]);

  return (
    <div className="overflow-hidden rounded-md border">
      <div className="relative">
        <div ref={priceRef} className="h-[280px] w-full" />
        <div
          ref={lineRef}
          className="pointer-events-none absolute inset-y-0 w-px bg-primary/60"
        >
          <span className="absolute -top-0 right-0.5 whitespace-nowrap rounded bg-primary/10 px-1 text-[9px] text-primary">
            决策日
          </span>
        </div>
      </div>
      <div ref={volumeRef} className="h-[85px] w-full border-t" />
    </div>
  );
}
