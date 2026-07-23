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

  const { strategy, ranking } = guide;

  return (
    <section aria-label="打板规则说明" className="px-3 py-4 sm:px-4">
      {/* 一句话说清这是什么策略 */}
      <section className="rounded-lg border bg-card px-4 py-4 sm:px-5">
        <h2 className="text-base font-semibold">这是一个什么策略</h2>
        <p className="mt-2 text-sm leading-6 text-foreground">
          在交易日的<strong className="font-semibold">{strategy.entry_windows.join("、")}</strong>
          两个时段里，买入即将涨停或刚涨停的强势股，第二个交易日（简称 D+1）尾盘按官方收盘价卖出。
          赚的是「涨停的惯性」和「次日的高开溢价」。实时全量买点列表不限制数量；
          两仓资金组合最多同时持有 {strategy.max_positions} 只，每只大约用一半资金，按信号到达的先后顺序成交。
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
            desc="板前模型每次只用该时刻已经完成的分钟和逐笔前缀，后续触板、封板及次日结果只在特征冻结后连接。"
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
                "当前价、涨幅、涨停价与已完成分钟",
                "1/3/5分钟收益、速度、加速度与回撤恢复",
                "量能、逐笔资金代理与质量池横截面",
                "严格板前价格和正式买入窗口",
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
              label="当前仅作诊断的盘中环境"
              hint="历史暂不能按同一可知时点复现，不得成为实时专属硬门"
              fields={[
                "板块扩散、概念启动与龙头排名",
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
            板前回放只认行动后的第一条严格低于涨停价的新报价；下一报价已经涨停就算未成交。
            正式扫板缺少涨停价排队明细，仍只能标为可尝试排队，不能解释为一定成交。
          </p>
        </div>
      </section>

      {/* 排序说明 */}
      <section className="mt-6 rounded-lg border bg-card px-4 py-4" aria-labelledby="ranking-title">
        <h3 id="ranking-title" className="text-sm font-semibold">板前候选怎么排先后</h3>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          先按同股 D+1 预期净收益和胜率保证次日溢价质量，再看 3 分钟触板、最终触板、封板率和承接分。
          当前涨幅只参与动态概率，不是固定买点，也不是第一排序键。二进三继续使用原排序。
        </p>
        <dl className="mt-3 grid gap-x-6 gap-y-3 text-xs sm:grid-cols-2">
          <Definition label="第一顺位" value={ranking.first_board_primary} />
          <Definition label="第二顺位" value={ranking.first_board_secondary} />
          <Definition label="同股基因怎么算" value={ranking.historical_win_rate_formula} />
          <Definition label="历史样本截止" value="只用信号日之前已收盘出结果的历史记录" />
        </dl>
        <p className="mt-3 border-l-2 pl-3 text-xs leading-5 text-muted-foreground">
          当前板前排序为研究观察，不生成正式买点。{ranking.portfolio_gate}。
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
