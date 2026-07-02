import type { BacktestParams } from "@/features/quant/constants";
import { QuantBoardSelector } from "@/features/quant/RecommendationsPanel";
import { TradingDateSelector } from "@/features/quant/TradingDateSelector";
import type { QuantStrategyOption } from "@/api/quant";

export function BacktestParamsForm({
  params,
  onChange,
  strategies,
  selectedStrategy,
  isRunning,
  tradingDates,
}: {
  params: BacktestParams;
  onChange: (params: BacktestParams) => void;
  strategies: QuantStrategyOption[];
  selectedStrategy: string;
  isRunning: boolean;
  tradingDates: string[];
}) {
  const selectedStrategyMeta = strategies.find((strategy) => strategy.id === selectedStrategy);

  return (
    <div className="rounded-lg border p-3">
      <div className="mb-3 border-b pb-3">
        <QuantBoardSelector
          selectedBoards={params.included_boards}
          activeBoards={params.included_boards}
          onChange={(included_boards) => onChange({ ...params, included_boards })}
          isRunning={isRunning}
        />
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1.5fr)_120px_120px]">
        <TradingDateSelector
          label="开始日期"
          value={params.start}
          dates={[...tradingDates, params.start]}
          onChange={(start) => onChange({ ...params, start })}
          disabled={isRunning}
          className="items-start gap-1 lg:col-span-2"
          selectClassName="mt-1 h-9 w-full min-w-0"
        />
        <div className="text-sm">
          <div className="text-xs text-muted-foreground">策略</div>
          <div className="mt-1 flex h-9 items-center rounded-md border bg-muted/30 px-2 text-sm">
            {selectedStrategyMeta?.name ?? "主线龙回头回踩低吸"}
          </div>
        </div>
        <div className="text-sm">
          <div className="text-xs text-muted-foreground">规则</div>
          <div className="mt-1 flex h-9 items-center rounded-md border bg-muted/30 px-2 text-sm">
            每日Top20独立评估
          </div>
        </div>
      </div>
      <div className="mt-3 border-t pt-3 text-xs text-muted-foreground">
        历史研究使用日线口径：D日收盘产生信号，D+1按日线开盘价执行；页面默认只看收益率和买卖点。
        {selectedStrategyMeta?.default_min_entry_score ? ` 当前策略默认最低分 ${selectedStrategyMeta.default_min_entry_score}。` : ""}
      </div>
    </div>
  );
}
