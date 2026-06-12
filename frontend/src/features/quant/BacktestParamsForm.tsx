import { Play, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { BacktestParams } from "@/features/quant/constants";
import { QuantBoardSelector } from "@/features/quant/RecommendationsPanel";

export function BacktestParamsForm({
  params,
  onChange,
  isRunning,
  onRun,
}: {
  params: BacktestParams;
  onChange: (params: BacktestParams) => void;
  isRunning: boolean;
  onRun: () => void;
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
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
        <label className="text-sm">
          <span className="text-xs text-muted-foreground">开始日期</span>
          <input
            className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-sm"
            type="date"
            value={params.start}
            onChange={(event) => onChange({ ...params, start: event.target.value })}
          />
        </label>
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
          <label className="flex h-9 items-center gap-2 rounded-md border px-2 text-sm">
            <input
              type="checkbox"
              checked={params.strict_entry}
              onChange={(event) => onChange({ ...params, strict_entry: event.target.checked })}
            />
            严格入场
          </label>
          <Button size="sm" onClick={onRun} disabled={isRunning}>
            {isRunning ? <RefreshCw size={15} className="animate-spin" /> : <Play size={15} />}
            运行
          </Button>
        </div>
      </div>
      <details className="mt-3 border-t pt-3 text-sm">
        <summary className="cursor-pointer text-muted-foreground">高级执行设置：尾盘分钟线、强制分钟成交、MA5 偏离</summary>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <label className="flex h-9 items-center gap-2 rounded-md border px-2 text-sm">
            <input
              type="checkbox"
              checked={params.intraday_entry}
              onChange={(event) => onChange({ ...params, intraday_entry: event.target.checked })}
            />
            尝试尾盘分钟入场
          </label>
          <label className="flex h-9 items-center gap-2 rounded-md border px-2 text-sm">
            <input
              type="checkbox"
              checked={params.minute_entry_required}
              onChange={(event) => onChange({ ...params, minute_entry_required: event.target.checked })}
            />
            强制分钟成交
          </label>
          <label className="text-sm">
            <span className="text-xs text-muted-foreground">尾盘开始</span>
            <input
              className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-sm"
              type="time"
              value={params.tail_entry_start}
              onChange={(event) => onChange({ ...params, tail_entry_start: event.target.value })}
            />
          </label>
          <label className="text-sm">
            <span className="text-xs text-muted-foreground">尾盘结束</span>
            <input
              className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-sm"
              type="time"
              value={params.tail_entry_end}
              onChange={(event) => onChange({ ...params, tail_entry_end: event.target.value })}
            />
          </label>
          <label className="text-sm">
            <span className="text-xs text-muted-foreground">MA5允许偏离%</span>
            <input
              className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-sm"
              type="number"
              min={0.1}
              max={5}
              step={0.1}
              value={params.tail_entry_ma5_tolerance_pct}
              onChange={(event) => setNumber("tail_entry_ma5_tolerance_pct", event.target.value)}
            />
          </label>
        </div>
      </details>
    </div>
  );
}
