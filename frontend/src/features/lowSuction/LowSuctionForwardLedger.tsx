import { useQuery } from "@tanstack/react-query";

import {
  fetchLowSuctionForwardLedger,
  type LowSuctionCrossRegimeValidation,
} from "@/api/lowSuction";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { cn } from "@/lib/utils";

export function LowSuctionForwardLedger({
  validation,
}: {
  validation?: LowSuctionCrossRegimeValidation;
}) {
  const forward = validation?.three_phase_natural_forward;
  const ledger = useQuery({
    queryKey: ["lowSuctionForwardLedger"],
    queryFn: () => fetchLowSuctionForwardLedger(1, 100),
    staleTime: 30_000,
  });
  if (!forward) {
    return <div className="border-t py-12 text-center text-sm text-muted-foreground">自然前向账本暂时不可用</div>;
  }
  const phases = forward.coverage.closed_market_phases;
  return (
    <div className="min-w-0">
      <div className="border-b py-4">
        <div className="text-sm font-medium">自然前向资格流水</div>
        <div className="mt-1 text-xs text-muted-foreground">
          不允许历史回填；只统计信号当日真实冻结、之后自然结算的候选
        </div>
      </div>
      <dl className="grid border-b border-l text-sm sm:grid-cols-2 lg:grid-cols-4">
        <Metric label="候选" value={`${forward.coverage.candidate_rows} 笔`} />
        <Metric label="闭合" value={`${forward.coverage.closed_outcomes} / 50`} />
        <Metric label="主升" value={`${phases.uptrend ?? 0} / 10`} />
        <Metric label="轮动 / 升温" value={`${phases.rotation ?? 0} / 20 · ${phases.warming ?? 0} / 20`} />
      </dl>
      <dl className="border-b text-sm">
        <Row label="资格合同" value={forward.qualification_contract_version} />
        <Row label="样本门" value={gate(forward.qualification.sample_gates_passed)} />
        <Row label="收益门" value={gate(forward.qualification.performance_gates_passed)} />
        <Row label="置信门" value={gate(forward.qualification.confidence_gates_passed)} />
        <Row label="全部资格门" value={gate(forward.qualification.all_gates_passed)} strong />
        <Row label="正式验证指标" value={forward.verified_forward_metrics ? "已公开" : "门满前保持为空"} />
      </dl>
      {forward.qualification.failed_gates.length > 0 && (
        <div className="py-4">
          <div className="mb-2 text-xs font-medium text-muted-foreground">尚未通过</div>
          <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm">
            {forward.qualification.failed_gates.map((item) => <span key={item}>{item}</span>)}
          </div>
        </div>
      )}
      <div className="border-t pt-4">
        <div className="mb-3 flex items-center justify-between gap-3">
          <h3 className="text-sm font-semibold">候选与结算流水</h3>
          <span className="text-xs text-muted-foreground">共 {ledger.data?.total ?? 0} 笔</span>
        </div>
        {ledger.isLoading ? (
          <div className="py-8 text-center text-sm text-muted-foreground">正在读取自然流水</div>
        ) : ledger.error ? (
          <div className="py-8 text-center text-sm text-fall">自然流水读取失败</div>
        ) : (ledger.data?.items.length ?? 0) === 0 ? (
          <div className="border-t py-10 text-center text-sm text-muted-foreground">尚无自然日期冻结候选</div>
        ) : (
          <div className="overflow-x-auto border-t">
            <table className="w-full min-w-[980px] text-left text-sm">
              <thead className="bg-muted/30 text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 font-medium">信号日</th>
                  <th className="px-3 py-2 font-medium">龙头</th>
                  <th className="px-3 py-2 font-medium">概念</th>
                  <th className="px-3 py-2 text-right font-medium">排名 / 波段</th>
                  <th className="px-3 py-2 font-medium">支撑</th>
                  <th className="px-3 py-2 font-medium">信号决定</th>
                  <th className="px-3 py-2 font-medium">结算</th>
                  <th className="px-3 py-2 text-right font-medium">收益</th>
                </tr>
              </thead>
              <tbody>
                {ledger.data!.items.map((row) => (
                  <tr key={`${row.signal_trade_date}-${row.vt_symbol}`} className="border-b last:border-b-0">
                    <td className="px-3 py-2.5 font-mono text-xs">{row.signal_trade_date}</td>
                    <td className="min-w-40 px-3 py-2.5"><StockIdentityLink name={row.stock_name} vtSymbol={row.vt_symbol} /></td>
                    <td className="px-3 py-2.5">{row.sector_name}</td>
                    <td className="px-3 py-2.5 text-right tabular-nums">龙{row.rank} / 第{row.current_wave_number}波</td>
                    <td className="px-3 py-2.5">{row.support_line ? `${row.support_line} · ${row.support_price?.toFixed(2) ?? "--"}` : "--"}</td>
                    <td className="px-3 py-2.5"><div>{row.signal_eligible ? "有效" : "排除"}</div><div className="text-xs text-muted-foreground">{row.decision_reason}</div></td>
                    <td className="px-3 py-2.5">{row.outcome_status ?? "等待结果"}</td>
                    <td className={cn("px-3 py-2.5 text-right font-semibold tabular-nums", returnTone(row.net_return_pct))}>{formatOptionalPct(row.net_return_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="border-b border-r px-3 py-3"><dt className="text-xs text-muted-foreground">{label}</dt><dd className="mt-1 font-semibold tabular-nums">{value}</dd></div>;
}

function Row({ label, value, strong = false }: { label: string; value: string; strong?: boolean }) {
  return <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-4 border-b px-3 py-2.5 last:border-b-0"><dt className="text-muted-foreground">{label}</dt><dd className={strong ? "font-semibold" : ""}>{value}</dd></div>;
}

function gate(passed: boolean) {
  return passed ? "通过" : "未通过";
}

function formatOptionalPct(value: number | null) {
  return value == null ? "--" : `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function returnTone(value: number | null) {
  return value == null ? "text-muted-foreground" : value > 0 ? "text-rise" : value < 0 ? "text-fall" : "";
}
