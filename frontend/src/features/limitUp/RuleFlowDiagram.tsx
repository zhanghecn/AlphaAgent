import { useMemo, useState } from "react";
import { ChevronDown } from "lucide-react";

import type { LimitUpStrategyGuide } from "@/api/limitUp";
import { cn } from "@/lib/utils";
import { STAGE_META, buildRuleFlow } from "./ruleFlow";

interface RuleFlowDiagramProps {
  guide: LimitUpStrategyGuide;
}

export function RuleFlowDiagram({ guide }: RuleFlowDiagramProps) {
  const nodes = useMemo(() => buildRuleFlow(guide), [guide]);
  const [selectedId, setSelectedId] = useState<string>(nodes[0]?.id ?? "");
  const selected = nodes.find((node) => node.id === selectedId) ?? nodes[0];

  return (
    <div className="grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
      <ol className="relative space-y-1" aria-label="选股规则流程图">
        {nodes.map((node, index) => {
          const meta = STAGE_META[node.stage];
          const active = node.id === selected?.id;
          return (
            <li key={node.id} className="relative">
              {index < nodes.length - 1 && (
                <span className="absolute left-[1.0625rem] top-9 h-[calc(100%-0.5rem)] w-px bg-border" aria-hidden />
              )}
              <button
                type="button"
                className={cn(
                  "relative z-10 flex w-full items-center gap-3 rounded-md border px-3 py-2.5 text-left transition-colors",
                  active
                    ? "border-foreground/40 bg-card shadow-sm"
                    : "border-transparent hover:bg-muted/40",
                )}
                aria-expanded={active}
                aria-current={active ? "step" : undefined}
                onClick={() => setSelectedId(active ? "" : node.id)}
              >
                <span
                  className={cn(
                    "flex h-8 w-8 shrink-0 items-center justify-center rounded-full border text-xs font-bold tabular-nums",
                    meta.tone,
                  )}
                  aria-hidden
                >
                  {node.badge}
                </span>
                <span className="min-w-0">
                  <span className={cn("block text-[11px]", active ? "text-muted-foreground" : "text-muted-foreground")}>
                    {meta.label}
                  </span>
                  <span className={cn("block truncate text-sm", active ? "font-semibold text-foreground" : "text-foreground")}>
                    {node.title}
                  </span>
                </span>
                <ChevronDown
                  size={15}
                  className={cn("ml-auto shrink-0 text-muted-foreground transition-transform", active && "rotate-180")}
                />
              </button>
            </li>
          );
        })}
      </ol>

      {selected ? <NodeDetail node={selected} /> : null}
    </div>
  );
}

function NodeDetail({ node }: { node: import("./ruleFlow").RuleFlowNode }) {
  const meta = STAGE_META[node.stage];
  return (
    <div className="rounded-lg border bg-card p-4 sm:p-5">
      <div className="flex flex-wrap items-center gap-2">
        <span className={cn("rounded-full border px-2.5 py-0.5 text-xs font-medium", meta.tone)}>
          {meta.label}
        </span>
        <h4 className="text-base font-semibold">{node.title}</h4>
      </div>
      <p className="mt-2 text-sm text-foreground">{node.purpose}</p>

      <section className="mt-4" aria-label={`${node.title}成立条件`}>
        <h5 className="text-xs font-semibold text-muted-foreground">成立条件</h5>
        <p className="mt-1 text-sm leading-6 text-foreground">{node.condition}</p>
      </section>

      {node.thresholds.length > 0 && (
        <section className="mt-4" aria-label={`${node.title}关键门槛`}>
          <h5 className="text-xs font-semibold text-muted-foreground">关键门槛</h5>
          <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-2">
            {node.thresholds.map((threshold) => (
              <div key={threshold.label} className="rounded-md border bg-muted/20 px-3 py-2">
                <div className="text-[11px] text-muted-foreground">{threshold.label}</div>
                <div className="mt-0.5 text-sm font-semibold tabular-nums text-foreground">{threshold.value}</div>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="mt-4" aria-label={`${node.title}用到的数据`}>
        <h5 className="text-xs font-semibold text-muted-foreground">用到的数据</h5>
        <p className="mt-1 text-sm leading-6 text-muted-foreground">{node.dataNote}</p>
      </section>

      {node.failHint && (
        <section className="mt-4 flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/5 px-3 py-2">
          <span className="mt-0.5 text-xs font-semibold text-amber-700 dark:text-amber-300">不通过会怎样</span>
          <p className="text-sm leading-6 text-foreground">{node.failHint}</p>
        </section>
      )}
    </div>
  );
}
