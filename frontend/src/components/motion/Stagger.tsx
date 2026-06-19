import { motion, useReducedMotion, type Variants } from "framer-motion";
import type { ReactNode } from "react";

const EASE: [number, number, number, number] = [0.16, 1, 0.3, 1];

interface StaggerListProps {
  children: ReactNode;
  className?: string;
  /** 子项之间的错峰间隔（秒） */
  staggerDelay?: number;
  /** 列表整体进入前的延迟（秒） */
  initialDelay?: number;
}

/** 列表容器：驱动子级 StaggerItem 逐项进入。
 *  variants 通过 context 自动传递给子级 motion 组件。 */
export function StaggerList({
  children,
  className,
  staggerDelay = 0.06,
  initialDelay = 0,
}: StaggerListProps) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      className={className}
      initial={reduce ? false : "hidden"}
      animate="visible"
      variants={{
        hidden: {},
        visible: {
          transition: {
            staggerChildren: reduce ? 0 : staggerDelay,
            delayChildren: initialDelay,
          },
        },
      }}
    >
      {children}
    </motion.div>
  );
}

interface StaggerItemProps {
  children: ReactNode;
  className?: string;
}

/** 列表项：配合 StaggerList 使用，自身继承父级 variants。 */
export function StaggerItem({ children, className }: StaggerItemProps) {
  const reduce = useReducedMotion();
  const variants: Variants = {
    hidden: { opacity: 0, y: reduce ? 0 : 12 },
    visible: {
      opacity: 1,
      y: 0,
      transition: { duration: 0.4, ease: EASE },
    },
  };
  return (
    <motion.div className={className} variants={variants}>
      {children}
    </motion.div>
  );
}
