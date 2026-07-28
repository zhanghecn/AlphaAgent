import {
  CheckCircle2,
  Eye,
  History,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";

import type { LimitUpStrategyGuide } from "@/api/limitUp";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { GuideDataset } from "./GuideDataset";
import { RuleFlowDiagram } from "./RuleFlowDiagram";

interface GuideViewProps {
  guide?: LimitUpStrategyGuide;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}

export function GuideView({
  guide,
  loading,
  error,
  onRetry,
}: GuideViewProps) {
  if (loading && !guide) return <GuideLoading />;
  if (error && !guide) return <GuideError message={error} onRetry={onRetry} />;
  if (!guide) return null;

  const { strategy, ranking, core_quality: core } = guide;

  return (
    <section aria-label="打板规则说明" className="px-3 py-4 sm:px-4">
      {/* 一句话说清这是什么策略 */}
      <section className="rounded-lg border bg-card px-4 py-4 sm:px-5">
        <h2 className="text-base font-semibold">这是一个什么策略</h2>
        <p className="mt-2 text-sm leading-6 text-foreground">
          唯一正式合同是 <strong className="font-semibold">{core.contract_version}</strong>。
          它先检查正确财报点时、原低位结构、盘中支撑和板位质量，再要求过去
          {core.prior_limit_window_days} 个交易日涨停 {core.minimum_prior_limit_count} 到
          {core.maximum_prior_limit_count} 次形成 A/B 基座，并用资金与概念扩散交叉每天补一笔 C。
          A/B/C 层级先验与个股既有 D+1 样本收缩后，质量胜率至少
          {(core.minimum_quality_win_probability * 100).toFixed(0)}% 且 D+1 预期为正。在
          <strong className="font-semibold">{strategy.entry_windows.join("、")}</strong>
          开盘后持续实时计算；当前正式买点必须等真实触板或回封发生，再复核完整公共质量门。
          D+1 按官方收盘价退出。实时列表展示全部合格信号，同一交易日可以有多笔。
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
            title="每个点时单独冻结"
            desc="每次决策只用该时刻已经披露的财报、已完成日线和盘中证据，后续封板及次日结果只在特征冻结后连接。"
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
                "当前价、涨幅、涨停价与正式买入窗口",
                "截至候选触板时同概念已封板数与最高板",
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
                "前一日市场阶段与个股前 5 日收益",
              ]}
            />
            <FieldGroupRow
              allowed={false}
              label="当前仅作诊断的盘中环境"
              hint="历史暂不能按同一可知时点复现，不得成为实时专属硬门"
              fields={[
                "未冻结成员时点的概念启动与事后龙头排名",
                "板块资金、个股资金与当前换手",
                "市场状态、快照新鲜度与报价新鲜度",
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
            历史买入价是正式触发时保存的价格代理，并按统一规则计入滑点与费用。
            由于缺少真实涨停价排队明细，只能标为可尝试排队，不能解释为一定成交。
          </p>
        </div>
      </section>

      {/* A/C/B 排序说明 */}
      <section className="mt-6 rounded-lg border bg-card px-4 py-4" aria-labelledby="ranking-title">
        <h3 id="ranking-title" className="text-sm font-semibold">A+C+B 怎么排先后</h3>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          D-1 所属行业成交额不低于此前 5 日基准的是 A，未扩张或数据不可用的是 B。
          C 是当日此前尚无 A/B 时，由低位回撤、行业资金或早期概念扩散交叉恢复的第一笔机会。
          同一时点按 A、C、B 排序，跨时点保持真实到达顺序。
        </p>
        <dl className="mt-3 grid gap-x-6 gap-y-3 text-xs sm:grid-cols-2">
          <Definition label="第一顺位" value="A · 行业成交额正在扩张" />
          <Definition label="第二顺位" value="C · 资金与概念扩散补位" />
          <Definition label="第三顺位" value="B · 10:30 后首触或回封" />
          <Definition label="首板基础盈利门" value={ranking.portfolio_gate} />
          <Definition label="历史样本截止" value="只用信号日之前已闭合的历史记录" />
        </dl>
        <p className="mt-3 border-l-2 pl-3 text-xs leading-5 text-muted-foreground">
          正式推荐不限仓位，全部进入 D+1 全量质量统计。回测账户才按一仓或两仓模拟成交，
          两仓尚无 A 时只使用一个非 A 仓。C 的早期历史成员含代理证据，页面会持续标记其自然前向尚未确认。
        </p>
      </section>

      {/* 验证证据 */}
      <div className="mt-8 border-t pt-5">
        <Tabs defaultValue="dataset">
          <TabsList className="grid h-9 w-full grid-cols-1 sm:w-56">
            <TabsTrigger value="dataset" className="py-1 text-xs">历史证据与自然前向</TabsTrigger>
          </TabsList>
          <TabsContent value="dataset" className="m-0 mt-4">
            <GuideDataset
              guide={guide}
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
