import { lazy, Suspense } from "react";
import type { ReactNode } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { AppShell } from "@/components/AppShell";
import { LoadingState } from "@/components/LoadingState";
import { SeoHead } from "@/components/SeoHead";
import {
  ADMIN_SESSION_QUERY_KEY,
  authRequired,
  authToken,
  getAdminSession,
} from "@/api/client";

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
const LadderHistoryPage = lazy(() => import("@/pages/LadderHistoryPage").then((m) => ({ default: m.LadderHistoryPage })));
const DataManagementPage = lazy(() => import("@/pages/DataManagementPage"));

/**
 * AUTH_REQUIRED=true 时才检查 token；默认直接进入工作台。
 */
function RequireAuth({ children }: { children: ReactNode }) {
  if (authRequired && !authToken.get()) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

/** 数据管理始终要求管理员会话，匿名工作台模式不影响该规则。 */
function RequireAdmin({ children }: { children: ReactNode }) {
  const hasAdminToken = Boolean(authToken.get());
  const { data: adminSession, isFetching } = useQuery({
    queryKey: ADMIN_SESSION_QUERY_KEY,
    queryFn: getAdminSession,
    enabled: hasAdminToken,
    staleTime: 0,
    retry: false,
    refetchOnMount: "always",
  });

  if (!hasAdminToken || isFetching || !adminSession?.authenticated) {
    return hasAdminToken && isFetching ? <LoadingState rows={6} /> : <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

export default function App() {
  return (
    <>
      <SeoHead forceNoIndex={authRequired} />
      <Suspense fallback={<LoadingState rows={6} />}>
        <Routes>
          {/* 匿名用户直接进入工作台；/login 仅保留给管理员执行写操作。 */}
          <Route path="/login" element={<LoginPage />} />
          {/* 认证开关关闭时 RequireAuth 直接透传。 */}
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
                      <Route path="/lianban/ladder" element={<LadderHistoryPage />} />
                      <Route
                        path="/data"
                        element={
                          <RequireAdmin>
                            <DataManagementPage />
                          </RequireAdmin>
                        }
                      />
                      {/* Legacy routes */}
                      <Route path="/sectors" element={<SectorsPage />} />
                      <Route
                        path="/data-sync"
                        element={
                          <RequireAdmin>
                            <DataManagementPage />
                          </RequireAdmin>
                        }
                      />
                    </Routes>
                  </Suspense>
                </AppShell>
              </RequireAuth>
            }
          />
        </Routes>
      </Suspense>
    </>
  );
}
