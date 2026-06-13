import { cn } from "@/lib/utils";

interface DataSkeletonProps {
  className?: string;
}

/**
 * shimmer 加载占位块：横向流光扫描效果，比纯灰块更精致。
 * 配合 tailwind 的 animate-shimmer + 渐变背景实现。
 */
export function DataSkeleton({ className }: DataSkeletonProps) {
  return (
    <div
      className={cn(
        "animate-shimmer rounded-md bg-gradient-to-r from-muted via-muted/60 to-muted bg-[length:200%_100%]",
        className,
      )}
    />
  );
}
