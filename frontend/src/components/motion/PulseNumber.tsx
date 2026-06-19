import { useEffect, useRef, useState } from "react";
import { cn, priceColorClass } from "@/lib/utils";
import { formatAnimatedValue, type AnimFormat } from "./format";

interface PulseNumberProps {
  value: number | null | undefined;
  format?: AnimFormat;
  decimals?: number;
  className?: string;
}

/**
 * 数值变化时短暂高亮（涨→红色脉冲 / 跌→绿色脉冲），涨跌色走 priceColorClass。
 * 不带滚动动画，用于非滚动场景的数值跳变反馈（如排名变化、计数更新）。
 * 滚动场景请用 KpiNumber / CountUp。
 */
export function PulseNumber({
  value,
  format = "raw",
  decimals = 2,
  className,
}: PulseNumberProps) {
  const prev = useRef<number | null | undefined>(value);
  const [pulse, setPulse] = useState("");

  useEffect(() => {
    const before = prev.current;
    if (before != null && value != null && value !== before) {
      const dir = value > before ? "rise" : "fall";
      setPulse(dir === "rise" ? "animate-pulse-rise" : "animate-pulse-fall");
      const timer = setTimeout(() => setPulse(""), 1200);
      prev.current = value;
      return () => clearTimeout(timer);
    }
    prev.current = value;
  }, [value]);

  return (
    <span
      data-num
      className={cn("tabular-nums rounded px-0.5", pulse, priceColorClass(value), className)}
    >
      {formatAnimatedValue(value ?? NaN, format, decimals)}
    </span>
  );
}
