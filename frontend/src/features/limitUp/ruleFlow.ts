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
  const capturePct = guide.radar_evidence.capture_min_change_pct;
  const formalPct = guide.radar_evidence.formal_min_change_pct;

  return [
    {
      id: "gate",
      stage: "gate",
      badge: "①",
      title: "大盘环境是否允许出手",
      purpose: "大势不好就不开仓，避免在烂行情里追涨被套。",
      condition:
        "同时满足：处于交易时段、主板封住涨停的家数足够多、实时炸板率没有超标、前一日市场情绪没有崩坏（或今日盘中已经修复）。任一条不满足，当天直接空仓，一只都不买。",
      thresholds: [
        { label: "主板封板家数", value: "≥ 5 只" },
        { label: "实时炸板率", value: "≤ 35%" },
        { label: "前日情绪", value: "未崩坏或已盘中修复" },
      ],
      dataNote:
        "全市场实时封板数与炸板数、当日市场情绪阶段（冰点/退潮等）、买卖盘资金流向——这些都是盘中实时数据。",
      dataGroupKeys: ["intraday"],
      failHint: "市场门关闭时，下面所有个股买点都不会触发，保持现金。",
    },
    {
      id: "filter",
      stage: "filter",
      badge: "②",
      title: "圈定能打的股票",
      purpose: "只在主板里挑「第一次涨停」和「二连板冲第三板」的票，把范围缩小。",
      condition:
        "只做沪深主板股票（自动排除 ST、退市、科创板和北交所特殊标记的票）。按前一日连板情况分三类：首板（今天第一次涨停）、二进三（前两天已连板、今天冲第三板）。第四板及以上的「高板」因为盘中接力必须看到涨停价排队的逐笔委托数据（Level-2 行情），目前只观察、不正式推荐。",
      thresholds: [
        { label: "可推荐板位", value: "首板、二进三" },
        { label: "高板", value: "仅研究不推荐" },
        { label: "排除", value: "ST / 退市 / 特殊标记" },
      ],
      dataNote: "股票代码与名称、所属板块、前一日是否连板及连了几板——这些都来自信号之前就已知的日线。",
      dataGroupKeys: ["prior"],
    },
    {
      id: "radar",
      stage: "radar",
      badge: "③",
      title: "雷达盯上、临近涨停才正式评估",
      purpose: "涨幅不够的不浪费算力，离涨停一步之遥才认真考虑推荐。",
      condition:
        `股票涨幅到 ${capturePct}%，系统开始内部跟踪和预计算（雷达采集）；涨到 ${formalPct}% 才进入正式评估、出现在推荐里。不到 ${formalPct}% 的票只在后台留痕，不向用户推荐。`,
      thresholds: [
        { label: "雷达采集起点", value: `${capturePct}% 涨幅` },
        { label: "正式推荐起点", value: `${formalPct}% 涨幅` },
      ],
      dataNote: "实时涨幅、当前价、涨停价。行情数据必须新鲜：实盘快照不超过 90 秒、概念行情不超过 45 秒。",
      dataGroupKeys: ["intraday"],
    },
    {
      id: "momentum",
      stage: "momentum",
      badge: "④",
      title: "确认上涨是真金白银推上去的",
      purpose: "不仅看涨了多少，更要看涨得「实不实」，判断它能不能封住涨停。",
      condition:
        "给盘中价格承接强度打一个动能分（0–100 分），综合了最近 15 分钟的涨幅加速、触板前的冲劲、是否回封，且回撤越多扣分越狠。动能分达到及格线才算通过；同时承接分要够，认为有封住涨停的能力。",
      thresholds: [
        { label: "动能分及格线", value: "55 / 100" },
        { label: "封板承接分", value: "≥ 35" },
      ],
      dataNote: "盘中分时价格、成交量、封单变化、回封动作。来自盘中实时分钟数据。",
      dataGroupKeys: ["intraday"],
      failHint: "动能分不够或盘中承接失速，说明这波上涨可能是虚的，封板概率低，不推荐。",
    },
    {
      id: "sector",
      stage: "sector",
      badge: "⑤",
      title: "确认有板块撑腰",
      purpose: "孤掌难鸣。没有板块带动，次日容易没溢价，所以必须有一群票一起动。",
      condition:
        "满足下面任一条路径即可：①盘中同行业有 2 只以上（扫板买点要求 3 只以上）股票一起触板，且行业资金没有严重净流出；②这只票所属的概念板块「全面启动」（八成成员上涨、中位数涨幅 2.5% 以上、至少 3 只涨超 5%），并且这只票排在概念龙头前 3 名。",
      thresholds: [
        { label: "行业扩散", value: "≥ 2 只同行业触板" },
        { label: "概念启动", value: "80% 上涨 · 中位 +2.5% · 3 只涨 5%" },
        { label: "概念龙头", value: "前 3 名" },
      ],
      dataNote: "同行业触板扩散数、概念成员的涨跌分布、概念龙头排名、概念行情新鲜度。",
      dataGroupKeys: ["intraday"],
      failHint: "既没有行业扩散、也没有概念整体爆发，单兵作战的票次日大概率没溢价，不推荐。",
    },
    {
      id: "rank",
      stage: "rank",
      badge: "⑥",
      title: "同分票按历史战绩排序",
      purpose: "前面硬门都过的票全部保留，再按历史表现排个先后，优先做更靠谱的。",
      condition:
        "首板先按历史胜率从高到低排，胜率相同再看当前涨幅；二进三沿用自身的结构、质量和风险排序。历史胜率 = 过去 126 天该股触板后封住涨停的成功率 × 封住后次日收盘赚钱的概率。注意：历史统计只算「当天之前已经收盘出结果」的样本，绝不拿还没收盘的将来数据。",
      thresholds: [
        { label: "历史胜率公式", value: "126日封停率 × 次日赚钱率" },
        { label: "组合门槛", value: "≥ 5 个历史样本 · 联合胜率 ≥ 30%" },
      ],
      dataNote: "该股历史封停记录、历史次日（D+1）表现、已披露的财务与风险信息——全部是信号日之前已知的数据。",
      dataGroupKeys: ["prior"],
      failHint: "排序只决定执行先后，不会删掉已通过硬门的票；推荐列表里都会保留。",
    },
    {
      id: "fill",
      stage: "fill",
      badge: "⑦",
      title: "按到达顺序成交、次日尾盘卖",
      purpose: "把选出来的票变成真实可执行的买卖，并诚实标注成交的不确定性。",
      condition:
        `最多 ${maxPositions} 个仓位、按信号到达顺序成交，每仓约 5 万元（10 万本金对半分），按 100 股一手取整。买价取信号触发后 20–60 秒的第一条报价（模拟从看到信号到下单的真实延迟）；如果当时价格已经到涨停价、需要排队，而没有逐笔委托数据（Level-2）就无法确认是否成交，老实标成「待排队」。次日（D+1）尾盘统一按官方收盘价卖出，缺收盘价的票直接剔除不硬算。`,
      thresholds: [
        { label: "买入窗口", value: windows.join("、") },
        { label: "仓位", value: `${maxPositions} 仓 · 每仓 5 万` },
        { label: "买价延迟", value: "信号后 20–60 秒" },
        { label: "卖出", value: "次日尾盘官方收盘价" },
      ],
      dataNote: "买入窗口内的实时报价、次日官方日线收盘价。封涨停时的排队成交需要 Level-2 逐笔数据，当前没有就标「不确定成交」。",
      dataGroupKeys: ["intraday", "outcome"],
    },
  ];
}

export const DATA_GROUP_LABELS: Record<string, string> = {
  intraday: "盘中实时",
  prior: "信号前已知",
  outcome: "事后结果",
};
