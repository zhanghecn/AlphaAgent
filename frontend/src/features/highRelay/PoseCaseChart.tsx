import { useEffect, useRef } from "react";
import {
  createChart,
  ColorType,
  type CandlestickData,
  type LineData,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";

import { useChartColors, RISE_COLOR, FALL_COLOR } from "@/lib/chart-theme";

/**
 * 地基姿态案例K线小图(v6.10 规则页四宫格):真实特征票的K线窗
 * (地基日前12根~决策日,~15根自动放大到能看清K线与MA20蓝线的距离),
 * 地基日那根K线上方标箭头;MA20=蓝线(与答题页同色)。
 */

export interface HprPoseCase {
  name: string;
  date: string;
  pose: string;
  note: string;
  code?: string;
  kline: { time: string; open: number; high: number; low: number; close: number; ma20: number | null }[];
  foundation_idx: number;
  e3?: number;
}

export function PoseCaseChart({ c }: { c: HprPoseCase }) {
  const ref = useRef<HTMLDivElement>(null);
  const palette = useChartColors();

  useEffect(() => {
    if (!ref.current || c.kline.length === 0) return;
    const chart = createChart(ref.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: palette.text,
        fontSize: 10,
      },
      grid: {
        vertLines: { color: palette.grid },
        horzLines: { color: palette.grid },
      },
      rightPriceScale: { borderColor: palette.grid, scaleMargins: { top: 0.12, bottom: 0.08 } },
      timeScale: { borderColor: palette.grid, timeVisible: false, rightOffset: 2 },
    });
    const candle = chart.addCandlestickSeries({
      upColor: RISE_COLOR,
      downColor: FALL_COLOR,
      borderVisible: false,
      wickUpColor: RISE_COLOR,
      wickDownColor: FALL_COLOR,
    });
    const data: CandlestickData[] = c.kline.map((b) => ({
      time: b.time as Time,
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
    }));
    candle.setData(data);
    const fbar = c.kline[c.foundation_idx];
    if (fbar) {
      const markers: SeriesMarker<Time>[] = [{
        time: fbar.time as Time,
        position: "aboveBar",
        color: "#3b82f6",
        shape: "arrowDown",
        text: "地基日",
      }];
      candle.setMarkers(markers);
    }
    const maData: LineData[] = c.kline
      .filter((b) => b.ma20 != null)
      .map((b) => ({ time: b.time as Time, value: b.ma20 as number }));
    if (maData.length) {
      const line = chart.addLineSeries({
        color: "#2563eb",
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      line.setData(maData);
    }
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [c, palette]);

  return <div ref={ref} className="h-[190px] w-full" />;
}
