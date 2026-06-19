import { motion, useReducedMotion } from "framer-motion";
import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

interface LiftCardProps {
  children: ReactNode;
  className?: string;
  /** hover 时叠加品牌聚焦辉光 */
  glow?: boolean;
}

/** hover 时整体上浮（spring）+ 可选聚焦辉光。
 *  升力用 framer-motion，阴影由内容 Card 自身的 hover:shadow-card-hover 处理，
 *  避免与 Card 阴影动画冲突。reduce-motion 时无升力。 */
export function LiftCard({ children, className, glow = false }: LiftCardProps) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      className={cn(glow && "transition-shadow duration-200 hover:shadow-focus-glow", className)}
      whileHover={reduce ? undefined : { y: -3 }}
      transition={{ type: "spring", stiffness: 300, damping: 20 }}
    >
      {children}
    </motion.div>
  );
}
