import { lazy, Suspense } from "react";
import type { ReactNode } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { LoadingState } from "@/components/LoadingState";
import { authToken } from "@/api/client";

// 路由懒加载：每个页面拆成独立 chunk，首屏只加载当前页，显著减小初始 bundle。
const LoginPage = lazy(() => import("@/pages/LoginPage").then((m) => ({ default: m.LoginPage })));
const MarketOverviewPage = lazy(() => import("@/pages/MarketOverviewPage").then((m) => ({ default: m.MarketOverviewPage })));
const StocksPage = lazy(() => import("@/pages/StocksPage").then((m) => ({ default: m.StocksPage })));
const StockDetailPage = lazy(() => import("@/pages/StockDetailPage").then((m) => ({ default: m.StockDetailPage })));
const IndexDetailPage = lazy(() => import("@/pages/IndexDetailPage").then((m) => ({ default: m.IndexDetailPage })));
const MarketTimingPage = lazy(() => import("@/pages/MarketTimingPage").then((m) => ({ default: m.MarketTimingPage })));
const SectorsPage = lazy(() => import("@/pages/SectorsPage").then((m) => ({ default: m.SectorsPage })));
const MainlineReplayPage = lazy(() => import("@/pages/MainlineReplayPage"));
const ShortTermResearchPage = lazy(() => import("@/pages/ShortTermResearchPage").then((m) => ({ default: m.ShortTermResearchPage })));
const LianbanReviewPage = lazy(() => import("@/pages/LianbanReviewPage").then((m) => ({ default: m.LianbanReviewPage })));
const DataManagementPage = lazy(() => import("@/pages/DataManagementPage"));

/**
 * 登录守卫：纯前端检查 token 是否存在。
 * token 过期由后端 401 兜底——client.ts 会清 token 并跳 /login。
 */
function RequireAuth({ children }: { children: ReactNode }) {
  if (!authToken.get()) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <Suspense fallback={<LoadingState rows={6} />}>
      <Routes>
        {/* 登录页独立于 AppShell（无侧栏） */}
        <Route path="/login" element={<LoginPage />} />
        {/* 其余路由需登录后访问 */}
        <Route
          path="*"
          element={
            <RequireAuth>
              <AppShell>
                <Suspense fallback={<LoadingState rows={6} />}>
                  <Routes>
                    <Route path="/" element={<MarketOverviewPage />} />
                    <Route path="/explore" element={<Navigate to="/mainline" replace />} />
                    <Route path="/stocks" element={<StocksPage />} />
                    <Route path="/stocks/:vtSymbol" element={<StockDetailPage />} />
                    <Route path="/indices/:key" element={<IndexDetailPage />} />
                    <Route path="/market" element={<MarketTimingPage />} />
                    <Route path="/chain" element={<Navigate to="/mainline" replace />} />
                    <Route path="/mainline" element={<MainlineReplayPage />} />
                    <Route path="/short-term" element={<ShortTermResearchPage />} />
                    <Route path="/lianban" element={<LianbanReviewPage />} />
                    <Route path="/data" element={<DataManagementPage />} />
                    {/* Legacy routes */}
                    <Route path="/sectors" element={<SectorsPage />} />
                    <Route path="/data-sync" element={<DataManagementPage />} />
                  </Routes>
                </Suspense>
              </AppShell>
            </RequireAuth>
          }
        />
      </Routes>
    </Suspense>
  );
}
