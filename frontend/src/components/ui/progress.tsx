import * as React from "react";
import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

interface ProgressProps extends React.HTMLAttributes<HTMLDivElement> {
  /** 当前进度值 */
  value?: number;
  /** 最大值（默认 100） */
  max?: number;
  /** 指示条额外类名（可换渐变 / 涨跌色） */
  indicatorClassName?: string;
}

/**
 * 进度条：framer-motion width spring + 品牌渐变，进度变化时平滑过渡。
 * 自建（不依赖 radix），用于量化选股进度、数据同步进度等。
 */
const Progress = React.forwardRef<HTMLDivElement, ProgressProps>(
  ({ className, value = 0, max = 100, indicatorClassName, ...props }, ref) => {
    const ratio = max > 0 ? value / max : 0;
    const pct = Math.min(100, Math.max(0, ratio * 100));
    return (
      <div
        ref={ref}
        role="progressbar"
        aria-valuenow={value}
        aria-valuemax={max}
        className={cn(
          "relative h-2 w-full overflow-hidden rounded-full bg-muted",
          className,
        )}
        {...props}
      >
        <motion.div
          className={cn(
            "h-full rounded-full bg-gradient-brand",
            indicatorClassName,
          )}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ type: "spring", stiffness: 120, damping: 20 }}
        />
      </div>
    );
  },
);
Progress.displayName = "Progress";

export { Progress };
