import { motion, AnimatePresence, useReducedMotion } from "framer-motion";
import { useLocation } from "react-router-dom";
import type { ReactNode } from "react";

const EASE: [number, number, number, number] = [0.16, 1, 0.3, 1];

/** 路由切换时的页面过渡：fade + 轻微上移。
 *  以 location.pathname 为 key，AnimatePresence mode="wait" 确保旧页退出后再进新页。
 *  包在 <Suspense> 内、<Routes> 外。reduce-motion 时无过渡。 */
export function PageTransition({ children }: { children: ReactNode }) {
  const location = useLocation();
  const reduce = useReducedMotion();

  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div
        key={location.pathname}
        initial={reduce ? false : { opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={reduce ? undefined : { opacity: 0, y: -8 }}
        transition={{ duration: 0.25, ease: EASE }}
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}
