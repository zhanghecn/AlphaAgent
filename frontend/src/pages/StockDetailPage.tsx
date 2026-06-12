/**
 * StockResearchPage — 个股投研 (重写 StockDetailPage)
 *
 * Core innovation: "Identity Card" showing all concepts a stock belongs to,
 * each with today's change_pct — so users see which "mainline" is driving it.
 *
 * Layout: Quote header → Identity card (concept tag cloud) → K-line →
 *         Business + Financials → Fund flow + Events
 */
import { useParams, Link } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  fetchStockDetail,
  fetchStockSnapshot,
  fetchStockBusiness,
} from "@/api/stocks";
import { fetchConceptCards } from "@/api/research";
import { fetchLimitPools } from "@/api/market";
import { createSymbolBacktest, type BacktestAudit, type BacktestTrade } from "@/api/quant";
import { StockQuoteHeader } from "@/features/stocks/StockQuoteHeader";
import { StockKlineChart, type KlineMarker } from "@/features/stocks/StockKlineChart";
import { StockIndicatorPanel } from "@/features/stocks/StockIndicatorPanel";
import { StockFinanceChart } from "@/features/stocks/StockFinanceChart";
import { ConceptTag } from "@/components/ConceptTag";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatAmount, formatPct, formatPrice, priceColorClass, cn } from "@/lib/utils";
import type { ConceptCard, ShenwanClassification, StockConceptCardsResponse, ConceptHint } from "@/types/research";
import type { StockSnapshot, StockBusiness as StockBusinessType } from "@/api/types";
import {
  Fingerprint,
  ShieldCheck,
  Database,
  Radio,
  Building2,
  Flame,
  ArrowRight,
  TrendingUp,
  BarChart3,
  RefreshCw,
  FileText,
} from "lucide-react";

export function StockDetailPage() {
  const { vtSymbol } = useParams<{ vtSymbol: string }>();
  const [backtestStart, setBacktestStart] = useState("2026-02-02");
  const [selectedBacktestMarkerId, setSelectedBacktestMarkerId] = useState<string | null>(null);

  const quoteQuery = useQuery({
    queryKey: ["stock-detail", vtSymbol],
    queryFn: () => fetchStockDetail(vtSymbol!),
    enabled: !!vtSymbol,
  });

  const snapshotQuery = useQuery({
    queryKey: ["stock-snapshot", vtSymbol],
    queryFn: () => fetchStockSnapshot(vtSymbol!),
    enabled: !!vtSymbol,
  });

  // Concept cards — the core innovation
  const conceptQuery = useQuery({
    queryKey: ["conceptCards", vtSymbol],
    queryFn: () => fetchConceptCards(vtSymbol!),
    staleTime: 30_000,
    enabled: !!vtSymbol,
  });

  // Business data
  const businessQuery = useQuery({
    queryKey: ["stock-business", vtSymbol],
    queryFn: () => fetchStockBusiness(vtSymbol!),
    enabled: !!vtSymbol,
  });

  // Limit pool data — for seal order (封单) display
  const limitPoolQuery = useQuery({
    queryKey: ["limit-pools-seal", vtSymbol],
    queryFn: () => fetchLimitPools(),
    staleTime: 60_000,
    enabled: !!vtSymbol,
  });

  const sealInfo = useMemo(() => {
    const pools = limitPoolQuery.data?.pools ?? {};
    const stockCode = vtSymbol!.split(".")[0];
    // Backend pool keys: zt, zt_previous, strong, zbgc, dtgc
    for (const poolKey of ["zt", "strong", "zbgc", "dtgc"] as const) {
      const group = pools[poolKey];
      const items = group?.items ?? [];
      const match = items.find((item) => item.symbol === stockCode);
      if (match) {
        return {
          limit_amount: match.limit_amount ?? null,
          limit_pool_type: poolKey,
          continuous_limit_up_count: match.limit_up_count ?? null,
        };
      }
    }
    return null;
  }, [limitPoolQuery.data, vtSymbol]);

  const singleBacktestMutation = useMutation({
    mutationFn: () =>
      createSymbolBacktest({
        vt_symbol: vtSymbol!,
        start: backtestStart,
        initial_cash: 1_000_000,
        persist: true,
        min_entry_score: 68,
        strict_entry: true,
        intraday_entry: true,
        minute_entry_required: false,
        tail_entry_start: "14:30",
        tail_entry_end: "14:57",
        tail_entry_ma5_tolerance_pct: 1.5,
      }),
  });
  const backtestAudit = singleBacktestMutation.data?.audit;
  const backtestMarkers = useMemo(
    () => backtestTradesToMarkers(backtestAudit?.trades ?? [], backtestAudit),
    [backtestAudit]
  );
  const selectedBacktestMarker = useMemo(
    () => backtestMarkers.find((marker) => marker.id === selectedBacktestMarkerId) ?? backtestMarkers[0] ?? null,
    [backtestMarkers, selectedBacktestMarkerId]
  );

  useEffect(() => {
    setSelectedBacktestMarkerId((current) => {
      if (current && backtestMarkers.some((marker) => marker.id === current)) return current;
      return backtestMarkers[0]?.id ?? null;
    });
  }, [backtestMarkers]);

  const handleBacktestMarkerClick = useCallback((marker: KlineMarker) => {
    setSelectedBacktestMarkerId(marker.id ?? null);
  }, []);

  if (!vtSymbol) return <ErrorState message="无效的股票代码" />;

  if (quoteQuery.isLoading) return <LoadingState rows={6} />;
  if (quoteQuery.isError)
    return (
      <ErrorState
        message={
          quoteQuery.error instanceof Error
            ? quoteQuery.error.message
            : "加载股票详情失败"
        }
        onRetry={() => quoteQuery.refetch()}
      />
    );

  const quote = quoteQuery.data!;
  const snapshot = snapshotQuery.data as StockSnapshot | undefined;
  const missing = snapshot?.data_quality?.missing ?? [];
  const sources: string[] = [];

  const concepts = conceptQuery.data;
  const business = businessQuery.data as StockBusinessType | null | undefined;

  return (
    <div className="space-y-5">
      {/* Quote header (reused) */}
      <StockQuoteHeader quote={quote} sealInfo={sealInfo} />

      {/* Data evidence bar */}
      <StockDataEvidence sources={sources} missing={missing} />

      {/* ⭐ Identity Card — Core Innovation */}
      <IdentityCard
        conceptData={concepts}
        isLoading={conceptQuery.isLoading}
      />

      <SingleStockBacktestPanel
        vtSymbol={vtSymbol}
        start={backtestStart}
        onStartChange={setBacktestStart}
        result={singleBacktestMutation.data}
        audit={backtestAudit}
        isRunning={singleBacktestMutation.isPending}
        error={singleBacktestMutation.error}
        onRun={() => singleBacktestMutation.mutate()}
      />

      {/* K-line chart */}
      <div className="rounded-lg border p-3 sm:p-4">
        <StockKlineChart
          vtSymbol={vtSymbol}
          markers={backtestMarkers}
          selectedMarkerId={selectedBacktestMarker?.id ?? null}
          onMarkerClick={handleBacktestMarkerClick}
        />
        <BacktestMarkerInsight marker={selectedBacktestMarker} audit={backtestAudit} />
      </div>

      {/* Technical indicators */}
      <section className="rounded-lg border p-3 sm:p-4">
        <h3 className="mb-3 text-sm font-medium">技术指标</h3>
        <StockIndicatorPanel vtSymbol={vtSymbol} />
      </section>

      {/* Two-column: Business + Financial summary */}
      <div className="grid gap-5 lg:grid-cols-2">
        {/* Business composition */}
        <section className="rounded-lg border p-3 sm:p-4">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-medium">
            <Building2 size={14} />
            主营业务
          </h3>
          {business ? (
            <BusinessComposition business={business} />
          ) : (
            <div className="py-4 text-sm text-muted-foreground">
              {businessQuery.isLoading ? "加载中..." : "暂无业务数据"}
            </div>
          )}
        </section>

        {/* Shenwan hierarchy + sector memberships */}
        <section className="rounded-lg border p-3 sm:p-4">
          <h3 className="mb-3 text-sm font-medium">行业归属</h3>
          <ShenwanHierarchy shenwan={concepts?.shenwan} />
        </section>
      </div>

      {/* Historical Financial Reports */}
      <section className="rounded-lg border p-3 sm:p-4">
        <h3 className="mb-3 flex items-center gap-2 text-sm font-medium">
          <TrendingUp size={14} />
          历史财报
        </h3>
        <StockFinanceChart vtSymbol={vtSymbol} />
      </section>
    </div>
  );
}

function SingleStockBacktestPanel({
  vtSymbol,
  start,
  onStartChange,
  result,
  audit,
  isRunning,
  error,
  onRun,
}: {
  vtSymbol: string;
  start: string;
  onStartChange: (value: string) => void;
  result: Awaited<ReturnType<typeof createSymbolBacktest>> | undefined;
  audit?: BacktestAudit;
  isRunning: boolean;
  error: unknown;
  onRun: () => void;
}) {
  const metrics = result?.metrics;
  const trades = audit?.trades ?? result?.trades ?? [];
  const events = audit?.events ?? [];

  return (
    <section className="rounded-lg border p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <BarChart3 size={15} />
            单股回测
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">
            只用 {vtSymbol} 的历史数据跑同一套入场/退出规则。若没有交易，表示策略没有给出可执行信号。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <input
            className="h-9 rounded-md border bg-background px-2 text-sm"
            type="date"
            value={start}
            onChange={(event) => onStartChange(event.target.value)}
          />
          <Button size="sm" onClick={onRun} disabled={isRunning}>
            {isRunning ? <RefreshCw size={15} className="animate-spin" /> : <BarChart3 size={15} />}
            运行单股回测
          </Button>
        </div>
      </div>

      {Boolean(error) && (
        <div className="mt-3 rounded-md border border-red-200 bg-red-50 p-2 text-sm text-fall">
          {error instanceof Error ? error.message : "单股回测失败"}
        </div>
      )}

      {result && (
        <div className="mt-4 space-y-4">
          <div className="grid gap-3 text-sm md:grid-cols-5">
            <InfoCell label="状态" value={result.status} />
            <InfoCell label="回测ID" value={result.backtest_id ?? "--"} />
            <InfoCell label="总收益" value={formatPct(metrics?.total_return_pct)} valueClass={priceColorClass(metrics?.total_return_pct)} />
            <InfoCell label="最大回撤" value={formatPct(metrics?.max_drawdown_pct)} valueClass="text-fall" />
            <InfoCell label="胜率" value={metrics?.win_rate == null ? "--" : formatPct(metrics.win_rate * 100)} />
          </div>

          {audit?.method && (
            <div className="rounded-md border bg-muted/30 p-3 text-sm">
              <div className="flex items-center gap-2 font-medium">
                <FileText size={14} />
                策略口径
              </div>
              <div className="mt-2 grid gap-2 md:grid-cols-2">
                <InfoCell label="候选生成" value={audit.method.signal_timing} />
                <InfoCell label="执行时点" value={audit.method.execution_timing} />
                <InfoCell label="入场过滤" value={`最低分 ${audit.method.entry_filter?.min_entry_score ?? "--"} / 严格 ${audit.method.entry_filter?.strict_entry ? "是" : "否"}`} />
                <InfoCell label="执行模式" value={audit.method.execution?.intraday_entry ? `尾盘 ${audit.method.execution.tail_entry_window}` : "次日开盘"} />
              </div>
            </div>
          )}

          {trades.length === 0 ? (
            <div className="rounded-md border p-3 text-sm text-muted-foreground">
              当前区间没有买卖点。常见原因：入场分不足、严格入场条件未满足、日线不足 80 根，或分钟尾盘规则没有触发。
            </div>
          ) : (
            <div className="overflow-hidden rounded-lg border">
              <div className="border-b px-3 py-2 text-sm font-medium">买卖点</div>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>日期</TableHead>
                    <TableHead>方向</TableHead>
                    <TableHead className="text-right">价格</TableHead>
                    <TableHead className="text-right">数量</TableHead>
                    <TableHead className="text-right">盈亏</TableHead>
                    <TableHead>原因</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {trades.map((trade, index) => (
                    <TableRow key={`${trade.trade_date}-${trade.side}-${index}`}>
                      <TableCell className="tabular-nums">{trade.trade_date}</TableCell>
                      <TableCell>{trade.side === "BUY" ? "买入" : "卖出"}</TableCell>
                      <TableCell className="text-right tabular-nums">{formatPrice(trade.price)}</TableCell>
                      <TableCell className="text-right tabular-nums">{trade.volume.toLocaleString()}</TableCell>
                      <TableCell className={cn("text-right tabular-nums", priceColorClass(trade.pnl))}>
                        {trade.pnl == null ? "--" : formatAmount(trade.pnl)}
                      </TableCell>
                      <TableCell className="text-muted-foreground">{trade.reason ?? "--"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}

          <BacktestEventLog events={events} />
        </div>
      )}
    </section>
  );
}

function BacktestEventLog({ events }: { events: BacktestAudit["events"] }) {
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="border-b px-3 py-2 text-sm font-medium">策略日志</div>
      {events.length === 0 ? (
        <div className="p-3 text-sm text-muted-foreground">暂无订单日志。</div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>日期</TableHead>
              <TableHead>股票</TableHead>
              <TableHead>事件</TableHead>
              <TableHead>执行</TableHead>
              <TableHead className="text-right">价格</TableHead>
              <TableHead>说明</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {events.slice(0, 20).map((event, index) => (
              <TableRow key={`${event.trade_date}-${event.event_type}-${index}`}>
                <TableCell className="tabular-nums">{event.trade_date}</TableCell>
                <TableCell>
                  <StockIdentityLink name={event.name} vtSymbol={event.vt_symbol} board={event.board} boardLabel={event.board_label} />
                </TableCell>
                <TableCell>{stockEventLabel(event.event_type, event.side, event.status)}</TableCell>
                <TableCell className="text-muted-foreground">{executionModeLabel(event.execution_mode)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatPrice(event.price)}</TableCell>
                <TableCell className="text-muted-foreground">{event.message ?? event.reason ?? "--"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}

function BacktestMarkerInsight({ marker, audit }: { marker: KlineMarker | null; audit?: BacktestAudit }) {
  if (!audit) {
    return (
      <div className="mt-4 border-t pt-3 text-sm text-muted-foreground">
        运行单股回测后，买入点和卖出点会标在 K 线上；点击图表上的买/卖标记可查看对应策略口径。
      </div>
    );
  }

  if (!marker) {
    return (
      <div className="mt-4 border-t pt-3 text-sm text-muted-foreground">
        当前回测没有产生可标注的成交点。请先查看上方“单股回测”的空结果原因和策略日志。
      </div>
    );
  }

  const isBuy = marker.side === "BUY";
  return (
    <section className="mt-4 border-t pt-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">{marker.title ?? (isBuy ? "买入策略说明" : "卖出策略说明")}</h3>
          <p className="mt-1 max-w-4xl text-sm text-muted-foreground">{marker.strategy}</p>
        </div>
        <Badge variant={isBuy ? "default" : "secondary"} className="rounded-md">
          {isBuy ? "买入点" : "卖出点"}
        </Badge>
      </div>

      <div className="mt-3 grid gap-3 text-sm md:grid-cols-5">
        <InfoCell label="成交日期" value={marker.tradeDate ?? marker.time} />
        <InfoCell label="信号日期" value={marker.signalDate ?? marker.tradeDate ?? marker.time} />
        <InfoCell label="执行方式" value={executionModeLabel(marker.executionMode)} />
        <InfoCell label="成交价格" value={formatPrice(marker.price)} />
        <InfoCell label="盈亏" value={marker.pnl == null ? "--" : formatAmount(marker.pnl)} valueClass={priceColorClass(marker.pnl)} />
      </div>

      <div className="mt-3 grid gap-3 text-sm lg:grid-cols-3">
        <InsightBlock title="信号" text={marker.signalText} />
        <InsightBlock title="执行" text={marker.executionText} />
        <InsightBlock title="原因" text={marker.reasonText} />
      </div>

      {marker.evidence && marker.evidence.length > 0 && (
        <div className="mt-3">
          <div className="mb-2 text-xs text-muted-foreground">回测证据</div>
          <div className="grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
            {marker.evidence.map((item) => (
              <InfoCell key={item.label} label={item.label} value={item.value} valueClass={item.valueClass} />
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function InsightBlock({ title, text }: { title: string; text?: string }) {
  return (
    <div className="rounded-md border bg-muted/20 p-3">
      <div className="text-xs text-muted-foreground">{title}</div>
      <div className="mt-1 leading-6">{text || "--"}</div>
    </div>
  );
}

function backtestTradesToMarkers(trades: BacktestTrade[], audit?: BacktestAudit): KlineMarker[] {
  return trades.map((trade, index) => {
    const execution = markerExecutionRaw(trade);
    const executionMode = getRawText(execution, "mode");
    const isBuy = trade.side === "BUY";
    const signalDate = isBuy ? getRawText(execution, "reference_date") : getRawText(execution, "signal_date");
    const executeDate = getRawText(execution, "execute_date") ?? trade.trade_date;
    return {
      id: `${trade.trade_date}-${trade.side}-${trade.vt_symbol}-${index}`,
      time: trade.trade_date,
      tradeDate: trade.trade_date,
      signalDate,
      executeDate,
      side: trade.side,
      price: trade.price,
      volume: trade.volume,
      amount: trade.amount,
      fee: trade.fee,
      pnl: trade.pnl,
      executionMode,
      title: markerTitle(trade),
      strategy: markerStrategyText(trade, audit),
      signalText: markerSignalText(trade, audit),
      executionText: markerExecutionText(trade, execution),
      reasonText: markerReasonText(trade),
      evidence: markerEvidence(trade, execution),
      raw: trade.raw,
      text: isBuy ? `买 ${formatPrice(trade.price)}` : `卖 ${formatPrice(trade.price)}`,
    };
  });
}

function markerTitle(trade: BacktestTrade) {
  if (trade.side === "BUY") return "买入信号：主线强势回踩低吸";
  return `卖出信号：${exitReasonLabel(trade.reason)}`;
}

function markerStrategyText(trade: BacktestTrade, audit?: BacktestAudit) {
  if (trade.side === "BUY") {
    const minScore = audit?.method?.entry_filter?.min_entry_score;
    const strict = audit?.method?.entry_filter?.strict_entry;
    const window = audit?.method?.execution?.tail_entry_window;
    return [
      "历史逐日动态候选回测：只使用信号日及以前可见数据打分。",
      `入场要求${minScore == null ? "" : `总分不低于 ${minScore}`}${strict ? "，并满足严格入场条件" : ""}。`,
      window ? `执行优先观察 D+1 尾盘 ${window} 是否接近可见 MA5。` : "",
    ].filter(Boolean).join(" ");
  }
  return "退出规则在持仓后的每个收盘日检查止损、止盈、移动止损和时间止损；D 日收盘确认信号，D+1 开盘才允许成交。";
}

function markerSignalText(trade: BacktestTrade, audit?: BacktestAudit) {
  if (trade.side === "BUY") {
    const raw = safeRaw(trade.raw);
    const return20 = getRawNumber(raw, "return_20d");
    const indexReturn20 = getRawNumber(raw, "index_return_20d");
    const ma5Distance = getRawNumber(raw, "ma5_distance_pct");
    const scoreText = audit?.method?.entry_filter?.min_entry_score == null
      ? "达到入场过滤条件"
      : `达到最低入场分 ${audit.method.entry_filter.min_entry_score}`;
    return [
      `信号日收盘后重新打分，${scoreText}。`,
      return20 == null ? "" : `近 20 日收益 ${formatPct(return20)}`,
      indexReturn20 == null ? "" : `同期指数 ${formatPct(indexReturn20)}`,
      ma5Distance == null ? "" : `收盘距 MA5 ${formatPct(ma5Distance)}`,
    ].filter(Boolean).join("；");
  }

  const execution = markerExecutionRaw(trade);
  const signalDate = getRawText(execution, "signal_date");
  return `${signalDate ?? "信号日"} 收盘后触发 ${exitReasonLabel(trade.reason)}，当天只记录卖出计划，不使用未发生的次日开盘价。`;
}

function markerExecutionText(trade: BacktestTrade, execution: Record<string, unknown>) {
  const mode = getRawText(execution, "mode");
  const modeLabel = executionModeLabel(mode);
  if (trade.side === "BUY") {
    if (mode === "minute_tail_ma5") {
      const barTime = getRawText(execution, "bar_time");
      const distance = getRawNumber(execution, "ma5_distance_pct");
      return `D+1 尾盘分钟线触发，${barTime ? `成交分钟 ${barTime}，` : ""}成交方式 ${modeLabel}${distance == null ? "" : `，距 MA5 ${formatPct(distance)}`}。`;
    }
    if (mode === "daily_next_open_fallback") {
      const count = getRawNumber(execution, "minute_bar_count");
      return `尾盘分钟线缺失或未触发，按配置回退为 D+1 开盘成交${count == null ? "" : `；当日分钟线 ${count} 根`}。`;
    }
    return `按 ${modeLabel} 执行成交。`;
  }

  const signalDate = getRawText(execution, "signal_date");
  const executeDate = getRawText(execution, "execute_date") ?? trade.trade_date;
  return `${signalDate ?? "D 日"} 收盘出现退出信号，${executeDate} 开盘撮合成交；成交价已计入滑点、佣金和卖出印花税。`;
}

function markerReasonText(trade: BacktestTrade) {
  if (trade.side === "BUY") {
    const raw = safeRaw(trade.raw);
    const washout = safeRaw(raw.washout);
    const drawdown = getRawNumber(washout, "drawdown_from_20d_high");
    const volumeRatio = getRawNumber(washout, "volume_ratio_5d_20d");
    const parts = [
      "策略寻找相对强势、趋势未破坏、回踩接近 MA5 的候选。",
      drawdown == null ? "" : `较 20 日高点回撤 ${formatPct(drawdown)}`,
      volumeRatio == null ? "" : `5/20 日量比 ${formatNumber(volumeRatio, 2)}`,
    ].filter(Boolean);
    return parts.join("；");
  }
  return exitReasonDescription(trade.reason);
}

function markerEvidence(trade: BacktestTrade, execution: Record<string, unknown>): KlineMarker["evidence"] {
  const raw = safeRaw(trade.raw);
  const rows: Array<{ label: string; value: string; valueClass?: string }> = [];
  if (trade.side === "BUY") {
    pushPctEvidence(rows, "20日收益", getRawNumber(raw, "return_20d"));
    pushPctEvidence(rows, "60日收益", getRawNumber(raw, "return_60d"));
    pushPctEvidence(rows, "60日回撤", getRawNumber(raw, "max_drawdown_60d"));
    pushPriceEvidence(rows, "MA5", getRawNumber(raw, "ma5"));
    pushPctEvidence(rows, "距MA5", getRawNumber(raw, "ma5_distance_pct"));
    pushNumberEvidence(rows, "资金热度代理", getRawNumber(raw, "smart_money_proxy_score"));
    pushNumberEvidence(rows, "资金流分", getRawNumber(raw, "fund_flow_score"));
    pushNumberEvidence(rows, "热度排名分", getRawNumber(raw, "hot_rank_score"));
    pushNumberEvidence(rows, "龙虎榜分", getRawNumber(raw, "lhb_score"));
    pushNumberEvidence(rows, "分钟线数量", getRawNumber(execution, "minute_bar_count"), 0);
    const window = getRawText(execution, "window");
    if (window) rows.push({ label: "尾盘窗口", value: window });
    return rows;
  }
  const entryDate = getRawText(execution, "entry_date");
  const signalDate = getRawText(execution, "signal_date");
  const executeDate = getRawText(execution, "execute_date");
  if (entryDate) rows.push({ label: "买入日期", value: entryDate });
  if (signalDate) rows.push({ label: "信号日期", value: signalDate });
  if (executeDate) rows.push({ label: "成交日期", value: executeDate });
  rows.push({ label: "退出原因", value: exitReasonLabel(trade.reason) });
  return rows;
}

function markerExecutionRaw(trade: BacktestTrade) {
  const raw = safeRaw(trade.raw);
  return raw.execution && typeof raw.execution === "object" && !Array.isArray(raw.execution)
    ? raw.execution as Record<string, unknown>
    : raw;
}

function safeRaw(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function getRawText(raw: Record<string, unknown>, key: string) {
  const value = raw[key];
  return typeof value === "string" && value.length > 0 ? value : null;
}

function getRawNumber(raw: Record<string, unknown>, key: string) {
  const value = raw[key];
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function pushPctEvidence(
  rows: Array<{ label: string; value: string; valueClass?: string }>,
  label: string,
  value: number | null
) {
  if (value == null) return;
  rows.push({ label, value: formatPct(value), valueClass: priceColorClass(value) });
}

function pushPriceEvidence(rows: Array<{ label: string; value: string }>, label: string, value: number | null) {
  if (value == null) return;
  rows.push({ label, value: formatPrice(value) });
}

function pushNumberEvidence(
  rows: Array<{ label: string; value: string }>,
  label: string,
  value: number | null,
  digits = 1
) {
  if (value == null) return;
  rows.push({ label, value: formatNumber(value, digits) });
}

function formatNumber(value: number, digits = 2) {
  return value.toFixed(digits);
}

function exitReasonLabel(reason?: string | null) {
  if (reason === "stop_loss") return "止损";
  if (reason === "take_profit") return "止盈";
  if (reason === "trailing_stop") return "移动止损";
  if (reason === "time_stop") return "时间止损";
  if (reason === "entry_signal") return "入场信号";
  return reason || "--";
}

function exitReasonDescription(reason?: string | null) {
  if (reason === "stop_loss") return "收盘价跌破成本价下方的止损阈值，下一交易日开盘卖出。";
  if (reason === "take_profit") return "收盘价达到设定止盈阈值，下一交易日开盘卖出。";
  if (reason === "trailing_stop") return "持仓后曾创新高，但收盘价从持仓高点回撤超过移动止损阈值，下一交易日开盘卖出。";
  if (reason === "time_stop") return "持仓时间超过策略设定的时间上限，下一交易日开盘卖出。";
  return reason || "--";
}

function InfoCell({ label, value, valueClass }: { label: string; value?: string | number | null; valueClass?: string }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={cn("mt-0.5 font-medium tabular-nums", valueClass)}>{value ?? "--"}</div>
    </div>
  );
}

function stockEventLabel(eventType: string, side?: string, status?: string) {
  const sideLabel = side === "BUY" ? "买入" : side === "SELL" ? "卖出" : side ?? "--";
  if (eventType === "trade") return `${sideLabel}成交`;
  if (status === "rejected") return `${sideLabel}拒绝`;
  if (status === "filled") return `${sideLabel}订单成交`;
  return `${sideLabel}订单`;
}

function executionModeLabel(mode?: string | null) {
  if (mode === "minute_tail_ma5") return "尾盘分钟";
  if (mode === "daily_next_open_fallback") return "开盘回退";
  if (mode === "minute_tail_ma5_required") return "严格分钟";
  if (mode === "daily_next_open") return "次日开盘";
  return mode || "--";
}

// ── Identity Card (core innovation) ──

function IdentityCard({
  conceptData,
  isLoading,
}: {
  conceptData: StockConceptCardsResponse | undefined;
  isLoading: boolean;
}) {
  if (isLoading) return <LoadingState rows={3} />;

  const cards = conceptData?.cards ?? [];
  const shenwan = conceptData?.shenwan;
  const hint = conceptData?.concept_hint;

  // Find the "hottest" concept (highest |change_pct|)
  const hottest: ConceptCard | null = cards.reduce<ConceptCard | null>(
    (prev: ConceptCard | null, curr: ConceptCard) => {
      const prevAbs = Math.abs(prev?.change_pct ?? 0);
      const currAbs = Math.abs(curr.change_pct ?? 0);
      return currAbs > prevAbs ? curr : prev;
    },
    null
  );

  return (
    <section className="rounded-lg border bg-gradient-to-r from-card to-muted/30 p-4 sm:p-5">
      <div className="flex items-center gap-2 mb-3">
        <Fingerprint size={16} className="text-primary" />
        <h3 className="text-sm font-semibold">身份卡片</h3>
        {conceptData && (
          <span className="text-xs text-muted-foreground">
            {conceptData.total_cards} 个概念/行业
          </span>
        )}
      </div>

      {/* ── 概念解读面板 ── */}
      {hint && hint.main_identity && <ConceptHintPanel hint={hint} />}

      {/* Shenwan industry path */}
      {shenwan && (shenwan.level1 || shenwan.level2 || shenwan.level3) && (
        <div className="mb-3 flex flex-wrap items-center gap-1 text-sm">
          <span className="text-muted-foreground">申万行业:</span>
          {[shenwan.level1, shenwan.level2, shenwan.level3]
            .filter(Boolean)
            .map((level, idx, arr) => (
              <span key={idx} className="flex items-center gap-1">
                <span className="font-medium">
                  {(level as { name?: string })?.name}
                </span>
                {idx < arr.length - 1 && (
                  <span className="text-muted-foreground">→</span>
                )}
              </span>
            ))}
        </div>
      )}

      {/* Concept tag cloud */}
      {cards.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {cards.map((card) => {
            const isHot = hottest?.sector_id === card.sector_id && card.change_pct != null && Math.abs(card.change_pct) > 1;
            return (
              <Link
                key={card.sector_id}
                to={`/explore?sector=${encodeURIComponent(card.sector_id)}`}
              >
                <ConceptTag
                  name={card.name}
                  changePct={card.change_pct}
                  type={card.type}
                  hot={isHot}
                />
              </Link>
            );
          })}
        </div>
      ) : (
        <div className="text-sm text-muted-foreground">暂无概念归属数据</div>
      )}

      {/* Hot mainline hint */}
      {hottest && hottest.change_pct != null && Math.abs(hottest.change_pct) > 1 && (
        <div className="mt-3 flex items-center gap-2 rounded-md bg-muted/60 px-3 py-2 text-sm">
          <Flame size={14} className="text-orange-500" />
          <span>
            今日最强主线:
            <Link
              to={`/explore?sector=${encodeURIComponent(hottest.sector_id)}`}
              className="ml-1 font-medium text-primary hover:underline"
            >
              {hottest.name} ({formatPct(hottest.change_pct)})
            </Link>
          </span>
          <ArrowRight size={14} className="text-muted-foreground" />
        </div>
      )}
    </section>
  );
}

// ── Concept Hint Panel (概念解读) ──

function ConceptHintPanel({ hint }: { hint: ConceptHint }) {
  const res = hint.resonance;
  const resonanceColor = res?.level_color === "rise"
    ? "text-rise"
    : res?.level_color === "fall"
      ? "text-fall"
      : "text-muted-foreground";

  return (
    <div className="mb-4 rounded-lg border bg-card/80 px-4 py-3 space-y-2">
      {/* 一句话定位 */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-muted-foreground">核心定位</span>
        <span className="text-sm font-semibold text-primary">
          {hint.main_identity}
        </span>
      </div>

      {/* 主题聚类标签 */}
      {hint.themes.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-muted-foreground">主线</span>
          {hint.themes.slice(0, 4).map((t) => (
            <Badge
              key={t.name}
              variant="outline"
              className="text-xs gap-1 px-2 py-0"
            >
              {t.name}
              <span className="text-muted-foreground">×{t.strength}</span>
            </Badge>
          ))}
          {hint.themes.length > 4 && (
            <span className="text-xs text-muted-foreground">
              +{hint.themes.length - 4}
            </span>
          )}
        </div>
      )}

      {/* 共振指示器 */}
      {res && res.total > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-muted-foreground">概念共振</span>
          {/* Mini bar */}
          <div className="flex h-3 w-24 overflow-hidden rounded-sm bg-muted">
            <div
              className="bg-rise/70"
              style={{ width: `${(res.rising / res.total) * 100}%` }}
            />
            <div
              className="bg-muted-foreground/30"
              style={{ width: `${(res.flat / res.total) * 100}%` }}
            />
            <div
              className="bg-fall/70"
              style={{ width: `${(res.falling / res.total) * 100}%` }}
            />
          </div>
          <span className={resonanceColor}>{res.level}</span>
          <span className="text-muted-foreground">
            {res.rising}/{res.total}上涨
          </span>
        </div>
      )}
    </div>
  );
}

// ── Shenwan Hierarchy display ──

function ShenwanHierarchy({
  shenwan,
}: {
  shenwan: ShenwanClassification | undefined;
}) {
  if (!shenwan || (!shenwan.level1 && !shenwan.level2 && !shenwan.level3)) {
    return (
      <div className="text-sm text-muted-foreground">暂无申万行业分类数据</div>
    );
  }

  const levels = [
    { label: "一级行业", data: shenwan.level1 },
    { label: "二级行业", data: shenwan.level2 },
    { label: "三级行业", data: shenwan.level3 },
  ].filter((l) => l.data);

  return (
    <div className="space-y-2">
      {levels.map(({ label, data }) => (
        <div key={label} className="flex items-center gap-2">
          <span className="w-16 shrink-0 text-xs text-muted-foreground">
            {label}
          </span>
          <span className="rounded-md bg-muted px-2 py-1 text-sm font-medium">
            {data?.name ?? "--"}
          </span>
        </div>
      ))}
    </div>
  );
}

// ── Business composition display ──

function BusinessComposition({
  business,
}: {
  business: StockBusinessType;
}) {
  const segments = business.segments ?? [];
  const summary = business.summary;

  if (segments.length === 0 && !summary) {
    return <div className="text-sm text-muted-foreground">暂无业务数据</div>;
  }

  return (
    <div className="space-y-3">
      {summary && (
        <p className="text-sm text-muted-foreground line-clamp-3">{summary}</p>
      )}
      {segments.length > 0 && (
        <div className="space-y-2">
          {segments.slice(0, 6).map((seg, idx) => {
            const name = seg.name ?? `业务${idx + 1}`;
            const ratio = seg.revenue_ratio;
            return (
              <div key={idx} className="flex items-center gap-2 text-sm">
                <span className="min-w-[80px] truncate">{name}</span>
                <div className="flex-1">
                  <div className="h-2 rounded-full bg-muted">
                    <div
                      className="h-2 rounded-full bg-primary/70 transition-all"
                      style={{
                        width: `${Math.min((ratio ?? 0) * 100, 100)}%`,
                      }}
                    />
                  </div>
                </div>
                <span className="w-12 text-right text-xs tabular-nums text-muted-foreground">
                  {ratio != null ? `${(ratio * 100).toFixed(1)}%` : "--"}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Data Evidence bar ──

function StockDataEvidence({
  sources,
  missing,
}: {
  sources: string[];
  missing: string[];
}) {
  const hasLocal = sources.some((source) => source.startsWith("postgresql"));
  return (
    <section className="flex flex-wrap items-center justify-between gap-3 rounded-lg border px-3 py-2">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <ShieldCheck size={15} />
        <span>当前个股数据</span>
        <Badge
          variant={hasLocal ? "secondary" : "outline"}
          className="rounded-md gap-1"
        >
          {hasLocal ? <Database size={13} /> : <Radio size={13} />}
          {hasLocal ? "本地库参与" : "实时源为主"}
        </Badge>
        <span
          className={cn(
            missing.length ? "text-muted-foreground" : "text-green-600"
          )}
        >
          {missing.length
            ? `${missing.length} 个模块待补齐`
            : "主要模块已返回"}
        </span>
      </div>
      {sources.length > 0 && (
        <div
          className="max-w-full truncate text-xs text-muted-foreground"
          title={sources.join(", ")}
        >
          证据: {sources.slice(0, 3).join(" / ")}
        </div>
      )}
    </section>
  );
}
