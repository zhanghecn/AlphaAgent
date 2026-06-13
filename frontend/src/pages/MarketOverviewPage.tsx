/**
 * MarketPulsePage — 今日市场 (重写)
 *
 * Layout: Index strip → Mainline ranking (left) + Market thermometer (right)
 * Data sources: sector ranking, fund flow, hot ranks, limit pools
 */
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { IndexStrip } from "@/features/market/IndexStrip";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { fetchSectorRanking } from "@/api/research";
import { fetchFundFlow, fetchHotRanks, fetchLimitPools } from "@/api/market";
import { formatPct, formatAmount, cn } from "@/lib/utils";
import type {
  SectorRankingItem,
  LimitPoolsData,
  HotRanksResponse,
  FundFlowResponse,
} from "@/types/research";
import { Compass, Flame, TrendingUp, BarChart3, ArrowRight } from "lucide-react";

export function MarketOverviewPage() {
  return (
    <div className="space-y-5">
      {/* Page header */}
      <div className="flex flex-wrap items-start justify-between gap-3 border-b pb-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">今日市场</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            主线驱动 · 实时板块热度 · 资金风向
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link
            to="/explore"
            className="inline-flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm font-medium transition-colors hover:bg-muted"
          >
            <Compass size={16} />
            主线探索
          </Link>
          <Link
            to="/stocks"
            className="inline-flex items-center gap-2 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            搜股票
          </Link>
        </div>
      </div>

      {/* Index strip (reused from existing component) */}
      <IndexStrip />

      {/* Main content: ranking + thermometer */}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <MainlineRankingPanel />
        <MarketThermometerPanel />
      </div>
    </div>
  );
}

// ── Mainline Ranking Panel (left) ──

function MainlineRankingPanel() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["sectorRanking", "all"],
    queryFn: () => fetchSectorRanking({ sector_type: "all", sort_by: "change_pct", limit: 15 }),
    staleTime: 30_000,
  });

  if (isLoading) return <LoadingState rows={6} />;
  if (isError) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "加载板块排行失败"}
        onRetry={() => refetch()}
      />
    );
  }

  const items = data?.items ?? [];

  return (
    <section className="rounded-lg border">
      <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
        <div className="flex items-center gap-2">
          <Flame size={16} className="text-rise" />
          <h2 className="text-sm font-semibold">今日主线热度</h2>
        </div>
        <Link
          to="/explore"
          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        >
          查看全部
          <ArrowRight size={12} />
        </Link>
      </div>
      <div className="divide-y">
        {items.length === 0 && (
          <div className="px-4 py-8 text-sm text-muted-foreground">暂无板块排行数据</div>
        )}
        {items.map((item: SectorRankingItem, idx: number) => (
          <MainlineRankRow key={item.sector_id} item={item} rank={idx + 1} />
        ))}
      </div>
    </section>
  );
}

function MainlineRankRow({ item, rank }: { item: SectorRankingItem; rank: number }) {
  const changePct = item.change_pct;
  const isRise = changePct != null && changePct > 0;

  return (
    <Link
      to={`/explore?sector=${encodeURIComponent(item.sector_id)}`}
      className="grid grid-cols-[2rem_minmax(0,1fr)_80px_90px] items-center gap-2 px-4 py-2.5 text-sm transition-colors hover:bg-muted/40"
    >
      {/* Rank badge */}
      <span
        className={cn(
          "flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold",
          rank === 1 && "bg-red-500 text-white",
          rank === 2 && "bg-orange-500 text-white",
          rank === 3 && "bg-amber-500 text-white",
          rank > 3 && "bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-300"
        )}
      >
        {rank}
      </span>

      {/* Name + type tag */}
      <div className="min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="truncate font-medium">{item.name}</span>
          {item.type === "industry" && (
            <span className="shrink-0 rounded bg-blue-100 px-1 py-0.5 text-[10px] text-blue-600 dark:bg-blue-500/15 dark:text-blue-300">
              行业
            </span>
          )}
        </div>
        <div className="mt-0.5 flex gap-2 text-xs text-muted-foreground">
          {item.stock_count != null && <span>{item.stock_count}只</span>}
          {item.leader_stock && <span className="truncate">龙头: {item.leader_stock}</span>}
        </div>
      </div>

      {/* Change % */}
      <span
        className={cn(
          "text-right font-semibold tabular-nums",
          isRise ? "text-rise" : changePct != null ? "text-fall" : "text-muted-foreground"
        )}
      >
        {formatPct(changePct)}
      </span>

      {/* Fund flow */}
      <span
        className={cn(
          "text-right text-xs tabular-nums",
          item.main_net_inflow != null && item.main_net_inflow >= 0 ? "fund-inflow" : "fund-outflow"
        )}
      >
        {item.main_net_inflow != null
          ? `${item.main_net_inflow >= 0 ? "+" : ""}${formatAmount(item.main_net_inflow)}`
          : "--"}
      </span>
    </Link>
  );
}

// ── Market Thermometer Panel (right) ──

function MarketThermometerPanel() {
  const limitQuery = useQuery({
    queryKey: ["limitPools"],
    queryFn: () => fetchLimitPools(),
    staleTime: 30_000,
  });

  const hotQuery = useQuery({
    queryKey: ["hotRanks", 5],
    queryFn: () => fetchHotRanks(5),
    staleTime: 30_000,
  });

  const fundQuery = useQuery({
    queryKey: ["fundFlow", "concept", 5],
    queryFn: () => fetchFundFlow("concept", 5),
    staleTime: 30_000,
  });

  return (
    <div className="space-y-4">
      <LimitPoolSection data={limitQuery.data} isLoading={limitQuery.isLoading} />
      <HotStocksSection data={hotQuery.data} isLoading={hotQuery.isLoading} />
      <FundFlowSection data={fundQuery.data} isLoading={fundQuery.isLoading} />
    </div>
  );
}

function LimitPoolSection({
  data,
  isLoading,
}: {
  data: LimitPoolsData | undefined;
  isLoading: boolean;
}) {
  if (isLoading) return <LoadingState rows={2} />;

  const ztPool = data?.pools?.zt;
  const dtgcPool = data?.pools?.dtgc;
  const strongPool = data?.pools?.strong;
  const limitUp = ztPool?.items?.length ?? 0;
  const limitDown = dtgcPool?.items?.length ?? 0;
  const strongCount = strongPool?.items?.length ?? 0;

  return (
    <section className="rounded-lg border p-4">
      <h3 className="flex items-center gap-2 text-sm font-semibold">
        <BarChart3 size={14} />
        涨停池
      </h3>
      <div className="mt-3 grid grid-cols-3 gap-3 text-center">
        <div className="rounded-lg bg-red-50 p-2 dark:bg-red-500/10">
          <div className="text-xl font-bold text-rise">{limitUp}</div>
          <div className="text-xs text-muted-foreground">涨停</div>
        </div>
        <div className="rounded-lg bg-green-50 p-2 dark:bg-green-500/10">
          <div className="text-xl font-bold text-fall">{limitDown}</div>
          <div className="text-xs text-muted-foreground">跌停</div>
        </div>
        <div className="rounded-lg bg-amber-50 p-2 dark:bg-amber-500/10">
          <div className="text-xl font-bold text-amber-600 dark:text-amber-400">{strongCount}</div>
          <div className="text-xs text-muted-foreground">强势</div>
        </div>
      </div>
      {/* Top limit-up stocks */}
      {ztPool && ztPool.items.length > 0 && (
        <div className="mt-3 space-y-1">
          {ztPool.items.slice(0, 5).map((s) => (
            <Link
              key={s.vt_symbol}
              to={`/stocks/${s.vt_symbol}`}
              className="flex items-center justify-between rounded px-2 py-1 text-xs transition-colors hover:bg-muted/50"
            >
              <StockIdentityLink
                name={s.name}
                vtSymbol={s.vt_symbol ?? stockVtSymbol(s.symbol)}
                link={false}
                className="min-w-0"
              />
              <span className="text-rise tabular-nums">
                {formatPct(s.change_pct)}
              </span>
            </Link>
          ))}
        </div>
      )}
    </section>
  );
}

function stockVtSymbol(symbol?: string | null) {
  const code = String(symbol ?? "").trim();
  if (!code) return "";
  if (code.includes(".")) return code.toUpperCase();
  if (code.startsWith("6")) return `${code}.SSE`;
  if (/^(8|4|920)/.test(code)) return `${code}.BSE`;
  return `${code}.SZSE`;
}

function HotStocksSection({
  data,
  isLoading,
}: {
  data: HotRanksResponse | undefined;
  isLoading: boolean;
}) {
  if (isLoading) return <LoadingState rows={3} />;

  const items = data?.items ?? [];

  return (
    <section className="rounded-lg border p-4">
      <h3 className="flex items-center gap-2 text-sm font-semibold">
        <Flame size={14} className="text-orange-500" />
        人气股 TOP5
      </h3>
      {items.length === 0 ? (
        <div className="mt-2 text-xs text-muted-foreground">暂无数据</div>
      ) : (
        <div className="mt-2 space-y-1.5">
          {items.slice(0, 5).map((item, idx: number) => (
            <Link
              key={item.stock_code ?? idx}
              to={`/stocks/${item.stock_code}.SSE`}
              className="flex items-center justify-between rounded px-2 py-1.5 text-xs transition-colors hover:bg-muted/50"
            >
              <div className="flex items-center gap-2 min-w-0">
                <span
                  className={cn(
                    "flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold",
                    idx === 0 && "bg-red-500 text-white",
                    idx === 1 && "bg-orange-500 text-white",
                    idx >= 2 && "bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-300"
                  )}
                >
                  {idx + 1}
                </span>
                <span className="truncate font-medium">
                  {item.stock_name ?? item.stock_code}
                </span>
              </div>
              <span className={cn("tabular-nums", item.change_pct != null && item.change_pct >= 0 ? "text-rise" : "text-fall")}>
                {formatPct(item.change_pct)}
              </span>
            </Link>
          ))}
        </div>
      )}
    </section>
  );
}

function FundFlowSection({
  data,
  isLoading,
}: {
  data: FundFlowResponse | undefined;
  isLoading: boolean;
}) {
  if (isLoading) return <LoadingState rows={3} />;

  const items = data?.items ?? [];
  const inflows = items.filter((i) => (i.main_net_inflow ?? 0) > 0);
  const outflows = items.filter((i) => (i.main_net_inflow ?? 0) < 0);

  return (
    <section className="rounded-lg border p-4">
      <div className="flex items-center justify-between">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <TrendingUp size={14} />
          板块资金流向
        </h3>
        <Link to="/explore" className="text-xs text-muted-foreground hover:text-foreground">
          详情 →
        </Link>
      </div>

      {inflows.length > 0 && (
        <div className="mt-3">
          <div className="mb-1 text-[10px] font-medium uppercase text-muted-foreground">
            净流入 TOP
          </div>
          <div className="space-y-1">
            {inflows.slice(0, 5).map((item) => (
              <div
                key={item.code ?? item.name}
                className="flex items-center justify-between px-2 py-1 text-xs"
              >
                <span className="truncate">{item.name}</span>
                <span className="fund-inflow tabular-nums">
                  +{formatAmount(item.main_net_inflow)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {outflows.length > 0 && (
        <div className="mt-3">
          <div className="mb-1 text-[10px] font-medium uppercase text-muted-foreground">
            净流出 TOP
          </div>
          <div className="space-y-1">
            {outflows.slice(0, 3).map((item) => (
              <div
                key={item.code ?? item.name}
                className="flex items-center justify-between px-2 py-1 text-xs"
              >
                <span className="truncate">{item.name}</span>
                <span className="fund-outflow tabular-nums">
                  {formatAmount(item.main_net_inflow)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {items.length === 0 && (
        <div className="mt-2 text-xs text-muted-foreground">暂无资金流向数据</div>
      )}
    </section>
  );
}
