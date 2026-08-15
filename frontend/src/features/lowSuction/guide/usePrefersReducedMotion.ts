import { useEffect, useState } from "react";

/**
 * 用户系统级「减少动态效果」偏好的订阅 hook。
 * 说明书案例图表的 JS 渐进绘制动画必须经它门控——全局 CSS 保险层只能
 * 挡 CSS 动画，挡不住 rAF 驱动的 setData。
 */
export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () =>
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onChange = (event: MediaQueryListEvent) => setReduced(event.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  return reduced;
}
