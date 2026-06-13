import { Fragment, useState, type ReactNode } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { SectionCard } from "@/components/dashboard/SectionCard";
import { EmptyState } from "@/components/EmptyState";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import type { PortfolioItem } from "@/api/quant";

interface CandidateTableProps {
  items: PortfolioItem[];
  /** Right-side action in the header (e.g. batch build button). */
  action?: ReactNode;
  /** Build a single candidate into a simulated position. */
  onBuild?: (vtSymbol: string) => void;
  onViewDetail?: (vtSymbol: string) => void;
}

interface CandidateReason {
  rank?: number;
  total_score?: number;
  risk_level?: string;
  trade_date?: string;
  entry_rule?: string;
}

/** Parse the quant_candidate reason JSON (rank / score / risk / date). */
function parseReason(reason?: string | null): CandidateReason | null {
  if (!reason) return null;
  try {
    const parsed = JSON.parse(reason);
    return typeof parsed === "object" && parsed !== null ? parsed : null;
  } catch {
    return null;
  }
}

function riskBadge(level?: string): { label: string; variant: "destructive" | "secondary" | "outline" } {
  switch (level?.toUpperCase()) {
    case "HIGH":
      return { label: "高风险", variant: "destructive" };
    case "MEDIUM":
      return { label: "中险", variant: "secondary" };
    case "LOW":
      return { label: "低风险", variant: "outline" };
    default:
      return { label: "--", variant: "outline" };
  }
}

const ENTRY_RULE_LABEL: Record<string, string> = {
  daily_close_signal_next_open_execution: "收盘信号·次日开盘执行",
};

/**
 * CandidateTable — ranked list of quant candidates.
 *
 * Surfaces the score / rank / risk that the strategy already produced (stored
 * as JSON in the item reason), so the user can see *why* each stock is a
 * candidate and which to build first — instead of a wall of identical cards.
 */
export function CandidateTable({ items, action, onBuild, onViewDetail }: CandidateTableProps) {
  const [expanded, setExpanded] = useState<string | null>(null);

  const rows = items
    .map((item) => ({ item, reason: parseReason(item.reason) }))
    .sort((a, b) => (a.reason?.rank ?? 9999) - (b.reason?.rank ?? 9999));

  const tradeDate = rows.find((row) => row.reason?.trade_date)?.reason?.trade_date;

  return (
    <SectionCard
      title={
        <span className="flex items-center gap-2">
          候选池
          <Badge variant="secondary" className="px-1.5 py-0">
            {items.length}
          </Badge>
        </span>
      }
      description={
        tradeDate
          ? `${tradeDate} 策略筛选 · 评分越高越优先`
          : "量化策略每日筛选 · 评分越高越优先"
      }
      action={action}
      bodyClassName="p-0"
    >
      {rows.length === 0 ? (
        <div className="p-4">
          <EmptyState
            message="候选池为空"
            description="在量化页生成区间候选后会自动同步到此。"
          />
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-xs text-muted-foreground">
              <tr className="border-b">
                <th className="w-12 px-3 py-2 text-left">#</th>
                <th className="px-3 py-2 text-left">股票</th>
                <th className="px-3 py-2 text-right">评分</th>
                <th className="px-3 py-2 text-center">风险</th>
                <th className="px-3 py-2 text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ item, reason }) => {
                const risk = riskBadge(reason?.risk_level);
                const isOpen = expanded === item.vt_symbol;
                return (
                  <Fragment key={item.vt_symbol}>
                    <tr className="border-b last:border-0 hover:bg-muted/30">
                      <td className="px-3 py-2 font-semibold tabular-nums text-muted-foreground">
                        {reason?.rank ?? "-"}
                      </td>
                      <td className="px-3 py-2">
                        <StockIdentityLink
                          name={item.name}
                          vtSymbol={item.vt_symbol}
                          board={item.board}
                          boardLabel={item.board_label}
                        />
                      </td>
                      <td className="px-3 py-2 text-right font-semibold tabular-nums">
                        {reason?.total_score != null ? reason.total_score.toFixed(1) : "--"}
                      </td>
                      <td className="px-3 py-2 text-center">
                        <Badge variant={risk.variant} className="px-1.5 py-0 text-xs">
                          {risk.label}
                        </Badge>
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex items-center justify-end gap-1">
                          {onBuild && (
                            <Button
                              size="sm"
                              variant="brand"
                              className="h-7 px-2"
                              onClick={() => onBuild(item.vt_symbol)}
                            >
                              建仓
                            </Button>
                          )}
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 w-7 p-0"
                            title="评分明细"
                            onClick={() => setExpanded(isOpen ? null : item.vt_symbol)}
                          >
                            {isOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                          </Button>
                        </div>
                      </td>
                    </tr>
                    {isOpen && (
                      <tr className="border-b last:border-0 bg-muted/20">
                        <td colSpan={5} className="px-3 py-2 text-xs text-muted-foreground">
                          <div className="grid grid-cols-2 gap-x-6 gap-y-1 sm:grid-cols-3">
                            <DetailRow label="候选日期" value={reason?.trade_date} />
                            <DetailRow label="综合评分" value={reason?.total_score?.toFixed(2)} />
                            <DetailRow label="风险等级" value={risk.label} />
                            <DetailRow
                              label="入场规则"
                              value={
                                reason?.entry_rule
                                  ? ENTRY_RULE_LABEL[reason.entry_rule] ?? reason.entry_rule
                                  : undefined
                              }
                            />
                            <DetailRow label="策略" value={item.strategy_id} />
                            <DetailRow label="版本" value={item.strategy_version} />
                          </div>
                          {onViewDetail && (
                            <button
                              type="button"
                              className="mt-2 text-xs text-primary hover:underline"
                              onClick={() => onViewDetail(item.vt_symbol)}
                            >
                              查看个股详情 →
                            </button>
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </SectionCard>
  );
}

function DetailRow({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="flex items-center gap-2">
      <span>{label}</span>
      <span className="text-foreground tabular-nums">{value ?? "--"}</span>
    </div>
  );
}
