import { useState } from "react";
import { ChevronDown } from "lucide-react";

import type { J12LiveEntry, J12LivePayload } from "@/api/firstRelay";
import { EmptyState } from "@/components/EmptyState";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { SyncStatusBar } from "@/components/SyncStatusBar";
import { cn, formatPrice } from "@/lib/utils";

const SESSION_LABELS: Record<string, string> = {
  preopen: "盘前",
  auction: "竞价时段",
  first_window: "早盘(09:30~09:45)",
  morning: "上午盘",
  lunch: "午间休市",
  afternoon: "下午盘",
  closed: "已收盘",
};

/** 两分支徽章(对齐 hpr POINT_BADGES 体系:G1 出手红 / S1 观察琥珀)。 */
const POINT_BADGES: Record<string, { label: string; full: string; className: string }> = {
  G1: {
    label: "G1",
    full: "G1 阴坑满开(出手):阴线地基 × 今开7.5~9.5",
    className: "bg-rise/15 text-rise ring-1 ring-rise/40",
  },
  S1: {
    label: "S1",
    full: "S1 阳坑半开(观察):阳线地基 × 前10日<-3% × 今开7.5~8.5",
    className: "bg-amber-500/15 text-amber-500 ring-1 ring-amber-500/40",
  },
};

const PLAYBOOK = [
  "盘后主链自动算次日池:昨日恰好 1 板(孤立首板)全量入雷达,G1/S1 候选标好",
  "9:25 竞价定型,对照「需今开窗」:G1 阴坑开 7.5~9.5、S1 阳坑开 7.5~8.5,窗内才出手",
  "开盘≥9.5 顶格不追(无预期差,接炸板);地基贴 60 日高点(0~10%)的命中也不买(力竭)",
  "第一次碰到涨停价 → 涨停价打板买入;二板开盘一字的票不进池(买不进)",
  "买入当天炸板 → 当天收盘卖;封住 → 拿到不再涨停那天收盘卖,15 天兜底;昨天封板+今开≤-5% → 竞价直接卖",
];

const BONUS_TONE: Record<string, { label: string; className: string }> = {
  锁板: { label: "锁板", className: "bg-blue-500/15 text-blue-500" },
  动量深坑: { label: "动量深坑", className: "bg-violet-500/15 text-violet-500" },
  秒板: { label: "秒板", className: "bg-teal-500/15 text-teal-500" },
};

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
          <span className="text-sm font-semibold text-foreground">一接二 · 实时推荐</span>
          <span className="font-mono tabular-nums">{payload.trade_date}</span>
          <span>{SESSION_LABELS[payload.session_stage] ?? payload.session_stage}</span>
          {payload.stale ? (
            <span className="rounded border border-amber-500/40 px-1.5 py-0.5 text-amber-500">
              非当日(最新可用池)
            </span>
          ) : null}
          <span>首板池 {counts.pool}</span>
          <span className="text-rise">G1 {counts.act_G1}</span>
          <span className="text-amber-500">S1 {counts.act_S1}</span>
          <span className="font-semibold text-rise">出手候选 {counts.actionable}</span>
          <span className="ml-auto flex items-center gap-2">
            <select
              className="h-8 rounded-md border bg-background px-2 text-xs"
              value={selectedDate ?? ""}
              onChange={(e) => onDateChange(e.target.value || null)}
              aria-label="选择回看交易日"
            >
              <option value="">实时</option>
              {availableDates.map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
          </span>
        </div>

        <div className="border-b bg-primary/5 px-4 py-2 font-mono text-xs text-primary">
          {payload.koujue}
        </div>

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
            盘中执行要点(竞价定型对照今开窗,命中分支触板即打)
          </button>
          {playbookOpen ? (
            <ol className="mt-2 list-decimal space-y-1 pl-5 text-xs text-muted-foreground">
              {PLAYBOOK.map((line) => <li key={line}>{line}</li>)}
            </ol>
          ) : null}
        </div>

        {entries.length === 0 ? (
          <div className="p-4">
            <EmptyState message="今日池为空——盘后统一更新链会自动计算次日池" />
          </div>
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
                  <th className="px-3 py-2 text-left font-medium">加分</th>
                  <th className="px-3 py-2 text-left font-medium">竞价窗</th>
                  <th className="px-3 py-2 text-right font-medium">昨收</th>
                  <th className="px-3 py-2 text-right font-medium">触发价</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry) => (
                  <LiveRow key={entry.vt_symbol} entry={entry} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function LiveRow({ entry }: { entry: J12LiveEntry }) {
  const badge = POINT_BADGES[entry.point] ?? null;
  const active = entry.actionable;
  const gate = entry.auction_gate;          // "7.5_9.5"
  const gateWin = gate ? gate.split("_") : null;
  const avoided = entry.avoid_static != null && entry.avoid_static !== "";
  return (
    <tr className={cn("border-b last:border-b-0 hover:bg-muted/30", !active && "opacity-50")}>
      <td className="px-3 py-2.5">
        <StockIdentityLink name={entry.name ?? entry.vt_symbol} vtSymbol={entry.vt_symbol} />
      </td>
      <td className="px-3 py-2.5">
        {badge ? (
          <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-medium", badge.className)} title={badge.full}>
            {badge.label}
          </span>
        ) : (
          <span className="text-muted-foreground/60">—</span>
        )}
      </td>
      <td className="px-3 py-2.5 text-xs">
        {active ? (
          entry.level === "A" ? (
            <span className="font-semibold text-rise" title="G1 出手级(六年分年全正)">✅出手</span>
          ) : (
            <span className="font-semibold text-amber-500" title="S1 观察级(五年检验B级,顺手轻仓)">🟡观察</span>
          )
        ) : avoided ? (
          <span className="text-amber-600" title={entry.avoid_static ?? undefined}>回避</span>
        ) : (
          <span className="text-muted-foreground/60">雷达</span>
        )}
      </td>
      <td className="px-3 py-2.5 text-xs text-muted-foreground">打2板</td>
      <td className="px-3 py-2.5 text-xs" title={`距20日线 ${entry.dist_ma20?.toFixed(1) ?? "--"}% · 地基涨跌 ${entry.foundation_chg?.toFixed(1) ?? "--"}%`}>
        {entry.foundation_yang == null ? "--" : entry.foundation_yang ? "阳" : "阴"}
        {entry.foundation_chg != null && ` ${entry.foundation_chg > 0 ? "+" : ""}${entry.foundation_chg.toFixed(1)}%`}
        {entry.dist_h60 != null && <span className="text-muted-foreground"> 新高{entry.dist_h60.toFixed(0)}%</span>}
      </td>
      <td className="px-3 py-2.5 text-xs text-muted-foreground" title={`开盘 ${entry.b1_open?.toFixed(1) ?? "--"}%`}>
        {entry.b1_type ?? "--"}
        {entry.b1_open != null && ` ${entry.b1_open > 0 ? "+" : ""}${entry.b1_open.toFixed(1)}%`}
        {entry.b1_turn != null && <span className="text-muted-foreground"> 换手{entry.b1_turn.toFixed(1)}</span>}
      </td>
      <td className="px-3 py-2.5 text-xs text-muted-foreground" title="地基前60日板史(有人做过的票才接得住)">
        {entry.chassis ?? "--"}
      </td>
      <td className="px-3 py-2.5 font-mono text-xs tabular-nums">
        {entry.pre10_pct == null ? "--" : `${entry.pre10_pct > 0 ? "+" : ""}${entry.pre10_pct.toFixed(1)}%`}
      </td>
      <td className="px-3 py-2.5">
        <div className="flex flex-wrap gap-1">
          {(entry.bonus ?? "").split(",").filter(Boolean).map((b) => (
            <span
              key={b}
              className={cn("rounded px-1.5 py-0.5 text-[10px]", BONUS_TONE[b]?.className ?? "bg-muted text-muted-foreground")}
              title="特征标签(看盘参考,仓位二值化:命中即满仓)"
            >
              {BONUS_TONE[b]?.label ?? b}
            </span>
          ))}
          {!entry.bonus && <span className="text-xs text-muted-foreground/60">—</span>}
        </div>
      </td>
      <td className="px-3 py-2.5 font-mono text-xs tabular-nums">
        {gateWin ? (
          <span title={entry.action_hint ?? undefined}>
            需{gateWin[0]}~{gateWin[1]}
          </span>
        ) : (
          <span className="text-muted-foreground/60">—</span>
        )}
      </td>
      <td className="px-3 py-2.5 text-right font-mono tabular-nums">{formatPrice(entry.prev_close)}</td>
      <td className="px-3 py-2.5 text-right font-mono tabular-nums text-primary">
        {formatPrice(entry.limit_price)}
        <span className="ml-1 text-[10px] text-muted-foreground">封板价</span>
      </td>
    </tr>
  );
}
