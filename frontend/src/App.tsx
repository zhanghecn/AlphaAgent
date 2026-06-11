import { Routes, Route } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { MarketOverviewPage } from "@/pages/MarketOverviewPage";
import { StocksPage } from "@/pages/StocksPage";
import { StockDetailPage } from "@/pages/StockDetailPage";
import { SectorsPage } from "@/pages/SectorsPage";
import { QuantTradingPage } from "@/pages/QuantTradingPage";

import ThemeExplorerPage from "@/pages/ThemeExplorerPage";
import ChainGraphPage from "@/pages/ChainGraphPage";
import DataManagementPage from "@/pages/DataManagementPage";

export default function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<MarketOverviewPage />} />
        <Route path="/explore" element={<ThemeExplorerPage />} />
        <Route path="/stocks" element={<StocksPage />} />
        <Route path="/stocks/:vtSymbol" element={<StockDetailPage />} />
        <Route path="/quant" element={<QuantTradingPage />} />
        <Route path="/chain" element={<ChainGraphPage />} />
        <Route path="/data" element={<DataManagementPage />} />
        {/* Legacy routes */}
        <Route path="/sectors" element={<SectorsPage />} />
        <Route path="/data-sync" element={<DataManagementPage />} />
      </Routes>
    </AppShell>
  );
}
