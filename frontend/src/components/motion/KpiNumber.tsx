import { useEffect, useRef, useState } from "react";
import { useSpring, useReducedMotion, useMotionValueEvent } from "framer-motion";
import { cn } from "@/lib/utils";
import { formatAnimatedValue, type AnimFormat } from "./format";

interface KpiNumberProps {
  value: number | null | undefined;
  format?: AnimFormat;
  /** 仅对 raw/price 生效 */
  decimals?: number;
  /** value 变化时是否触发涨跌脉冲（默认 true） */
  pulse?: boolean;
  /** 是否 CountUp 滚动（默认 true）；纯计数无方向语义时也可关脉冲保留滚动 */
  animate?: boolean;
  className?: string;
}

/**
 * 全站数字统一入口：CountUp 滚动 + tabular-nums + display 字体 + 可选涨跌脉冲。
 *
 * 涨跌色由调用方通过 className 传入 priceColorClass（保持 A 股涨红跌绿语义单一来源），
 * 本组件只负责动效：value 变化时按涨跌方向叠加 pulse-rise/pulse-fall 背景高亮。
 * reduce-motion 时退化为瞬时显示、无脉冲。
 */
export function KpiNumber({
  value,
  format = "raw",
  decimals = 2,
  pulse = true,
  animate = true,
  className,
}: KpiNumberProps) {
  const num = value ?? NaN;
  const reduce = useReducedMotion();
  const spring = useSpring(0, { stiffness: 100, damping: 20, mass: 0.5 });
  const [display, setDisplay] = useState(reduce || !animate ? num : 0);
  const prev = useRef<number>(num);
  const [pulseClass, setPulseClass] = useState("");

  useEffect(() => {
    if (reduce || !animate || !Number.isFinite(num)) {
      setDisplay(num);
      return;
    }
    spring.set(num);
  }, [num, reduce, animate, spring]);

  useMotionValueEvent(spring, "change", (v) => {
    setDisplay(v);
  });

  useEffect(() => {
    if (!pulse || !Number.isFinite(num)) {
      prev.current = num;
      return;
    }
    const before = prev.current;
    if (Number.isFinite(before) && num !== before) {
      const dir = num > before ? "rise" : "fall";
      setPulseClass(dir === "rise" ? "animate-pulse-rise" : "animate-pulse-fall");
      const timer = setTimeout(() => setPulseClass(""), 1200);
      prev.current = num;
      return () => clearTimeout(timer);
    }
    prev.current = num;
  }, [num, pulse]);

  return (
    <span
      data-num
      className={cn("font-display tabular-nums rounded px-0.5", pulseClass, className)}
    >
      {formatAnimatedValue(display, format, decimals)}
    </span>
  );
}
