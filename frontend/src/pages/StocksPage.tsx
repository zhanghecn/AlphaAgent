import { StockTable } from "@/features/stocks/StockTable";

export function StocksPage() {
  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold">全 A 股票</h2>
      <StockTable />
    </div>
  );
}
