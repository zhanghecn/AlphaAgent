import { useContext } from "react";
import { ThemeContext } from "./ThemeProvider";

/** 获取当前主题与切换方法，必须在 <ThemeProvider> 内使用 */
export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    throw new Error("useTheme 必须在 <ThemeProvider> 内使用");
  }
  return ctx;
}
