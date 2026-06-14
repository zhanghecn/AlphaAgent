import { Play, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { BacktestParams } from "@/features/quant/constants";
import { QuantBoardSelector } from "@/features/quant/RecommendationsPanel";
import { TradingDateSelector } from "@/features/quant/TradingDateSelector";
import type { QuantStrategyOption } from "@/api/quant";

export function BacktestParamsForm({
  params,
  onChange,
  strategies,
  selectedStrategy,
  onStrategyChange,
  isRunning,
  onRun,
  tradingDates,
}: {
  params: BacktestParams;
  onChange: (params: BacktestParams) => void;
  strategies: QuantStrategyOption[];
  selectedStrategy: string;
  onStrategyChange: (strategy: string) => void;
  isRunning: boolean;
  onRun: () => void;
  tradingDates: string[];
}) {
  const setNumber = (key: keyof BacktestParams, value: string) => {
    onChange({ ...params, [key]: Number(value) });
  };

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
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-7">
        <TradingDateSelector
          label="开始日期"
          value={params.start}
          dates={[...tradingDates, params.start]}
          onChange={(start) => onChange({ ...params, start })}
          disabled={isRunning}
          className="items-start gap-1 lg:col-span-2"
          selectClassName="mt-1 h-9 w-full min-w-0"
        />
        <label className="text-sm">
          <span className="text-xs text-muted-foreground">初始资金</span>
          <input
            className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-sm"
            type="number"
            min={100000}
            step={100000}
            value={params.initial_cash}
            onChange={(event) => setNumber("initial_cash", event.target.value)}
          />
        </label>
        <label className="text-sm">
          <span className="text-xs text-muted-foreground">样本股票</span>
          <input
            className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-sm"
            type="number"
            min={20}
            max={5000}
            value={params.max_symbols}
            onChange={(event) => setNumber("max_symbols", event.target.value)}
          />
        </label>
        <label className="text-sm">
          <span className="text-xs text-muted-foreground">最大持仓</span>
          <input
            className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-sm"
            type="number"
            min={1}
            max={30}
            value={params.max_positions}
            onChange={(event) => setNumber("max_positions", event.target.value)}
          />
        </label>
        <label className="text-sm">
          <span className="text-xs text-muted-foreground">最低分</span>
          <input
            className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-sm"
            type="number"
            min={0}
            max={100}
            step={1}
            value={params.min_entry_score}
            onChange={(event) => setNumber("min_entry_score", event.target.value)}
          />
        </label>
        <div className="flex items-end gap-2">
          <Button size="sm" onClick={onRun} disabled={isRunning}>
            {isRunning ? <RefreshCw size={15} className="animate-spin" /> : <Play size={15} />}
            运行组合回测
          </Button>
        </div>
      </div>
      <details className="mt-3 border-t pt-3 text-sm">
        <summary className="cursor-pointer text-muted-foreground">高级执行设置：策略、严格14:30快照、只买 BUY</summary>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <label className="text-sm">
            <span className="text-xs text-muted-foreground">策略</span>
            <select
              className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-sm"
              value={selectedStrategy}
              onChange={(event) => onStrategyChange(event.target.value)}
            >
              {strategies.length === 0 ? (
                <option value={selectedStrategy}>主线强势回踩低吸</option>
              ) : (
                strategies.map((strategy) => (
                  <option key={strategy.id} value={strategy.id}>
                    {strategy.name}
                  </option>
                ))
              )}
            </select>
          </label>
          <label className="text-sm">
            <span className="text-xs text-muted-foreground">执行模型</span>
            <div className="mt-1 flex h-9 items-center rounded-md border bg-muted/30 px-2 text-sm">严格14:30</div>
          </label>
          <label className="text-sm">
            <span className="text-xs text-muted-foreground">执行快照</span>
            <div className="mt-1 flex h-9 items-center rounded-md border bg-muted/30 px-2 text-sm">1分钟 / 14:30快照</div>
          </label>
          <label className="text-sm">
            <span className="text-xs text-muted-foreground">尾盘约束</span>
            <div className="mt-1 flex h-9 items-center rounded-md border bg-muted/30 px-2 text-sm">
              14:30 单点，MA5偏离 {params.tail_entry_ma5_tolerance_pct}%
            </div>
          </label>
          <label className="text-sm">
            <span className="text-xs text-muted-foreground">入场口径</span>
            <div className="mt-1 flex h-9 items-center rounded-md border bg-muted/30 px-2 text-sm">只买 BUY 硬入场</div>
          </label>
        </div>
        <div className="mt-2 text-xs text-muted-foreground">
          普通组合回测固定严格14:30执行，只买 BUY 硬入场信号，WATCH 不会参与买入；其他执行模型只在“执行模型对比”中作为研究对照。
        </div>
      </details>
    </div>
  );
}
