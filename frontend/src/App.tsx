import { lazy, Suspense } from "react";
import { Routes, Route } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { LoadingState } from "@/components/LoadingState";

// 路由懒加载：每个页面拆成独立 chunk，首屏只加载当前页，显著减小初始 bundle。
const MarketOverviewPage = lazy(() => import("@/pages/MarketOverviewPage").then((m) => ({ default: m.MarketOverviewPage })));
const StocksPage = lazy(() => import("@/pages/StocksPage").then((m) => ({ default: m.StocksPage })));
const StockDetailPage = lazy(() => import("@/pages/StockDetailPage").then((m) => ({ default: m.StockDetailPage })));
const SectorsPage = lazy(() => import("@/pages/SectorsPage").then((m) => ({ default: m.SectorsPage })));
const QuantTradingPage = lazy(() => import("@/pages/QuantTradingPage").then((m) => ({ default: m.QuantTradingPage })));
const PortfolioPage = lazy(() => import("@/pages/PortfolioPage").then((m) => ({ default: m.PortfolioPage })));
const ThemeExplorerPage = lazy(() => import("@/pages/ThemeExplorerPage"));
const ChainGraphPage = lazy(() => import("@/pages/ChainGraphPage"));
const DataManagementPage = lazy(() => import("@/pages/DataManagementPage"));

export default function App() {
  return (
    <AppShell>
      <Suspense fallback={<LoadingState rows={6} />}>
        <Routes>
          <Route path="/" element={<MarketOverviewPage />} />
          <Route path="/explore" element={<ThemeExplorerPage />} />
          <Route path="/stocks" element={<StocksPage />} />
          <Route path="/stocks/:vtSymbol" element={<StockDetailPage />} />
          <Route path="/quant" element={<QuantTradingPage />} />
          <Route path="/portfolio" element={<PortfolioPage />} />
          <Route path="/chain" element={<ChainGraphPage />} />
          <Route path="/data" element={<DataManagementPage />} />
          {/* Legacy routes */}
          <Route path="/sectors" element={<SectorsPage />} />
          <Route path="/data-sync" element={<DataManagementPage />} />
        </Routes>
      </Suspense>
    </AppShell>
  );
}
