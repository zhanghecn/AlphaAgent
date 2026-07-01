import { useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { fetchMarketTimingPanel } from "@/api/marketTiming";
import { AccuracyMatrix } from "@/features/market-timing/AccuracyMatrix";
import { FactorBreakdown } from "@/features/market-timing/FactorBreakdown";
import { TimingChart } from "@/features/market-timing/TimingChart";
import { TimingHero } from "@/features/market-timing/TimingHero";
import { Button } from "@/components/ui/button";

export function MarketTimingPage() {
  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey: ["marketTimingPanel"],
    queryFn: () => fetchMarketTimingPanel(),
    staleTime: 30 * 60 * 1000, // 与后端缓存对齐
  });

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl font-bold tracking-tight">大盘择时</h1>
          <p className="text-sm text-muted-foreground">
            金手指 = 看多 · 银手指 = 看空（基于 7 指数加权 + 市场广度 + 顶部结构因子）
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => refetch()}
          disabled={isFetching}
          className="gap-1.5"
        >
          <RefreshCw size={14} className={isFetching ? "animate-spin" : ""} />
          {isFetching ? "计算中" : "刷新"}
        </Button>
      </header>

      <TimingHero overview={data?.overview ?? null} loading={isLoading} />

      <TimingChart chart={data?.chart ?? null} loading={isLoading} />

      <div className="grid gap-5 lg:grid-cols-2">
        <AccuracyMatrix
          accuracy={data?.accuracy ?? null}
          loading={isLoading}
          sampleRange={data?.sample_range}
        />
        <FactorBreakdown overview={data?.overview ?? null} loading={isLoading} />
      </div>

      <p className="pb-4 text-center text-xs text-muted-foreground/70">
        信号只用 ≤t 数据(无未来函数) · 准确率含 bootstrap 置信区间 · 样本期单边牛市, 银手指有效性待更长历史验证
      </p>
    </div>
  );
}
