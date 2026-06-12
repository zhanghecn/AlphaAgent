import { useEffect, useRef } from "react";
import {
  createChart,
  type IChartApi,
  type Time,
  ColorType,
  CrosshairMode,
} from "lightweight-charts";

export interface SignalMarker {
  time: string; // YYYY-MM-DD format
  price: number;
  type: "buy" | "sell";
  reason?: string;
}

export interface HoldingMiniChartProps {
  bars: Array<{
    time: string; // YYYY-MM-DD
    open: number;
    high: number;
    low: number;
    close: number;
  }>;
  costPrice?: number;
  stopLossPrice?: number;
  takeProfitPrice?: number;
  buySignals?: SignalMarker[];
  sellSignals?: SignalMarker[];
  height?: number; // default 120
  onClick?: () => void;
}

export function HoldingMiniChart({
  bars,
  costPrice,
  stopLossPrice,
  takeProfitPrice,
  buySignals,
  sellSignals,
  height = 120,
  onClick,
}: HoldingMiniChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!containerRef.current || !bars || bars.length === 0) {
      return;
    }

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#9ca3af",
        fontSize: 10,
      },
      grid: {
        vertLines: { visible: false },
        horzLines: { visible: false },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: {
        borderVisible: false,
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
      timeScale: { visible: false, borderVisible: false },
      handleScale: false,
      handleScroll: false,
    });

    chartRef.current = chart;

    const candleSeries = chart.addCandlestickSeries({
      upColor: "#ef4444", // red for rise (A-share)
      downColor: "#22c55e", // green for fall (A-share)
      borderUpColor: "#ef4444",
      borderDownColor: "#22c55e",
      wickUpColor: "#ef4444",
      wickDownColor: "#22c55e",
    });

    candleSeries.setData(
      bars.map((bar) => ({
        time: bar.time as Time,
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
      }))
    );

    // Cost price line (gray dashed)
    if (costPrice) {
      candleSeries.createPriceLine({
        price: costPrice,
        color: "#9ca3af",
        lineWidth: 1,
        lineStyle: 2, // dashed
        axisLabelVisible: false,
        title: "",
      });
    }

    // Stop loss price line (red dashed)
    if (stopLossPrice) {
      candleSeries.createPriceLine({
        price: stopLossPrice,
        color: "#ef4444",
        lineWidth: 1,
        lineStyle: 2, // dashed
        axisLabelVisible: false,
        title: "",
      });
    }

    // Take profit price line (green dashed)
    if (takeProfitPrice) {
      candleSeries.createPriceLine({
        price: takeProfitPrice,
        color: "#22c55e",
        lineWidth: 1,
        lineStyle: 2, // dashed
        axisLabelVisible: false,
        title: "",
      });
    }

    // Buy/sell markers
    const markers = [
      ...(buySignals?.map((s) => ({
        time: s.time as Time,
        position: "belowBar" as const,
        color: "#22c55e",
        shape: "arrowUp" as const,
        text: s.reason || "买入",
      })) ?? []),
      ...(sellSignals?.map((s) => ({
        time: s.time as Time,
        position: "aboveBar" as const,
        color: "#ef4444",
        shape: "arrowDown" as const,
        text: s.reason || "卖出",
      })) ?? []),
    ].sort((a, b) =>
      a.time < b.time ? -1 : a.time > b.time ? 1 : 0
    );

    if (markers.length > 0) {
      candleSeries.setMarkers(markers);
    }

    // Resize observer
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        chart.applyOptions({ width: entry.contentRect.width });
      }
    });
    observer.observe(containerRef.current);

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [bars, costPrice, stopLossPrice, takeProfitPrice, buySignals, sellSignals, height]);

  if (!bars || bars.length === 0) {
    return null;
  }

  return (
    <div
      ref={containerRef}
      style={{ height, width: "100%" }}
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => { if (e.key === "Enter" || e.key === " ") onClick(); } : undefined}
    />
  );
}
