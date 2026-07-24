import { useState } from "react";
import { ChevronDown } from "lucide-react";

import type { LowSuctionCrossRegimeValidation } from "@/api/lowSuction";
import { cn } from "@/lib/utils";

type RuleTone = "gate" | "campaign" | "leader" | "action" | "settle";

type RuleNode = {
  id: string;
  badge: string;
  tone: RuleTone;
  stageLabel: string;
  title: string;
  purpose: string;
  condition: string;
  dataNote: string;
  failHint: string;
};

const TONE_CLASS: Record<RuleTone, string> = {
  gate: "border-muted-foreground/40 text-muted-foreground",
  campaign: "border-rise/40 text-rise",
  leader: "border-primary/40 text-primary",
  action: "border-amber-500/40 text-amber-600 dark:text-amber-300",
  settle: "border-muted-foreground/40 text-muted-foreground",
};

function buildNodes(contract: LowSuctionCrossRegimeValidation["three_phase_candidate"]["execution_contract"]): RuleNode[] {
  const raw: Array<Omit<RuleNode, "badge">> = [
    { id: "universe", tone: "gate", stageLabel: "股票池", title: "只保留可交易主板", purpose: "先把池子圈定到规则适用的证券，避免在不能买的标的上浪费信号。", condition: contract.universe, dataNote: "证券基础信息、上市状态、ST 标记、交易板块", failHint: "排除，不进入当日候选。" },
    { id: "campaign", tone: "campaign", stageLabel: "概念主升", title: "确认资金推动的概念行情", purpose: "反包的前提是概念本身有资金推动的主升行情，而不是孤立个股异动。", condition: contract.concept_campaign, dataNote: "概念成分日线、概念涨幅、换手与回撤序列", failHint: "概念未启动或已经退潮，整组股票不参与。" },
    { id: "leader", tone: "leader", stageLabel: "动态龙头", title: "计算概念内 Top3", purpose: "只做每个概念里最强的三只，后排跟风不做反包。", condition: contract.leader_identity, dataNote: "截至当日的波段涨幅、强势日、概念超额、换手扩张", failHint: "排名在 Top3 之外，不做反包。" },
    { id: "structure", tone: "campaign", stageLabel: "个股主升", title: "确认仍有创新高能力", purpose: "个股自身结构要仍处于主升段，回踩才有意义。", condition: contract.main_rise_structure, dataNote: "个股日线、可见前高、波段结构与均线", failHint: "结构破坏或无法形成更高点，停止跟踪。" },
    { id: "support", tone: "leader", stageLabel: "回踩支撑", title: "第一次看 MA5，后续看 MA10", purpose: "等待价格回到波段对应的均线支撑，而不是追高买入。", condition: contract.wave_support, dataNote: "信号日前完整日线、MA5、MA10、波段次数", failHint: "未触及目标支撑或有效跌破支撑，不买。" },
    { id: "reclaim", tone: "campaign", stageLabel: "分歧转强", title: "支撑测试后重新走强", purpose: "回踩只是观察，重新走强才是买入理由——分歧后多方要夺回主动。", condition: contract.common_reclaim, dataNote: "支撑测试后 1-2 日的收盘、涨幅、最低价和参考前高", failHint: "只有回踩、没有转强确认，继续等待。" },
    { id: "entry", tone: "action", stageLabel: "收盘买入", title: "信号日按收盘价成交", purpose: "所有条件在收盘时确认，按收盘价成交，不盘中抢跑。", condition: `${contract.uptrend_entry}；${contract.warming_entry}；${contract.rotation_entry}。${contract.entry_execution}`, dataNote: "行情阶段、信号日完整收盘价、组合可用仓位", failHint: `退潮时${contract.retreat_entry}；仓位或概念限制不通过也不买。` },
    { id: "exit", tone: "settle", stageLabel: "退出结算", title: "D+1 止损，盈利单跟随结构", purpose: "亏损单快速了断，盈利单让结构决定持有周期。", condition: `${contract.d1_exit}；${contract.winner_exit}`, dataNote: "D+1 及后续完整日线、前高、个股结构、概念行情状态", failHint: "成本后 D+1 不盈利直接退出；盈利单在创新高确认或结构结束时退出。" },
  ];
  return raw.map((node, index) => ({ ...node, badge: String(index + 1).padStart(2, "0") }));
}

/**
 * 反包规则说明：左侧编号步骤轨 + 右侧节点详情。
 * 人话文案归本文件所有（与打板 ruleFlow 同一分层原则），后端执行契约不动。
 */
export function LowSuctionRulesView({ validation }: { validation: LowSuctionCrossRegimeValidation }) {
  const contract = validation.three_phase_candidate.execution_contract;
  const [nodes] = useState(() => buildNodes(contract));
  const [selectedId, setSelectedId] = useState(nodes[0].id);
  const selected = nodes.find((node) => node.id === selectedId) ?? nodes[0];
  return (
    <div className="min-w-0 py-5">
      <div className="mb-4 rounded-md border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-xs leading-5 text-muted-foreground">
        <span className="font-semibold text-amber-700 dark:text-amber-300">证据口径</span>
        <span className="ml-2">历史回测使用当前成分向后回放（探索性代理），且 91% 信号日收盘贴近涨停、同一收盘价成交不保证——压力口径（D+1 开盘）下胜率与收益大幅下降。只作研究展示，不计入正式资格；正式资格以前向 300 笔纸面成交账本为准。</span>
      </div>

      <div className="grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
        <ol className="relative space-y-1" aria-label="反包规则流程图">
          {nodes.map((node, index) => {
            const active = node.id === selected.id;
            return (
              <li key={node.id} className="relative">
                {index < nodes.length - 1 && (
                  <span className="absolute left-[1.0625rem] top-9 h-[calc(100%-0.5rem)] w-px bg-border" aria-hidden />
                )}
                <button
                  type="button"
                  className={cn(
                    "relative z-10 flex w-full items-center gap-3 rounded-md border px-3 py-2.5 text-left transition-colors",
                    active ? "border-foreground/40 bg-card shadow-sm" : "border-transparent hover:bg-muted/40",
                  )}
                  aria-current={active ? "step" : undefined}
                  onClick={() => setSelectedId(node.id)}
                >
                  <span className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-full border font-mono text-[11px] font-semibold", TONE_CLASS[node.tone])} aria-hidden>
                    {node.badge}
                  </span>
                  <span className="min-w-0">
                    <span className="block text-[11px] text-muted-foreground">{node.stageLabel}</span>
                    <span className={cn("block truncate text-sm", active && "font-semibold")}>{node.title}</span>
                  </span>
                  <ChevronDown size={15} className={cn("ml-auto shrink-0 text-muted-foreground transition-transform", active && "rotate-180")} aria-hidden />
                </button>
              </li>
            );
          })}
        </ol>

        <div className="rounded-lg border bg-card p-4 sm:p-5" aria-live="polite">
          <div className="flex flex-wrap items-center gap-2">
            <span className={cn("rounded-full border px-2.5 py-0.5 text-xs font-medium", TONE_CLASS[selected.tone])}>
              {selected.stageLabel}
            </span>
            <h4 className="text-base font-semibold">{selected.title}</h4>
          </div>
          <p className="mt-2 text-sm text-foreground">{selected.purpose}</p>

          <section className="mt-4" aria-label={`${selected.title}算法条件`}>
            <h5 className="text-xs font-semibold text-muted-foreground">算法条件</h5>
            <p className="mt-1 text-sm leading-6 text-foreground">{selected.condition}</p>
          </section>

          <section className="mt-4" aria-label={`${selected.title}使用数据`}>
            <h5 className="text-xs font-semibold text-muted-foreground">使用数据</h5>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">{selected.dataNote}</p>
          </section>

          <section className="mt-4 flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/5 px-3 py-2">
            <span className="mt-0.5 shrink-0 text-xs font-semibold text-amber-700 dark:text-amber-300">不通过</span>
            <p className="text-sm leading-6 text-foreground">{selected.failHint}</p>
          </section>
        </div>
      </div>

      <div className="mt-5 border-t py-3 text-xs text-muted-foreground">
        成交口径：{contract.portfolio}；{contract.data_frequency}
      </div>
    </div>
  );
}
