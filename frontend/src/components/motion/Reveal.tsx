import { motion, useReducedMotion, type Variants } from "framer-motion";
import type { ReactNode } from "react";

type RevealDirection = "up" | "down" | "left" | "right";

const OFFSET: Record<RevealDirection, { x?: number; y?: number }> = {
  up: { y: 16 },
  down: { y: -16 },
  left: { x: 24 },
  right: { x: -24 },
};

// 弹性缓动（与 tailwind transitionTimingFunction.spring 一致）
const EASE: [number, number, number, number] = [0.16, 1, 0.3, 1];

interface RevealProps {
  children: ReactNode;
  direction?: RevealDirection;
  delay?: number;
  duration?: number;
  /** 进入后是否只动画一次（默认 true，避免滚动来回反复触发） */
  once?: boolean;
  /** 进入视口多少比例时触发（0-1） */
  amount?: number;
  className?: string;
}

/** 滚动进入视口时淡入 + 方向位移。reduce-motion 时瞬时显示（无位移）。 */
export function Reveal({
  children,
  direction = "up",
  delay = 0,
  duration = 0.5,
  once = true,
  amount = 0.2,
  className,
}: RevealProps) {
  const reduce = useReducedMotion();
  const offset = reduce ? {} : OFFSET[direction];

  const variants: Variants = {
    hidden: { opacity: 0, ...offset },
    visible: { opacity: 1, x: 0, y: 0 },
  };

  return (
    <motion.div
      className={className}
      variants={variants}
      initial={reduce ? false : "hidden"}
      whileInView="visible"
      viewport={{ once, amount }}
      transition={{ duration, delay, ease: EASE }}
    >
      {children}
    </motion.div>
  );
}
