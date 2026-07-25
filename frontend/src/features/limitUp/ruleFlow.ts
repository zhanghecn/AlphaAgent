import type { LimitUpStrategyGuide } from "@/api/limitUp";

export interface RuleThreshold {
  label: string;
  value: string;
}

export type RuleStage = "gate" | "filter" | "radar" | "momentum" | "sector" | "rank" | "fill";

export interface RuleFlowNode {
  id: string;
  stage: RuleStage;
  badge: string;
  title: string;
  /** 这一步想干什么（一句话） */
  purpose: string;
  /** 成立的详细条件 */
  condition: string;
  /** 关键数字门槛 */
  thresholds: RuleThreshold[];
  /** 用到的数据（人话） */
  dataNote: string;
  /** 对应后端字段组 */
  dataGroupKeys: ("intraday" | "prior" | "outcome")[];
  /** 不通过会怎样 */
  failHint?: string;
}

export const STAGE_META: Record<RuleStage, { label: string; tone: string }> = {
  gate: { label: "市场门禁", tone: "border-amber-500/50 bg-amber-500/10 text-amber-700 dark:text-amber-300" },
  filter: { label: "范围筛选", tone: "border-primary/50 bg-primary/10 text-primary" },
  radar: { label: "雷达采集", tone: "border-primary/50 bg-primary/10 text-primary" },
  momentum: { label: "动能确认", tone: "border-rise/50 bg-rise/10 text-rise" },
  sector: { label: "板块确认", tone: "border-rise/50 bg-rise/10 text-rise" },
  rank: { label: "排序优先", tone: "border-foreground/30 bg-muted/60 text-foreground" },
  fill: { label: "成交结算", tone: "border-foreground/30 bg-muted/60 text-foreground" },
};

/**
 * 打板选股流程的可读化重建。
 *
 * 文案基于后端 `alphaagent/server/services/limit_up/` 的真实规则代码
 * （市场门、板位分类、雷达契约、动能分、板块路径、历史胜率、现金结算）。
 * 后端 `strategy_guide.py` 返回的是审计契约文档，保留精确英文术语；
 * 这里把它翻译成给用户看的人话，每步讲清"卡什么、用什么数据、为什么"。
 */
export function buildRuleFlow(guide: LimitUpStrategyGuide): RuleFlowNode[] {
  const windows = guide.strategy.entry_windows;
  const maxPositions = guide.strategy.max_positions;
  const capturePct = guide.preboard_decision.observation_min_change_pct;

  return [
    {
      id: "gate",
      stage: "gate",
      badge: "①",
      title: "先固定正式策略边界",
      purpose: "板前研究只改首板触发时机，不改二进三、两仓、费用和次日退出。",
      condition:
        "正式 v15 的市场风险门和封板/回封扫板继续运行。板前概率链尚未通过历史与独立前向双晋级门时，只显示研究排序，不生成买入提醒，也不占用两个正式仓位。",
      thresholds: [
        { label: "正式首板", value: "v15 扫板保持" },
        { label: "二进三", value: "规则保持" },
        { label: "组合", value: `${maxPositions} 仓保持` },
      ],
      dataNote:
        "正式策略与板前研究使用同一历史首板基线、费用和 D+1 官方收盘结算，差别只在首板触发和排序。",
      dataGroupKeys: ["prior", "outcome"],
    },
    {
      id: "filter",
      stage: "filter",
      badge: "②",
      title: "先过高质量首板母池",
      purpose: "不拿全市场 3% 股票训练或推荐，只研究正式规则本来就会考虑的首板。",
      condition:
        "先按当前正式同源规则检查沪深主板资格、首板身份、财务风险、历史首板结构和同股 D+1 盈利基因。普通 3% 股票即使涨得快，只要没通过这层质量门，就不会进入板前模型。二进三仍走原规则，不进入板前首板模型。",
      thresholds: [
        { label: "同股D+1样本", value: "≥ 5 笔" },
        { label: "封板×D+1联合率", value: "≥ 30%" },
        { label: "股票范围", value: "合格沪深主板首板" },
      ],
      dataNote: "信号日之前已收盘的日线、首板历史、D+1 结果和已披露财务信息。所有统计都要求结算日早于信号日。",
      dataGroupKeys: ["prior"],
      failHint: "质量门失败的股票只留在原始行情，不进入个股概率、排序或推荐。",
    },
    {
      id: "radar",
      stage: "radar",
      badge: "③",
      title: "达到 3% 后启动持续观察",
      purpose: "3% 只是开始跟踪，后续每个新快照都会重新计算概率。",
      condition:
        `只有上一层高质量首板涨幅达到 ${capturePct}% 且当前价仍严格低于涨停价，才进入板前观察池。${capturePct}%、5%、8%、9% 和 9.5% 都不是固定买点；触板后立即退出板前列表，正式 v15 的封板/回封扫板提示仍保留。`,
      thresholds: [
        { label: "观察起点", value: `≥ ${capturePct}%` },
        { label: "板前价格", value: "现价 < 涨停价" },
        { label: "固定买点", value: "无" },
      ],
      dataNote: "实时现价、前收、涨停价和已完成分钟前缀；当前未完成分钟不会提前进入特征。",
      dataGroupKeys: ["intraday"],
    },
    {
      id: "momentum",
      stage: "momentum",
      badge: "④",
      title: "计算上升动能与双触板概率",
      purpose: "不靠单一涨幅阈值，用完整板前路径判断短时和当日触板机会。",
      condition:
        "共享模型同时输出未来 3 个交易分钟内触板概率和当日执行窗口结束前最终触板概率。输入包括当前涨幅、距板、1/3/5 分钟收益、速度、加速度、回撤恢复、量能、逐笔资金代理、质量池横截面和首板承接分；当天最终触板和 D+1 结果只作标签，不能进入输入。",
      thresholds: [
        { label: "短时目标", value: "3 分钟触板概率" },
        { label: "日内目标", value: "最终触板概率" },
        { label: "完成分钟", value: "至少 7 根" },
      ],
      dataNote: "历史与实时调用同一特征投影和同一模型；来源不同只允许发生在分钟行情适配器。",
      dataGroupKeys: ["intraday"],
      failHint: "分钟前缀不足或模型不可用时只保留内部审计样本，不公开板前候选、不补零、不猜概率。",
    },
    {
      id: "sector",
      stage: "sector",
      badge: "⑤",
      title: "板块与资金先做诊断",
      purpose: "保留板块切换线索，但不让历史无法点时复现的字段暗中卡住实时候选。",
      condition:
        "盘中行业扩散、概念启动、龙头排名、板块资金、个股资金、换手率和快照新鲜度继续采集并展示。当前历史覆盖不能按相同可知时点复现，因此统一标记为仅诊断，不参与板前行动硬门；等同源审计通过后才能升级。",
      thresholds: [
        { label: "当前用途", value: "仅诊断" },
        { label: "允许阻断", value: "仅同源字段" },
        { label: "日终回填", value: "禁止" },
      ],
      dataNote: "盘中板块、概念、资金与换手；每项都记录可知时点和同源状态。",
      dataGroupKeys: ["intraday"],
      failHint: "缺失只会降低诊断完整度，不会一边历史缺失、一边实时作为专属硬门。",
    },
    {
      id: "rank",
      stage: "rank",
      badge: "⑥",
      title: "按 D+1 价值和触板概率排序",
      purpose: "先保证次日溢价质量，再在同等质量中优先更可能尽快触板的股票。",
      condition:
        `排序固定为：${guide.preboard_decision.ranking_order.join(" → ")}。涨幅本身不是第一排序键；同股 D+1 预期和胜率来自信号日前已闭合样本，动态模型只负责触板概率。`,
      thresholds: [
        { label: "第一优先", value: "同股 D+1 预期净收益" },
        { label: "第二优先", value: "同股 D+1 胜率" },
        { label: "组合门槛", value: "≥ 5 个历史样本 · 联合胜率 ≥ 30%" },
      ],
      dataNote: "prior-only D+1 基因、双触板概率、触板后封板率和首板承接分。",
      dataGroupKeys: ["prior", "intraday"],
      failHint: "误报一旦在影子或正式模式占仓，后来更强的票不能事后替换。",
    },
    {
      id: "fill",
      stage: "fill",
      badge: "⑦",
      title: "双晋级后补充正式板前买点",
      purpose: "概率会排序不等于收益可靠，且概率层不能删除原扫板买点。",
      condition:
        "历史回放只认行动后第一条严格低于涨停价的新报价；一分钟代理用下一分钟开盘，等于涨停价就算未成交。历史账户通过后只进入影子，两仓误报真实占位；独立前向账户再通过后，才补充正式板前买点和概率排序。原 v15 封板与回封扫板兜底始终保留。D+1 仍按官方收盘价扣除正式费用。",
      thresholds: [
        { label: "买入窗口", value: windows.join("、") },
        { label: "仓位", value: `${maxPositions} 仓 · 误报占位` },
        { label: "板前成交", value: "下一报价 < 涨停价" },
        { label: "卖出", value: "次日尾盘官方收盘价" },
      ],
      dataNote: "点时新报价、正式费用、D+1 官方日线；缺少涨停价排队明细时，扫板只表示可尝试排队。",
      dataGroupKeys: ["intraday", "outcome"],
    },
  ];
}

export const DATA_GROUP_LABELS: Record<string, string> = {
  intraday: "盘中实时",
  prior: "信号前已知",
  outcome: "事后结果",
};
