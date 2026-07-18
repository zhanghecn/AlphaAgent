import {
  CheckCircle2,
  Eye,
  History,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";

import type {
  LimitUpRadarValidation,
  LimitUpStrategyGuide,
} from "@/api/limitUp";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { GuideDataset } from "./GuideDataset";
import { RuleFlowDiagram } from "./RuleFlowDiagram";

interface GuideViewProps {
  guide?: LimitUpStrategyGuide;
  radarValidation?: LimitUpRadarValidation;
  radarValidationLoading?: boolean;
  radarValidationError?: string | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}

export function GuideView({
  guide,
  radarValidation,
  radarValidationLoading = false,
  radarValidationError = null,
  loading,
  error,
  onRetry,
}: GuideViewProps) {
  if (loading && !guide) return <GuideLoading />;
  if (error && !guide) return <GuideError message={error} onRetry={onRetry} />;
  if (!guide) return null;

  const { strategy, ranking } = guide;

  return (
    <section aria-label="打板规则说明" className="px-3 py-4 sm:px-4">
      {/* 一句话说清这是什么策略 */}
      <section className="rounded-lg border bg-card px-4 py-4 sm:px-5">
        <h2 className="text-base font-semibold">这是一个什么策略</h2>
        <p className="mt-2 text-sm leading-6 text-foreground">
          在交易日的<strong className="font-semibold">{strategy.entry_windows.join("、")}</strong>
          两个时段里，买入即将涨停或刚涨停的强势股，第二个交易日（简称 D+1）尾盘按官方收盘价卖出。
          赚的是「涨停的惯性」和「次日的高开溢价」。最多同时持有 {strategy.max_positions} 只，
          每只大约用一半资金，按信号到达的先后顺序成交。
        </p>
        <div className="mt-3 flex items-start gap-2 rounded-md border border-rise/40 bg-rise/5 px-3 py-2">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-rise" />
          <p className="text-sm leading-6 text-foreground">
            <strong className="font-semibold text-rise">规则保证不偷看未来数据</strong>
            ：选股时只用到此刻和此前已经知道的信息；当天这只票最终有没有封住涨停、次日收盘价是多少，
            都要等选股完成之后才用来算收益，绝不倒过来影响选股。
          </p>
        </div>
      </section>

      {/* 七步流程 */}
      <section className="mt-6" aria-labelledby="flow-title">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <h3 id="flow-title" className="text-sm font-semibold">选股到成交，一共七步</h3>
            <p className="mt-1 text-xs text-muted-foreground">
              点击左侧任一步骤，查看它具体卡什么条件、用什么数据、不通过会怎样
            </p>
          </div>
          <span className="text-xs text-muted-foreground">从大盘到个股，层层过滤</span>
        </div>
        <div className="mt-3">
          <RuleFlowDiagram guide={guide} />
        </div>
      </section>

      {/* 防未来函数 + 字段时点 */}
      <section className="mt-6" aria-labelledby="no-lookahead-title">
        <h3 id="no-lookahead-title" className="text-sm font-semibold">怎么做到不偷看未来</h3>
        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          <NoLookaheadCard
            icon={<Eye className="h-4 w-4" />}
            title="信号瞬间定格"
            desc="每只票只用它第一次满足全部条件那一刻的行情画面。即便之后价格又跌回去，也不会回头重新推荐，避免「事后挑最好的那帧」。"
          />
          <NoLookaheadCard
            icon={<History className="h-4 w-4" />}
            title="历史只看已收盘"
            desc="计算历史胜率时，只用「信号日之前就已经收盘出结果」的样本。任何还没出结果的未来数据都不参与统计。"
          />
          <NoLookaheadCard
            icon={<CheckCircle2 className="h-4 w-4" />}
            title="先选股，后算账"
            desc="当天封板结果和次日收盘价，只在选股全部完成后用来计算收益，绝对不会反过来影响当天的选股决定。"
          />
        </div>

        <div className="mt-3 overflow-hidden rounded-lg border">
          <div className="border-b bg-muted/30 px-4 py-2 text-xs font-medium text-muted-foreground">
            哪些数据能用、哪些不能用
          </div>
          <div className="divide-y">
            <FieldGroupRow
              allowed
              label="盘中实时数据"
              hint="买入的那一刻能看到，允许参与选股"
              fields={[
                "当前价、涨幅、涨停价、买卖盘口",
                "盘中承接强度（动能分）与封单变化",
                "封板、开板、回封的实时状态",
                "同行业触板扩散、概念启动与龙头排名",
                "市场情绪阶段与资金流向",
              ]}
            />
            <FieldGroupRow
              allowed
              label="信号之前就已知的数据"
              hint="信号日之前已经存在，允许参与选股"
              fields={[
                "前一交易日及更早的官方日线",
                "信号日之前已收盘的历史封停成功率",
                "信号日之前已收盘的次日赚钱率",
                "当时已经披露的财务报告与风险信息",
              ]}
            />
            <FieldGroupRow
              allowed={false}
              label="事后才知道的结果"
              hint="选股完成后才能确定，禁止参与选股"
              fields={[
                "当天这只票最终有没有封住涨停",
                "次日（D+1）的官方收盘价",
                "扣完费用和滑点之后的净收益",
                "之后的走势与最终排名",
              ]}
            />
          </div>
        </div>
      </section>

      {/* 成交边界 */}
      <section className="mt-6 flex items-start gap-3 rounded-lg border border-amber-500/40 bg-amber-500/5 px-4 py-3">
        <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-300" />
        <div>
          <h3 className="text-sm font-medium">关于成交的诚实说明</h3>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">
            本策略没有逐笔成交和涨停价排队（Level-2）数据。当买价已经到涨停价、需要排队时，
            系统无法确认你的委托是否真的成交，会如实标注「待排队」，而不是假装一定买到了。
            回测里的成交价也包含了滑点，不能理解成每笔委托都一定能按显示价格成交。
          </p>
        </div>
      </section>

      {/* 排序说明 */}
      <section className="mt-6 rounded-lg border bg-card px-4 py-4" aria-labelledby="ranking-title">
        <h3 id="ranking-title" className="text-sm font-semibold">同分票怎么排先后</h3>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          通过全部硬门的票都会保留在推荐里，排序只决定先做谁。首板先看历史胜率，胜率相同再看当前涨幅；
          二进三则按自身的结构、质量和风险排序。
        </p>
        <dl className="mt-3 grid gap-x-6 gap-y-3 text-xs sm:grid-cols-2">
          <Definition label="第一顺位" value={ranking.first_board_primary} />
          <Definition label="第二顺位" value={ranking.first_board_secondary} />
          <Definition label="历史胜率怎么算" value={ranking.historical_win_rate_formula} />
          <Definition label="历史样本截止" value="只用信号日之前已收盘出结果的历史记录" />
        </dl>
        <p className="mt-3 border-l-2 pl-3 text-xs leading-5 text-muted-foreground">
          历史胜率只调整展示顺序，不会删掉已经通过实时硬门的推荐。{ranking.portfolio_gate}。
        </p>
      </section>

      {/* 验证数据 */}
      <div className="mt-8 border-t pt-5">
        <Tabs defaultValue="dataset">
          <TabsList className="grid h-9 w-full grid-cols-1 sm:w-56">
            <TabsTrigger value="dataset" className="py-1 text-xs">验证数据与历史回测</TabsTrigger>
          </TabsList>
          <TabsContent value="dataset" className="m-0 mt-4">
            <GuideDataset
              guide={guide}
              radarValidation={radarValidation}
              radarValidationLoading={radarValidationLoading}
              radarValidationError={radarValidationError}
            />
          </TabsContent>
        </Tabs>
      </div>
    </section>
  );
}

function NoLookaheadCard({ icon, title, desc }: { icon: React.ReactNode; title: string; desc: string }) {
  return (
    <div className="rounded-lg border bg-card px-4 py-3">
      <div className="flex items-center gap-2 text-rise">
        {icon}
        <span className="text-sm font-semibold">{title}</span>
      </div>
      <p className="mt-2 text-xs leading-5 text-muted-foreground">{desc}</p>
    </div>
  );
}

function FieldGroupRow({
  allowed,
  label,
  hint,
  fields,
}: {
  allowed: boolean;
  label: string;
  hint: string;
  fields: string[];
}) {
  return (
    <div className="px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={cn(
            "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium",
            allowed ? "bg-rise/10 text-rise" : "bg-fall/10 text-fall",
          )}
        >
          {allowed ? <CheckCircle2 className="h-3 w-3" /> : <TriangleAlert className="h-3 w-3" />}
          {allowed ? "允许参与选股" : "禁止参与选股"}
        </span>
        <span className="text-sm font-semibold">{label}</span>
        <span className="text-[11px] text-muted-foreground">{hint}</span>
      </div>
      <ul className="mt-2 grid gap-x-6 gap-y-0.5 text-[11px] leading-5 text-muted-foreground sm:grid-cols-2">
        {fields.map((field) => (
          <li key={field}>· {field}</li>
        ))}
      </ul>
    </div>
  );
}

function Definition({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className={cn("mt-1 leading-5 text-foreground", mono && "font-mono text-[11px]")}>{value}</dd>
    </div>
  );
}

function GuideLoading() {
  return (
    <div className="space-y-3 px-5 py-6" aria-label="规则说明读取中">
      <div className="h-16 animate-pulse bg-muted" />
      <div className="h-9 w-64 animate-pulse bg-muted" />
      <div className="h-48 animate-pulse bg-muted" />
    </div>
  );
}

function GuideError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="px-5 py-12 text-center">
      <TriangleAlert className="mx-auto h-6 w-6 text-destructive" />
      <p className="mt-3 text-sm text-destructive">{message}</p>
      <Button type="button" variant="outline" size="sm" className="mt-4" onClick={onRetry}>
        重新读取
      </Button>
    </div>
  );
}
