import { ArrowRight, Check, X } from "lucide-react";

import { Modal, ModalBody, ModalHeader } from "@/components/ui/modal";
import { cn } from "@/lib/utils";

export interface LowSuctionRuleEvidence {
  stockName: string;
  vtSymbol: string;
  conceptName: string;
  marketPhase?: string;
  rank: number;
  waveNumber: number;
  supportLine: string | null;
  supportPrice: number | null;
  signalDate: string;
  entryPrice: number;
  signalEligible: boolean;
  decisionReason: string;
  exitText?: string;
}

export function LowSuctionRuleEvidenceModal({
  open,
  onOpenChange,
  evidence,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  evidence: LowSuctionRuleEvidence | null;
}) {
  if (!evidence) return null;
  const nodes = buildNodes(evidence);
  return (
    <Modal open={open} onOpenChange={onOpenChange} className="max-w-5xl" ariaLabel={`${evidence.stockName}买入规则说明`}>
      <ModalHeader title={`${evidence.stockName} · 买入规则说明`} onClose={() => onOpenChange(false)} />
      <ModalBody className="max-h-[78vh] overflow-y-auto p-0">
        <div className="border-b px-5 py-3 text-xs text-muted-foreground">
          {evidence.vtSymbol} · 信号日 {evidence.signalDate} · {evidence.conceptName}
        </div>
        <div className="overflow-x-auto px-5 py-4">
          <ol className="flex min-w-[850px] items-stretch" aria-label="该股票规则通过流程">
            {nodes.map((node, index) => (
              <li key={node.title} className="flex min-w-0 flex-1 items-center">
                <div className={cn("h-full w-full border px-3 py-3", node.passed ? "border-foreground/30" : "border-border bg-muted/20")}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-xs text-muted-foreground">{String(index + 1).padStart(2, "0")}</span>
                    {node.passed ? <Check size={14} className="text-rise" aria-label="通过" /> : <X size={14} className="text-fall" aria-label="未通过" />}
                  </div>
                  <div className="mt-1 text-sm font-semibold">{node.title}</div>
                  <div className="mt-1 text-xs leading-4 text-muted-foreground">{node.evidence}</div>
                </div>
                {index < nodes.length - 1 && <ArrowRight size={15} className="mx-1 shrink-0 text-muted-foreground" aria-hidden />}
              </li>
            ))}
          </ol>
        </div>
        <dl className="grid border-t text-sm sm:grid-cols-2">
          <EvidenceRow label="最终判断" value={evidence.decisionReason} />
          <EvidenceRow label="成交口径" value={`${evidence.signalDate} 收盘 ${evidence.entryPrice.toFixed(2)}`} />
          {evidence.exitText && <EvidenceRow label="退出结果" value={evidence.exitText} />}
          <EvidenceRow label="证据状态" value={evidence.signalEligible ? "全部买入门槛通过" : "存在未通过门槛"} />
        </dl>
      </ModalBody>
    </Modal>
  );
}

function buildNodes(evidence: LowSuctionRuleEvidence) {
  const eligible = evidence.signalEligible;
  return [
    { title: "主板股票", passed: true, evidence: evidence.vtSymbol },
    { title: "概念主升", passed: eligible, evidence: `${evidence.conceptName}${evidence.marketPhase ? ` · ${evidence.marketPhase}` : ""}` },
    { title: "动态 Top3", passed: evidence.rank <= 3, evidence: `概念内龙${evidence.rank}` },
    { title: "个股主升", passed: eligible, evidence: `第${evidence.waveNumber}波，结构保持`} ,
    { title: "回踩支撑", passed: Boolean(evidence.supportLine), evidence: evidence.supportLine ? `${evidence.supportLine.toUpperCase()} · ${evidence.supportPrice?.toFixed(2) ?? "--"}` : "未确认支撑" },
    { title: "分歧转强", passed: eligible, evidence: evidence.decisionReason },
    { title: "收盘买入", passed: eligible, evidence: `${evidence.signalDate} · ${evidence.entryPrice.toFixed(2)}` },
  ];
}

function EvidenceRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[88px_minmax(0,1fr)] gap-3 border-b px-5 py-3 sm:odd:border-r">
      <dt className="text-muted-foreground">{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
