import path from "path";
import { defineConfig } from "vitest/config";

// 独立于 vite.config.ts 的最小测试配置，仅用于纯逻辑单测。
// UI/组件渲染验证仍走构建后浏览器实测，不引入 jsdom 等额外依赖。
export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "node",
    fileParallelism: false,
    include: ["src/**/*.spec.ts", "src/**/*.spec.tsx", "src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
