import { useEffect, useState } from "react";
import { useSpring, useReducedMotion, useMotionValueEvent } from "framer-motion";
import { cn } from "@/lib/utils";
import { formatAnimatedValue, type AnimFormat } from "./format";

interface CountUpProps {
  value: number;
  format?: AnimFormat;
  /** 仅对 raw/price 生效（pct/amount/marketcap 走固定业务格式） */
  decimals?: number;
  className?: string;
}

/**
 * 数字从 0 平滑滚动到 value（spring 物理曲线），value 变化时平滑过渡到新值。
 * reduce-motion 时直接显示终值（不滚动）。
 * 复用 lib/utils 的 formatter（单参），不引第二套格式化路径。
 */
export function CountUp({
  value,
  format = "raw",
  decimals = 2,
  className,
}: CountUpProps) {
  const reduce = useReducedMotion();
  const spring = useSpring(reduce ? value : 0, {
    stiffness: 100,
    damping: 20,
    mass: 0.5,
  });
  const [display, setDisplay] = useState(reduce ? value : 0);

  useEffect(() => {
    if (reduce) {
      setDisplay(value);
      return;
    }
    spring.set(value);
  }, [value, reduce, spring]);

  useMotionValueEvent(spring, "change", (v) => {
    setDisplay(v);
  });

  return (
    <span data-num className={cn("tabular-nums", className)}>
      {formatAnimatedValue(display, format, decimals)}
    </span>
  );
}
