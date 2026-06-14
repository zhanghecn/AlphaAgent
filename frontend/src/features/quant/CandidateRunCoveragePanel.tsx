import { CalendarCheck } from "lucide-react";
import { useMemo, useState } from "react";
import type { QuantScreenRunItem, QuantStrategyOption, QuantTradingDateItem } from "@/api/quant";
import { InfoCell } from "@/components/InfoCell";
import { Button } from "@/components/ui/button";

const PAGE_SIZE = 20;

export function CandidateRunCoveragePanel({
  screenRuns,
  tradingDates,
  startDate,
  selectedTradeDate,
  strategy,
  onSelectDate,
}: {
  screenRuns: QuantScreenRunItem[];
  tradingDates: QuantTradingDateItem[];
  startDate: string;
  selectedTradeDate: string;
  strategy?: QuantStrategyOption;
  onSelectDate: (tradeDate: string) => void;
}) {
  const [page, setPage] = useState(0);
  const latestRunByDate = latestRuns(screenRuns);
  const dates = coverageDates(tradingDates, startDate);
  const covered = dates.filter((date) => latestRunByDate.has(date));
  const missing = dates.filter((date) => !latestRunByDate.has(date));
  const latestRun = [...latestRunByDate.values()].sort((left, right) => right.trade_date.localeCompare(left.trade_date))[0];
  const coveragePct = dates.length ? (covered.length / dates.length) * 100 : null;
  const descendingDates = useMemo(() => [...dates].reverse(), [dates]);
  const pageCount = Math.max(Math.ceil(descendingDates.length / PAGE_SIZE), 1);
  const currentPage = Math.min(page, pageCount - 1);
  const pageDates = descendingDates.slice(currentPage * PAGE_SIZE, currentPage * PAGE_SIZE + PAGE_SIZE);
  const pageStart = descendingDates.length ? currentPage * PAGE_SIZE + 1 : 0;
  const pageEnd = Math.min((currentPage + 1) * PAGE_SIZE, descendingDates.length);
  const latestBuyCount = buyRecommendationCount(latestRun);
  const latestWatchCount = watchRecommendationCount(latestRun);

  return (
    <section className="rounded-lg border">
      <div className="flex items-center justify-between gap-2 border-b px-3 py-2">
        <div className="flex items-center gap-2">
          <CalendarCheck size={16} />
          <h3 className="text-sm font-semibold">候选运行覆盖</h3>
        </div>
        <span className="text-xs text-muted-foreground">{strategy?.name ?? "当前策略"}</span>
      </div>
      <div className="space-y-3 p-3">
        <div className="grid grid-cols-2 gap-3">
          <InfoCell label="覆盖交易日" value={`${covered.length} / ${dates.length}`} />
          <InfoCell label="覆盖率" value={coveragePct == null ? "--" : `${coveragePct.toFixed(1)}%`} />
          <InfoCell label="缺口交易日" value={missing.length} />
          <InfoCell label="最新同步日" value={latestRun?.trade_date ?? "--"} />
        </div>
        {latestRun && (
          <div className="grid grid-cols-2 gap-3">
            <InfoCell label="最新候选" value={latestRun.recommendation_count} />
            <InfoCell label="BUY候选" value={latestBuyCount} />
            <InfoCell label="WATCH候选" value={latestWatchCount} />
            <InfoCell label="评分股票" value={latestRun.candidate_count} />
          </div>
        )}
        <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
          <span>交易日 {pageStart}-{pageEnd} / {descendingDates.length}</span>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" className="h-7 px-2" disabled={currentPage === 0} onClick={() => setPage((value) => Math.max(value - 1, 0))}>
              上一页
            </Button>
            <Button size="sm" variant="outline" className="h-7 px-2" disabled={currentPage >= pageCount - 1} onClick={() => setPage((value) => Math.min(value + 1, pageCount - 1))}>
              下一页
            </Button>
          </div>
        </div>
        <div className="max-h-80 space-y-1.5 overflow-auto pr-1">
          {pageDates.map((date) => {
            const run = latestRunByDate.get(date);
            const active = date === selectedTradeDate;
            return (
              <button
                key={date}
                type="button"
                className={`flex w-full items-center justify-between rounded-md border px-2 py-1.5 text-left text-xs ${
                  active ? "border-primary bg-muted" : "hover:bg-muted/50"
                }`}
                onClick={() => onSelectDate(date)}
              >
                <span className="tabular-nums">{date}</span>
                <span className="text-muted-foreground">
                  {run
                    ? `#${run.id} · 候选 ${run.recommendation_count} · BUY ${buyRecommendationCount(run)} · WATCH ${watchRecommendationCount(run)}`
                    : "未运行"}
                </span>
              </button>
            );
          })}
        </div>
        {missing.length > 0 && (
          <div className="rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300">
            仍有 {missing.length} 个交易日没有当前策略的筛选记录。生成区间候选会从起点补到本地最新交易日。
          </div>
        )}
        {missing.length === 0 && dates.length > 0 && (
          <div className="rounded-md border p-2 text-xs text-muted-foreground">当前起点之后的交易日已全部有筛选记录。</div>
        )}
        {missing[0] && (
          <Button size="sm" variant="outline" className="w-full" onClick={() => onSelectDate(missing[0])}>
            查看最早缺口 {missing[0]}
          </Button>
        )}
      </div>
    </section>
  );
}

function latestRuns(runs: QuantScreenRunItem[]): Map<string, QuantScreenRunItem> {
  const byDate = new Map<string, QuantScreenRunItem>();
  for (const run of runs) {
    const current = byDate.get(run.trade_date);
    if (!current || run.id > current.id) {
      byDate.set(run.trade_date, run);
    }
  }
  return byDate;
}

function coverageDates(items: QuantTradingDateItem[], startDate: string): string[] {
  const dates = items.map((item) => item.trade_date).sort();
  if (!startDate) return dates;
  return dates.filter((date) => date >= startDate);
}

function buyRecommendationCount(run?: QuantScreenRunItem): number {
  if (!run) return 0;
  return Math.max(Number(run.buy_recommendation_count ?? 0), 0);
}

function watchRecommendationCount(run?: QuantScreenRunItem): number {
  if (!run) return 0;
  const explicit = run.watch_recommendation_count;
  if (explicit != null) return Math.max(Number(explicit), 0);
  return Math.max(Number(run.recommendation_count ?? 0) - buyRecommendationCount(run), 0);
}
