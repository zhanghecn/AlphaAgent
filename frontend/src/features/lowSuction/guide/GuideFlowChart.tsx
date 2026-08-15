import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";

import { cn } from "@/lib/utils";

import type {
  GuideRuleNodeWithCases,
  GuideStage,
} from "./guideContent";

/**
 * 低吸因子流程图：手工 HTML+SVG 纵向五阶段管道，准入阶段分叉两族
 * 规则节点列。不用 @xyflow/react——拓扑固定，手绘 SVG 连接线足够，
 * 避免唤醒已闲置的重依赖。
 */

interface GuideFlowChartProps {
  stages: GuideStage[];
  nodes: GuideRuleNodeWithCases[];
  selectedRuleKey: string | null;
  onSelectRule: (ruleKey: string) => void;
}

/** 族语义色：趋势 brand 蓝、超跌 violet（避开神圣保留的涨红跌绿）。 */
const FAMILY_STYLES = {
  trend_pullback: {
    border: "border-l-brand-600",
    badge: "border-brand-600/40 bg-brand-600/10 text-brand-700 dark:text-brand-300",
    label: "趋势回踩族 · 7 条产品规则",
  },
  oversold_rebound: {
    border: "border-l-violet-600",
    badge:
      "border-violet-600/40 bg-violet-600/10 text-violet-700 dark:text-violet-300",
    label: "超跌反弹族 · 6 条产品（5×P1.5 + P1）+ 3 条研究",
  },
} as const;

export function GuideFlowChart({
  stages,
  nodes,
  selectedRuleKey,
  onSelectRule,
}: GuideFlowChartProps) {
  const stageByKey = new Map(stages.map((stage) => [stage.key, stage]));
  const trendNodes = nodes.filter((node) => node.family === "trend_pullback");
  const oversoldNodes = nodes.filter(
    (node) => node.family === "oversold_rebound",
  );

  return (
    <div className="px-3 py-4 sm:px-4">
      {/* 01 硬过滤 */}
      <StageCard stage={stageByKey.get("filter")!} />
      <StageConnector />

      {/* 02 规则准入：两族分叉 */}
      <StageCard stage={stageByKey.get("admission")!} />
      <div className="relative">
        {/* 桌面端分叉连接线（preserveAspectRatio=none 拓扑恒定，免 ResizeObserver） */}
        <svg
          className="pointer-events-none absolute inset-x-0 top-0 hidden h-5 w-full lg:block"
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
          aria-hidden
        >
          <path
            d="M50 0 L50 35 M50 35 L25 35 L25 100 M50 35 L75 35 L75 100"
            fill="none"
            stroke="hsl(var(--border))"
            strokeWidth="1.5"
            vectorEffect="non-scaling-stroke"
          />
        </svg>
        <div className="grid gap-3 pt-1 lg:grid-cols-2 lg:pt-6">
          <FamilyRuleColumn
            family="trend_pullback"
            nodes={trendNodes}
            selectedRuleKey={selectedRuleKey}
            onSelectRule={onSelectRule}
          />
          <FamilyRuleColumn
            family="oversold_rebound"
            nodes={oversoldNodes}
            selectedRuleKey={selectedRuleKey}
            onSelectRule={onSelectRule}
          />
        </div>
        {/* 汇合线 */}
        <svg
          className="pointer-events-none absolute inset-x-0 bottom-0 hidden h-5 w-full translate-y-full lg:block"
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
          aria-hidden
        >
          <path
            d="M25 0 L25 65 L50 65 L50 100 M75 0 L75 65 L50 65"
            fill="none"
            stroke="hsl(var(--border))"
            strokeWidth="1.5"
            vectorEffect="non-scaling-stroke"
          />
        </svg>
      </div>
      <div className="h-5 lg:h-5" />

      {/* 03-05 主流水 */}
      <StageCard stage={stageByKey.get("scoring")!} />
      <StageConnector />
      <StageCard stage={stageByKey.get("ranking")!} />
      <StageConnector />
      <StageCard stage={stageByKey.get("portfolio")!} />
    </div>
  );
}

function StageCard({ stage }: { stage: GuideStage }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mx-auto w-full max-w-2xl rounded-md border bg-muted/20">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full flex-wrap items-baseline gap-x-2 px-3 py-2 text-left transition-colors hover:bg-muted/40"
      >
        <span className="font-mono text-[10px] font-semibold tracking-[0.15em] text-primary">
          {stage.no}
        </span>
        <span className="text-xs font-semibold">{stage.zh}</span>
        <span className="eyebrow">{stage.en}</span>
        <span className="min-w-0 flex-1 text-[11px] text-muted-foreground">
          {stage.note}
        </span>
        <span className="shrink-0 self-center text-muted-foreground">
          {open ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
        </span>
      </button>
      {open && (
        <ul className="ml-4 list-disc space-y-0.5 px-3 pb-2.5 text-[11px] leading-relaxed text-muted-foreground">
          {stage.bullets.map((bullet) => (
            <li key={bullet}>{bullet}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function StageConnector() {
  return <div className="mx-auto h-5 w-px bg-border" aria-hidden />;
}

function FamilyRuleColumn({
  family,
  nodes,
  selectedRuleKey,
  onSelectRule,
}: {
  family: keyof typeof FAMILY_STYLES;
  nodes: GuideRuleNodeWithCases[];
  selectedRuleKey: string | null;
  onSelectRule: (ruleKey: string) => void;
}) {
  const styles = FAMILY_STYLES[family];
  const productNodes = nodes.filter((node) => node.tier === "product");
  const researchNodes = nodes.filter((node) => node.tier === "research");

  return (
    <div className="space-y-1.5">
      <p className="text-[11px] font-medium text-muted-foreground">
        {styles.label}
      </p>
      <div className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
        {productNodes.map((node) => (
          <RuleNodeButton
            key={node.ruleKey}
            node={node}
            family={family}
            selected={node.ruleKey === selectedRuleKey}
            onSelect={onSelectRule}
          />
        ))}
      </div>
      {researchNodes.length > 0 && (
        <>
          <p className="pt-1 text-[10px] text-muted-foreground/80">
            研究锚点（不进实时推荐与回测仓位）
          </p>
          <div className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
            {researchNodes.map((node) => (
              <RuleNodeButton
                key={node.ruleKey}
                node={node}
                family={family}
                selected={node.ruleKey === selectedRuleKey}
                onSelect={onSelectRule}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function RuleNodeButton({
  node,
  family,
  selected,
  onSelect,
}: {
  node: GuideRuleNodeWithCases;
  family: keyof typeof FAMILY_STYLES;
  selected: boolean;
  onSelect: (ruleKey: string) => void;
}) {
  const styles = FAMILY_STYLES[family];
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={() => onSelect(node.ruleKey)}
      className={cn(
        "rounded-md border border-l-4 px-2.5 py-1.5 text-left text-xs transition-colors hover:bg-muted",
        styles.border,
        node.tier === "research" && "border-dashed",
        selected
          ? "border-primary bg-primary/[0.06] ring-1 ring-primary"
          : "bg-card",
      )}
    >
      <span className="flex items-center gap-1.5">
        <span className="min-w-0 flex-1 truncate font-medium">
          {node.shortLabel}
        </span>
        {node.productTier && (
          <span
            className={cn(
              "shrink-0 rounded border px-1 py-px text-[9px] font-semibold",
              styles.badge,
            )}
          >
            {node.productTier}
          </span>
        )}
        {node.tier === "research" && (
          <span className="shrink-0 rounded border border-dashed px-1 py-px text-[9px] text-muted-foreground">
            研究
          </span>
        )}
        {node.cases.length > 0 && (
          <span className="shrink-0 tabular-nums text-[9px] text-muted-foreground">
            {node.cases.length}例
          </span>
        )}
      </span>
    </button>
  );
}
