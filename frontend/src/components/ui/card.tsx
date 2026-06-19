import * as React from "react";
import { cn } from "@/lib/utils";

type CardVariant = "default" | "glass" | "lift";

const VARIANT_CLASS: Record<CardVariant, string> = {
  // 默认：靛蓝设计系统统一区块骨架（保留原样式，向后兼容）
  default:
    "rounded-xl border bg-card text-card-foreground shadow-card transition-shadow duration-200 hover:shadow-card-hover",
  // 玻璃：backdrop-blur 半透明（仅固定/浮层/卡片头使用，列表项禁用以保性能）
  glass:
    "rounded-xl text-card-foreground glass shadow-glass dark:shadow-glass-dark transition-shadow duration-200 hover:shadow-card-hover",
  // 升力：hover 整体上浮（CSS transform，比 motion 包裹更轻量）
  lift:
    "rounded-xl border bg-card text-card-foreground shadow-card transition-all duration-200 ease-spring hover:-translate-y-0.5 hover:shadow-card-hover",
};

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: CardVariant;
}

/**
 * 卡片容器：靛蓝设计系统下的统一区块骨架。
 * variant=default 保持原行为；glass/lift 为整体视觉刷新新增的质感变体。
 */
const Card = React.forwardRef<HTMLDivElement, CardProps>(
  ({ className, variant = "default", ...props }, ref) => (
    <div
      ref={ref}
      className={cn(VARIANT_CLASS[variant], className)}
      {...props}
    />
  ),
);
Card.displayName = "Card";

const CardHeader = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn("flex flex-col space-y-1.5 p-6", className)}
    {...props}
  />
));
CardHeader.displayName = "CardHeader";

const CardTitle = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn(
      "font-display text-lg font-semibold leading-none tracking-tight",
      className,
    )}
    {...props}
  />
));
CardTitle.displayName = "CardTitle";

const CardDescription = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn("text-sm text-muted-foreground", className)}
    {...props}
  />
));
CardDescription.displayName = "CardDescription";

const CardContent = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div ref={ref} className={cn("p-6 pt-0", className)} {...props} />
));
CardContent.displayName = "CardContent";

const CardFooter = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn("flex items-center p-6 pt-0", className)}
    {...props}
  />
));
CardFooter.displayName = "CardFooter";

export {
  Card,
  CardHeader,
  CardFooter,
  CardTitle,
  CardDescription,
  CardContent,
};
