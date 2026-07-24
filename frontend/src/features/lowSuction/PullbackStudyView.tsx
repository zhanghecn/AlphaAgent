import { Fragment } from "react";
import { PanelHead } from "@/components/PanelHead";
import { cn } from "@/lib/utils";
import { formatNumber, formatPct, formatRate, rateTone } from "./format";

/**
 * 回踩低吸（研究观察）页。
 *
 * 这是路 B 变体——"回踩支撑当天直接买入"的真低吸，与反包（转强确认日买入）本质不同。
 * 全量漏斗回测已证伪（PF 0.75），不作推荐，仅作为冻结的研究结论展示，封存该方向。
 *
 * 数据为冻结的研究结果（support_day_entry_variant_study，2024-08..2026-07），
 * 不是实时策略；研究结论不随行情变化，故内嵌而非实时计算。
 */
const FROZEN = {
  studyVersion: "support-day-entry-variant-v1",
  parentTouches: 8504,
  variant: {
    signals: 6309,
    trades: 2484,
    winRate: 31.84,
    meanReturn: -0.63,
    profitFactor: 0.75,
    compound: -61.51,
    drawdown: -75.82,
  },
  exitReasons: [
    { reason: "support_broken", label: "支撑跌破止损", count: 1767, pct: 71.1 },
    { reason: "higher_high_confirmed", label: "创新高确认", count: 615, pct: 24.8 },
    { reason: "structural_break", label: "结构破坏", count: 67, pct: 2.7 },
    { reason: "concept_campaign_ended", label: "概念结束", count: 35, pct: 1.4 },
  ],
  cuts: [
    { label: "收盘守支撑", yes: { trades: 1476, win: 33.06, pf: 0.8 }, no: { trades: 1008, win: 30.06, pf: 0.66 } },
    { label: "第一波 vs 后续波段", yes: { trades: 1294, win: 31.22, pf: 0.66 }, no: { trades: 1190, win: 32.52, pf: 0.86 } },
  ],
  reverseWrap: { winRate: 76.4, profitFactor: 4.38 },
};

export function PullbackStudyView() {
  return (
    <div className="min-w-0">
      <div className="rounded-md border border-amber-500/40 bg-amber-500/5 px-3 py-3 text-xs leading-6 sm:px-4">
        <div className="font-semibold text-amber-700 dark:text-amber-300">研究观察 · 不作推荐</div>
        <p className="mt-1 text-muted-foreground">
          这是「回踩支撑当天直接买入」的真低吸变体，与<span className="text-foreground font-medium">反包</span>（转强确认日买入）本质不同。
          全量漏斗回测（{FROZEN.parentTouches.toLocaleString()} 次支撑触碰）已证伪：胜率 {FROZEN.variant.winRate}%、PF {FROZEN.variant.profitFactor}、两仓复利 {FROZEN.variant.compound}%。
          下方为冻结的研究结论，仅作方向封存，不产生任何信号或推荐。
        </p>
      </div>

      <div className="mt-4">
        <PanelHead no="01" zh="全量漏斗回测" en="REJECTED VARIANT" note={FROZEN.studyVersion} />
        <dl className="grid grid-cols-2 border-l sm:grid-cols-3">
          <Metric label="支撑触碰母集合" value={`${FROZEN.parentTouches.toLocaleString()} 次`} />
          <Metric label="变体信号" value={`${FROZEN.variant.signals.toLocaleString()} 个`} />
          <Metric label="非重叠成交" value={`${FROZEN.variant.trades.toLocaleString()} 笔`} />
          <Metric label="胜率" value={formatRate(FROZEN.variant.winRate)} tone="text-fall" />
          <Metric label="单笔均值" value={formatPct(FROZEN.variant.meanReturn)} tone="text-fall" />
          <Metric label="利润因子" value={formatNumber(FROZEN.variant.profitFactor)} tone="text-fall" />
          <Metric label="两仓复利" value={formatPct(FROZEN.variant.compound)} tone="text-fall" />
          <Metric label="最大回撤" value={formatPct(FROZEN.variant.drawdown)} tone="text-fall" />
        </dl>
      </div>

      <section className="border-t py-5">
        <PanelHead no="02" zh="退出原因分布" en="EXIT BREAKDOWN" note="71% 止损出局——多数买到的是飞刀" />
        <div className="overflow-x-auto border-t">
          <table className="w-full min-w-[480px] text-left text-sm">
            <thead className="bg-muted/30 text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">退出原因</th>
                <th className="px-3 py-2 text-right font-medium">笔数</th>
                <th className="px-3 py-2 text-right font-medium">占比</th>
              </tr>
            </thead>
            <tbody>
              {FROZEN.exitReasons.map((r) => (
                <tr key={r.reason} className="border-b last:border-b-0">
                  <td className="px-3 py-2.5">{r.label}</td>
                  <td className="px-3 py-2.5 text-right tabular-nums">{r.count.toLocaleString()}</td>
                  <td className={cn("px-3 py-2.5 text-right tabular-nums", r.reason === "support_broken" ? "text-fall" : "")}>{r.pct}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="border-t py-5">
        <PanelHead no="03" zh="预登记切分（全部失败）" en="PRE-REGISTERED CUTS" note="没有任何子切 PF≥1" />
        <div className="overflow-x-auto border-t">
          <table className="w-full min-w-[560px] text-left text-sm">
            <thead className="bg-muted/30 text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">切分</th>
                <th className="px-3 py-2 font-medium">分组</th>
                <th className="px-3 py-2 text-right font-medium">交易</th>
                <th className="px-3 py-2 text-right font-medium">胜率</th>
                <th className="px-3 py-2 text-right font-medium">PF</th>
              </tr>
            </thead>
            <tbody>
              {FROZEN.cuts.map((cut) => (
                <Fragment key={cut.label}>
                  <tr className="border-b">
                    <td className="px-3 py-2.5">{cut.label}</td>
                    <td className="px-3 py-2.5">是</td>
                    <td className="px-3 py-2.5 text-right tabular-nums">{cut.yes.trades}</td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-fall">{formatRate(cut.yes.win)}</td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-fall">{formatNumber(cut.yes.pf)}</td>
                  </tr>
                  <tr className="border-b">
                    <td className="px-3 py-2.5">{cut.label}</td>
                    <td className="px-3 py-2.5">否</td>
                    <td className="px-3 py-2.5 text-right tabular-nums">{cut.no.trades}</td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-fall">{formatRate(cut.no.win)}</td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-fall">{formatNumber(cut.no.pf)}</td>
                  </tr>
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="border-t py-5">
        <PanelHead no="04" zh="对照：反包（转强确认日买入）" en="CONTROL" note="转强确认才是 alpha 源" />
        <div className="grid grid-cols-2 border-l sm:grid-cols-2">
          <Metric label="回踩日入场（本页）胜率" value={formatRate(FROZEN.variant.winRate)} tone="text-fall" />
          <Metric label="反包（转强确认）胜率" value={formatRate(FROZEN.reverseWrap.winRate)} tone={rateTone(FROZEN.reverseWrap.winRate - 50)} />
          <Metric label="回踩日入场 PF" value={formatNumber(FROZEN.variant.profitFactor)} tone="text-fall" />
          <Metric label="反包 PF" value={formatNumber(FROZEN.reverseWrap.profitFactor)} tone={rateTone(FROZEN.reverseWrap.profitFactor)} />
        </div>
        <p className="mt-3 px-3 text-xs leading-5 text-muted-foreground">
          转强确认（≥8% 收复且接近前高）把 6,309 次触碰筛成 204 个信号，换来 44.6 个百分点的胜率差——
          那 10% 的确认溢价买的就是这个筛选。裸买回踩省掉的确认，恰恰是 alpha 本身。
        </p>
      </section>

      <div className="border-t py-4 text-xs text-muted-foreground">
        <span className="font-medium text-foreground">结论</span>：真低吸（回踩日买入）在日线 alpha 边界外不可行；
        预登记切分全 PF&lt;1，不再迭代此方向。证据档见
        <code className="mx-1 rounded bg-muted px-1 py-0.5">memory/06_backtests/low_suction_support_day_entry_variant_20260722.md</code>。
      </div>
    </div>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return <div className="border-b border-r px-3 py-3"><dt className="text-xs text-muted-foreground">{label}</dt><dd className={cn("mt-1 font-semibold tabular-nums", tone)}>{value}</dd></div>;
}
