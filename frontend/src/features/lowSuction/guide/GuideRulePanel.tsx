import { ChevronDown, ChevronUp } from "lucide-react";
import { useState } from "react";

import { StockIdentityLink } from "@/components/StockIdentityLink";
import { cn } from "@/lib/utils";

import { GuideCaseChart } from "./GuideCaseChart";
import type { GuideCase, GuideRuleNodeWithCases } from "./guideContent";

/**
 * 规则详情面板：选中规则节点后展示准入条件、验证证据与关联经典案例
 * （真实历史股票 K 线）。第一个案例默认展开，其余折叠点击展开。
 */

interface GuideRulePanelProps {
  node: GuideRuleNodeWithCases | null;
}

export function GuideRulePanel({ node }: GuideRulePanelProps) {
  if (!node) {
    return (
      <div className="rounded-md border border-dashed px-4 py-8 text-center text-xs text-muted-foreground">
        点击流程图中的规则节点，查看准入条件与经典案例 K 线
      </div>
    );
  }
  return (
    <div key={node.ruleKey} className="animate-fade-in space-y-3">
      <div>
        <div className="flex flex-wrap items-baseline gap-x-2">
          <h3 className="text-sm font-semibold">{node.shortLabel}</h3>
          {node.productTier && (
            <span className="rounded border border-violet-600/40 bg-violet-600/10 px-1.5 py-px text-[10px] font-semibold text-violet-700 dark:text-violet-300">
              {node.productTier} 产品放行
            </span>
          )}
          {node.tier === "research" && (
            <span className="rounded border border-dashed px-1.5 py-px text-[10px] text-muted-foreground">
              研究锚点 · 不进推荐
            </span>
          )}
        </div>
        <p className="mt-0.5 font-mono text-[10px] text-muted-foreground/80">
          {node.ruleKey}
        </p>
      </div>

      <div>
        <p className="mb-1 text-xs font-semibold">准入条件</p>
        <ul className="ml-4 list-disc space-y-0.5 text-xs text-muted-foreground">
          {node.conditions.map((condition) => (
            <li key={condition}>{condition}</li>
          ))}
        </ul>
      </div>

      <p className="rounded border border-border/60 bg-muted/20 px-2.5 py-1.5 text-[11px] leading-relaxed text-muted-foreground">
        📊 {node.evidence}
      </p>

      <div className="space-y-2">
        <p className="text-xs font-semibold">
          经典案例（真实历史股票）
          {node.cases.length > 0 && (
            <span className="ml-1 tabular-nums text-muted-foreground">
              {node.cases.length} 条
            </span>
          )}
        </p>
        {node.cases.length === 0 ? (
          <p className="rounded border border-dashed px-3 py-3 text-[11px] text-muted-foreground">
            该规则暂无策展案例；可在「实时推荐」的候选因子详解中观察当日命中样本。
          </p>
        ) : (
          node.cases.map((caseItem, index) => (
            <CaseBlock
              key={caseItem.caseId}
              node={node}
              caseItem={caseItem}
              defaultOpen={index === 0}
            />
          ))
        )}
      </div>
    </div>
  );
}

function CaseBlock({
  node,
  caseItem,
  defaultOpen,
}: {
  node: GuideRuleNodeWithCases;
  caseItem: GuideCase;
  defaultOpen: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-md border bg-card">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between gap-2 px-2.5 py-1.5 text-left text-xs hover:bg-muted/50"
      >
        <span className="min-w-0">
          <StockIdentityLink name={caseItem.name} vtSymbol={caseItem.vtSymbol} />
        </span>
        {open ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
      </button>
      <div
        className={cn(
          "border-t px-2.5 py-2",
          !open && "hidden",
        )}
      >
        {open && (
          <GuideCaseChart caseItem={caseItem} chartHint={node.chartHint} />
        )}
      </div>
    </div>
  );
}
