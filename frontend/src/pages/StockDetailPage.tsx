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
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import {
  fetchStockDetail,
  fetchStockSnapshot,
  fetchStockBusiness,
} from "@/api/stocks";
import { fetchConceptCards } from "@/api/research";
import { fetchLimitPools } from "@/api/market";
import { StockQuoteHeader } from "@/features/stocks/StockQuoteHeader";
import { StockKlineChart } from "@/features/stocks/StockKlineChart";
import { StockIndicatorPanel } from "@/features/stocks/StockIndicatorPanel";
import { StockFinanceChart } from "@/features/stocks/StockFinanceChart";
import { ConceptTag } from "@/components/ConceptTag";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { Badge } from "@/components/ui/badge";
import { formatPct, cn } from "@/lib/utils";
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
} from "lucide-react";

export function StockDetailPage() {
  const { vtSymbol } = useParams<{ vtSymbol: string }>();

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

      {/* K-line chart */}
      <div className="rounded-lg border p-3 sm:p-4">
        <StockKlineChart vtSymbol={vtSymbol} />
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
