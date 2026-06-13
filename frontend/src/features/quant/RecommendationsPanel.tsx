import { Link } from "react-router-dom";
import { AlertTriangle, Database, Play, RefreshCw, ShieldCheck } from "lucide-react";
import { cn, formatPct, priceColorClass } from "@/lib/utils";
import { formatNumber, numberValue } from "@/lib/backtest-utils";
import { QUANT_BOARD_OPTIONS, boardLabels, type QuantBoard } from "@/features/quant/constants";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { TradingDateSelector } from "@/features/quant/TradingDateSelector";
import type { QuantRecommendation, QuantScreenRunItem } from "@/api/quant";

export function RecommendationsPanel({
  isLoading,
  isError,
  error,
  items,
  tradeDate,
  runId,
  strategyVersion,
  includedBoards,
  screenRuns,
  tradingDates,
  selectedTradeDate,
  onSelectedTradeDateChange,
  selectedBoards,
  onSelectedBoardsChange,
  status,
  message,
  syncedCount,
  onRetry,
  onRunScreen,
  isRunningScreen,
}: {
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  items: QuantRecommendation[];
  tradeDate?: string;
  runId?: number | null;
  strategyVersion?: string;
  includedBoards?: string[];
  screenRuns: QuantScreenRunItem[];
  tradingDates: string[];
  selectedTradeDate: string;
  onSelectedTradeDateChange: (tradeDate: string) => void;
  selectedBoards: string[];
  onSelectedBoardsChange: (boards: string[]) => void;
  status?: string;
  message?: string;
  syncedCount: number;
  onRetry: () => void;
  onRunScreen: () => void;
  isRunningScreen: boolean;
}) {
  if (isLoading) return <LoadingState rows={6} />;
  if (isError) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "加载量化推荐失败"}
        onRetry={onRetry}
      />
    );
  }

  const activeBoards = includedBoards?.length ? includedBoards : selectedBoards;
  const latestRunByDate = new Map<string, QuantScreenRunItem>();
  for (const run of screenRuns) {
    const current = latestRunByDate.get(run.trade_date);
    if (!current || run.id > current.id) {
      latestRunByDate.set(run.trade_date, run);
    }
  }
  const availableDates = Array.from(
    new Set([...tradingDates, ...screenRuns.map((run) => run.trade_date), selectedTradeDate].filter(Boolean))
  );

  return (
    <section className="rounded-lg border">
      <div className="space-y-3 border-b px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <ShieldCheck size={16} />
            <h2 className="text-sm font-semibold">量化候选</h2>
          </div>
          <div className="text-xs text-muted-foreground">
            {tradeDate ?? "--"} · {runId ? `运行 #${runId}` : "未运行"} · {strategyVersion ?? "--"} · 分组同步 {syncedCount} 只
          </div>
        </div>
        <TradingDateSelector
          label="起始交易日"
          value={selectedTradeDate}
          dates={availableDates}
          onChange={onSelectedTradeDateChange}
          getOptionLabel={(date) => {
            const run = latestRunByDate.get(date);
            return run ? `${date} · #${run.id} · 候选 ${run.recommendation_count}` : `${date} · 未运行`;
          }}
        />
        <QuantBoardSelector
          selectedBoards={selectedBoards}
          activeBoards={activeBoards}
          onChange={onSelectedBoardsChange}
          onRun={onRunScreen}
          isRunning={isRunningScreen}
        />
      </div>
      {items.length === 0 ? (
        <QuantEmptyState
          status={status}
          message={message}
        />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-14">排名</TableHead>
              <TableHead>股票</TableHead>
              <TableHead>动作</TableHead>
              <TableHead className="text-right">总分</TableHead>
              <TableHead className="text-right">MA5距离</TableHead>
              <TableHead className="text-right">风险/流动性</TableHead>
              <TableHead>核查</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((item) => {
              const reason = item.reason ?? {};
              const ma5Distance = numberValue(reason.ma5_distance_pct);
              const riskScore = numberValue(reason.risk_score);
              const liquidityScore = numberValue(reason.liquidity_score);
              const failedRules = Array.isArray(reason.failed_rules) ? reason.failed_rules.join(", ") : "";
              const risk = item.risk_control ?? {};
              return (
                <TableRow key={`${item.trade_date}-${item.vt_symbol}`}>
                  <TableCell className="font-medium tabular-nums">{item.rank}</TableCell>
                  <TableCell>
                    <StockIdentityLink name={item.name} vtSymbol={item.vt_symbol} board={item.board} boardLabel={item.board_label} />
                  </TableCell>
                  <TableCell>
                    <span
                      className={cn(
                        "rounded-md border px-2 py-1 text-xs",
                        item.action === "BUY" ? "border-red-200 bg-red-50 text-rise dark:border-red-500/30 dark:bg-red-500/10" : "text-muted-foreground"
                      )}
                    >
                      {item.action === "BUY" ? "买入" : "观察"}
                    </span>
                  </TableCell>
                  <TableCell className="text-right font-medium tabular-nums">
                    {formatNumber(item.total_score, 2)}
                  </TableCell>
                  <TableCell className={cn("text-right tabular-nums", priceColorClass(ma5Distance))}>
                    {formatPct(ma5Distance)}
                  </TableCell>
                  <TableCell className="text-right text-xs text-muted-foreground">
                    {formatNumber(riskScore, 1)} / {formatNumber(liquidityScore, 1)}
                  </TableCell>
                  <TableCell className="max-w-60 text-xs text-muted-foreground">
                    {failedRules || `止损 ${formatPct(numberValue(risk.stop_loss_pct) ? -numberValue(risk.stop_loss_pct)! * 100 : null)}`}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}
    </section>
  );
}

export function QuantBoardSelector({
  selectedBoards,
  activeBoards,
  onChange,
  onRun,
  isRunning,
}: {
  selectedBoards: string[];
  activeBoards: string[];
  onChange: (boards: string[]) => void;
  onRun?: () => void;
  isRunning: boolean;
}) {
  const toggleBoard = (board: QuantBoard, checked: boolean) => {
    const current = new Set(selectedBoards);
    if (checked) {
      current.add(board);
    } else {
      current.delete(board);
    }
    const next = QUANT_BOARD_OPTIONS
      .map((item) => item.value)
      .filter((item) => current.has(item));
    onChange(next.length ? next : ["main"]);
  };

  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-muted-foreground">股票池</span>
        {QUANT_BOARD_OPTIONS.map((option) => (
          <label key={option.value} className="flex h-8 items-center gap-2 rounded-md border px-2 text-sm">
            <input
              type="checkbox"
              checked={selectedBoards.includes(option.value)}
              onChange={(event) => toggleBoard(option.value, event.target.checked)}
            />
            {option.label}
          </label>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-muted-foreground">
          当前结果: {boardLabels(activeBoards)}
        </span>
        {onRun && (
          <Button size="sm" onClick={onRun} disabled={isRunning}>
            {isRunning ? <RefreshCw size={15} className="animate-spin" /> : <Play size={15} />}
            生成区间候选
          </Button>
        )}
      </div>
    </div>
  );
}

function QuantEmptyState({
  status,
  message,
}: {
  status?: string;
  message?: string;
}) {
  const unavailable = status === "unavailable";
  return (
    <div className="p-4">
      <div className={cn("rounded-lg border p-4", unavailable ? "border-amber-200 bg-amber-50 dark:border-amber-500/30 dark:bg-amber-500/10" : "bg-muted/20")}>
        <div className="flex items-start gap-3">
          {unavailable ? <AlertTriangle size={18} className="mt-0.5 text-amber-700 dark:text-amber-400" /> : <Database size={18} className="mt-0.5 text-muted-foreground" />}
          <div className="min-w-0 flex-1">
            <div className="font-medium">{unavailable ? "量化数据还不能读取" : "还没有量化候选"}</div>
            <div className="mt-1 text-sm text-muted-foreground">
              {message || "选择起始交易日后生成区间候选。系统会按真实交易日逐日打分并落库。"}
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button asChild size="sm" variant="outline">
                <Link to="/data">
                  <Database size={15} />
                  查看数据状态
                </Link>
              </Button>
            </div>
            {unavailable && (
              <div className="mt-3 text-xs text-amber-700 dark:text-amber-400">
                先配置 PostgreSQL 的 DATABASE_URL，并同步股票清单、日线和可选财报/资金流数据。
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
