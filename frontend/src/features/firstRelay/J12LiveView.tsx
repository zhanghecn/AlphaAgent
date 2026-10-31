import { useState } from "react";
import { ChevronDown } from "lucide-react";

import type { J12LiveEntry, J12LivePayload } from "@/api/firstRelay";
import { EmptyState } from "@/components/EmptyState";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { SyncStatusBar } from "@/components/SyncStatusBar";
import { cn, formatPrice } from "@/lib/utils";
import { formatAuctionGates } from "./utils";

const SESSION_LABELS: Record<string, string> = {
  preopen: "盘前",
  auction: "竞价时段",
  first_window: "早盘(09:30~09:45)",
  morning: "上午盘",
  lunch: "午间休市",
  afternoon: "下午盘",
  closed: "已收盘",
};

const PLAYBOOK = [
  "盘后生成次日孤立首板池，F1~F10 任一命中即为综合候选，同票同日只算一笔",
  "只有 F3、F6、F9 需要复核今开窗；同时命中无窗规则时，不再额外要求今开",
  "二板开盘已是涨停价则不买；盘中最高价严格突破 +9% 才按触发价买入",
  "开盘已经高于触发价且未到涨停价时按开盘价买入；只过 +9%、后来未触板也算事件",
  "买入日未封住则次日尾盘卖；封住则持有到断板尾盘；一字跌停顺延，15 个交易日兜底",
];

export function J12LiveView({
  payload,
  availableDates,
  selectedDate,
  onDateChange,
}: {
  payload: J12LivePayload;
  availableDates: string[];
  selectedDate: string | null;
  onDateChange: (date: string | null) => void;
}) {
  const [playbookOpen, setPlaybookOpen] = useState(false);
  const entries = payload.entries ?? [];
  const counts = payload.counts;

  return (
    <div className="space-y-4">
      <section aria-label="一接二实时推荐" className="rounded-lg border">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b px-4 py-3 text-xs text-muted-foreground">
          <span className="text-sm font-semibold text-foreground">一接二 · 综合最终版</span>
          <span className="font-mono tabular-nums">{payload.trade_date}</span>
          <span>{SESSION_LABELS[payload.session_stage] ?? payload.session_stage}</span>
          {payload.stale ? (
            <span className="rounded border border-amber-500/40 px-1.5 py-0.5 text-amber-500">非当日(最新可用池)</span>
          ) : null}
          <span>首板池 {counts.pool}</span>
          <span className="font-semibold text-rise">出手候选 {counts.actionable}</span>
          <span>信号 {counts.signals}</span>
          <span className="ml-auto flex items-center gap-2">
            <select
              className="h-8 rounded-md border bg-background px-2 text-xs"
              value={selectedDate ?? ""}
              onChange={(e) => onDateChange(e.target.value || null)}
              aria-label="选择回看交易日"
            >
              <option value="">实时</option>
              {availableDates.map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          </span>
        </div>

        <div className="border-b bg-primary/5 px-4 py-2 font-mono text-xs text-primary">{payload.koujue}</div>

        <SyncStatusBar
          scan={null}
          tradeDate={payload.trade_date}
          stale={payload.stale}
          eodJobId="j12_eod_finalize"
          rebuildAt="23:05"
        />

        <div className="border-b px-4 py-2">
          <button
            type="button"
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            onClick={() => setPlaybookOpen((v) => !v)}
            aria-expanded={playbookOpen}
          >
            <ChevronDown size={13} className={cn(playbookOpen && "rotate-180")} />
            盘中执行要点(严格 +9% 触发)
          </button>
          {playbookOpen ? (
            <ol className="mt-2 list-decimal space-y-1 pl-5 text-xs text-muted-foreground">
              {PLAYBOOK.map((line) => <li key={line}>{line}</li>)}
            </ol>
          ) : null}
        </div>

        {entries.length === 0 ? (
          <div className="p-4"><EmptyState message="当前版本池为空——盘后统一更新链会计算次日池" /></div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1180px] text-sm">
              <thead className="border-b bg-muted/30 text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">股票</th>
                  <th className="px-3 py-2 text-left font-medium">方案点</th>
                  <th className="px-3 py-2 text-left font-medium">级别</th>
                  <th className="px-3 py-2 text-left font-medium">打板</th>
                  <th className="px-3 py-2 text-left font-medium">地基</th>
                  <th className="px-3 py-2 text-left font-medium">首板(昨天)</th>
                  <th className="px-3 py-2 text-left font-medium">底盘</th>
                  <th className="px-3 py-2 text-left font-medium">前10日</th>
                  <th className="px-3 py-2 text-left font-medium">同中</th>
                  <th className="px-3 py-2 text-left font-medium">竞价窗</th>
                  <th className="px-3 py-2 text-right font-medium">昨收</th>
                  <th className="px-3 py-2 text-right font-medium">+9%触发价</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry) => <LiveRow key={entry.vt_symbol} entry={entry} />)}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function LiveRow({ entry }: { entry: J12LiveEntry }) {
  const active = entry.actionable;
  return (
    <tr className={cn("border-b last:border-b-0 hover:bg-muted/30", !active && "opacity-50")}>
      <td className="px-3 py-2.5"><StockIdentityLink name={entry.name ?? entry.vt_symbol} vtSymbol={entry.vt_symbol} /></td>
      <td className="px-3 py-2.5">
        {entry.point !== "—" ? (
          <span className="rounded bg-rise/15 px-1.5 py-0.5 text-[10px] font-medium text-rise ring-1 ring-rise/40" title={entry.action_hint ?? undefined}>
            {entry.point}
          </span>
        ) : <span className="text-muted-foreground/60">—</span>}
      </td>
      <td className="px-3 py-2.5 text-xs">
        {active ? <span className="font-semibold text-rise">出手</span> : <span className="text-muted-foreground/60">雷达</span>}
      </td>
      <td className="px-3 py-2.5 text-xs text-muted-foreground">打2板</td>
      <td className="px-3 py-2.5 text-xs" title={`距20日线 ${entry.dist_ma20?.toFixed(1) ?? "--"}% · 地基涨跌 ${entry.foundation_chg?.toFixed(1) ?? "--"}%`}>
        {entry.foundation_yang == null ? "--" : entry.foundation_yang ? "阳" : "阴"}
        {entry.foundation_chg != null && ` ${entry.foundation_chg > 0 ? "+" : ""}${entry.foundation_chg.toFixed(1)}%`}
        {entry.dist_h60 != null && <span className="text-muted-foreground"> 距高{entry.dist_h60.toFixed(0)}%</span>}
      </td>
      <td className="px-3 py-2.5 text-xs text-muted-foreground" title={`开盘 ${entry.b1_open?.toFixed(1) ?? "--"}%`}>
        {entry.b1_type ?? "--"}
        {entry.b1_open != null && ` ${entry.b1_open > 0 ? "+" : ""}${entry.b1_open.toFixed(1)}%`}
        {entry.b1_turn != null && <span className="text-muted-foreground"> 换手{entry.b1_turn.toFixed(1)}</span>}
      </td>
      <td className="px-3 py-2.5 text-xs text-muted-foreground">{entry.chassis ?? "--"}</td>
      <td className="px-3 py-2.5 font-mono text-xs tabular-nums">
        {entry.pre10_pct == null ? "--" : `${entry.pre10_pct > 0 ? "+" : ""}${entry.pre10_pct.toFixed(1)}%`}
      </td>
      <td className="px-3 py-2.5 text-xs text-muted-foreground" title={entry.rule_ids ?? undefined}>
        {entry.bonus?.replace("同中", "") || "—"}
      </td>
      <td className="px-3 py-2.5 font-mono text-xs tabular-nums" title={entry.action_hint ?? undefined}>
        {formatAuctionGates(entry.auction_gate)}
      </td>
      <td className="px-3 py-2.5 text-right font-mono tabular-nums">{formatPrice(entry.prev_close)}</td>
      <td className="px-3 py-2.5 text-right font-mono tabular-nums text-primary" title={`封板价 ${formatPrice(entry.limit_price)}`}>
        {formatPrice(entry.trigger_price)}
      </td>
    </tr>
  );
}
