"""Audited selection rules and dataset metadata for the limit-up desk."""

from __future__ import annotations

from alphaagent.server.services.limit_up.versions import (
    HISTORY_STRATEGY_VERSION,
    LIVE_STRATEGY_VERSION,
)
from alphaagent.server.services.limit_up.radar_contract import CAPTURE_MIN_CHANGE_PCT
from alphaagent.server.services.limit_up.preboard_decision_contract import (
    PREBOARD_DECISION_VERSION,
)

GUIDE_VERSION = "limit-up-strategy-guide-v2"


def get_limit_up_strategy_guide() -> dict[str, object]:
    """Return the reviewed point-in-time contract shown by the web desk."""

    return {
        "guide_version": GUIDE_VERSION,
        "strategy": {
            "live_version": LIVE_STRATEGY_VERSION,
            "history_version": HISTORY_STRATEGY_VERSION,
            "selection_no_lookahead": True,
            "selection_contract": LIVE_STRATEGY_VERSION,
            "preboard_research_contract": PREBOARD_DECISION_VERSION,
            "entry_windows": ["10:00-11:30", "13:00-14:30"],
            "entry_mode": "sweep",
            "exit_mode": "next_close",
            "max_positions": 2,
            "live_actionable_limit": None,
        },
        "verdict": {
            "title": "选股阶段没有使用未来数据",
            "detail": (
                "每个决策时点只冻结当时已经完成的分钟、逐笔前缀和历史先验；"
                "D日最终触板、封板和D+1收盘只在特征冻结后用于标签或结算。"
            ),
            "execution_boundary": (
                "没有逐笔委托与涨停价排队成交回报，正式扫板仍是计入滑点的价格代理，"
                "不能解释为每笔委托一定成交。"
            ),
        },
        "selection_steps": [
            {
                "order": 1,
                "title": "形成高质量首板母池",
                "rule": (
                    "先复用正式同源主板、首板、风险、lane质量和prior-only盈利门；"
                    "普通上涨股票不进入个股模型。"
                ),
                "timing": "D-1历史与盘中点时信息",
            },
            {
                "order": 2,
                "title": "达到3%后启动观察",
                "rule": (
                    "只有高质量首板涨幅达到3%且现价严格低于涨停价才进入观察池；"
                    "3%、5%、8%、9%和9.5%都不是固定买点。"
                ),
                "timing": "盘中实时",
            },
            {
                "order": 3,
                "title": "冻结同源点时特征",
                "rule": (
                    "只使用已完成分钟、截至当前的逐笔资金代理、质量池横截面和"
                    "信号日前已闭合的历史先验。"
                ),
                "timing": "每项数据的可知时间不晚于当前决策时点",
            },
            {
                "order": 4,
                "title": "计算双触板概率",
                "rule": (
                    "共享模型输出未来3个交易分钟内触板概率和当日执行窗口内最终"
                    "触板概率；双概率同时有效后才公开排序，概率不可用时只保留"
                    "内部审计样本。"
                ),
                "timing": "每个新快照重新评分",
            },
            {
                "order": 5,
                "title": "隔离暂不可同源的诊断因子",
                "rule": (
                    "盘中板块、概念、资金、当前换手和新鲜度继续采集，但当前历史不能"
                    "按同一可知时点复现，因此不得成为实时专属硬门。"
                ),
                "timing": "当前仅作诊断",
            },
            {
                "order": 6,
                "title": "按D+1价值和触板概率排序",
                "rule": (
                    "先按同股D+1预期净收益和胜率，再按3分钟触板、最终触板、"
                    "触板后封板率和首板承接分排序；误报占仓，后来股票不得替换。"
                ),
                "timing": "历史先验只用result_date早于signal_date的样本",
            },
            {
                "order": 7,
                "title": "严格板前成交与双门晋级",
                "rule": (
                    "回放只认行动后的第一条严格低于涨停价的新报价；历史账户通过后"
                    "仅进入影子，独立前向账户再次通过后才补充正式板前买点。无论是否"
                    "晋级，正式v15封板和回封扫板买点保持且不被板前层删除。"
                ),
                "timing": "先冻结决策，后连接触板、封板和D+1结算",
            },
        ],
        "ranking": {
            "first_board_primary": "同股D+1预期净收益降序",
            "first_board_secondary": "D+1胜率、3分钟/最终触板概率、封板率依次降序",
            "historical_win_rate_formula": (
                "个股126日封停成功率 × 同股历史首板封住后D+1收盘净赚钱率"
            ),
            "history_cutoff": "result_date < signal_date",
            "ranking_only": True,
            "portfolio_gate": (
                "全量正式首板仍要求至少5个前序D+1样本且联合率不低于30%；"
                "两仓只限制资金占用，不放宽或收紧这道质量门"
            ),
        },
        "preboard_decision": {
            "decision_version": PREBOARD_DECISION_VERSION,
            "observation_min_change_pct": CAPTURE_MIN_CHANGE_PCT,
            "observation_is_buy_signal": False,
            "quality_pool_rule": "先通过正式同源首板质量门，再由涨幅达到3%激活观察",
            "probability_outputs": ["3分钟触板概率", "当日最终触板概率"],
            "ranking_order": [
                "同股D+1预期净收益",
                "同股D+1胜率",
                "3分钟触板概率",
                "最终触板概率",
                "触板后封板率",
                "首板承接分",
            ],
            "promotion_rule": (
                "历史严格板前账户通过后仅进入影子；独立前向账户再次通过后，"
                "才补充正式板前买点和概率排序，且不删除同股当前扫板兜底"
            ),
            "formal_baseline": (
                "当前limit-up-live-v15仍按历史联合胜率、当前涨幅和承接证据排序；"
                "封板/回封扫板买点保持不变，未来板前层只能补充"
            ),
        },
        "field_groups": [
            {
                "key": "intraday",
                "label": "盘中实时字段",
                "selection_allowed": True,
                "fields": [
                    "当前决策时点与严格板前价格",
                    "当前价、涨幅、涨停价与距板",
                    "已完成分钟的速度、加速度、量能和回撤恢复",
                    "截至当前决策时点的逐笔资金代理",
                    "高质量母池的点时横截面",
                    "共享风险门与正式执行窗口",
                ],
            },
            {
                "key": "prior",
                "label": "信号前已知字段",
                "selection_allowed": True,
                "fields": [
                    "D-1及更早官方日线",
                    "信号日前已经闭合的封停成功率",
                    "信号日前已经闭合的同股D+1预期净收益与赚钱率",
                    "当时已经披露的财务与风险信息",
                ],
            },
            {
                "key": "diagnostic",
                "label": "当前仅诊断字段",
                "selection_allowed": False,
                "fields": [
                    "盘中板块扩散、概念启动与龙头排名",
                    "板块资金、个股资金与当前换手",
                    "市场状态、快照新鲜度与报价新鲜度",
                ],
            },
            {
                "key": "outcome",
                "label": "事后结果字段",
                "selection_allowed": False,
                "fields": [
                    "D日最终是否封住",
                    "D+1官方收盘价",
                    "扣除费用和滑点后的净收益",
                    "后续快照和最终排名",
                ],
            },
        ],
        "dataset": {
            "name": "v15保存快照点时反事实重放",
            "kind": "saved_point_in_time_counterfactual_replay",
            "table": "limit_up_signal_snapshots",
            "date_start": "2026-07-15",
            "date_end": "2026-07-17",
            "snapshot_count": 643,
            "daily_snapshot_counts": [
                {"trade_date": "2026-07-15", "snapshot_count": 253},
                {"trade_date": "2026-07-16", "snapshot_count": 253},
                {"trade_date": "2026-07-17", "snapshot_count": 137},
            ],
            "closed_through": "2026-07-15",
            "closed_signal_count": 11,
            "win_count": 7,
            "win_rate_pct": 63.6364,
            "average_net_return_pct": 2.9050,
            "portfolio_trade_count": 2,
            "portfolio_win_count": 2,
            "portfolio_return_pct": 5.7892,
            "portfolio_max_drawdown_pct": -0.0309,
            "entry": "第一次规则通过的保存快照，盘中 sweep 价格代理",
            "exit": "D+1官方日线close_price",
            "costs": "双边各10bp滑点、万三佣金、最低5元、万0.1过户、卖出万五印花税",
            "report": "memory/06_backtests/limit_up_sector_quality_v15_20260717.md",
            "limitations": [
                "只有2026-07-15具备D+1官方收盘，7月16日和17日不拿盘中价替代。",
                "643帧用于在相同点时输入上重放v15规则，不是643笔交易。",
                "该小样本验证v15相对v14的板块门修复，不替代冻结后的长期前向观察。",
            ],
        },
        "historical_reference": {
            "name": "806日历史候选代理（截至2026-07-24）",
            "kind": "historical_candidate_proxy",
            "tables": ["limit_up_history_replays", "stock_daily_bars"],
            "date_start": "2023-03-28",
            "date_end": "2026-07-24",
            "trade_day_count": 806,
            "qualified_signal_count": 243,
            "closed_recommendation_count": 239,
            "account_trade_count": 127,
            "recommendation_win_rate_pct": 54.8117,
            "account_win_rate_pct": 58.2677,
            "live_equivalent": False,
            "purpose": "长期检验候选结构、时间窗口、费用、仓位和D+1收盘退出",
            "limitation": (
                "缺少历史盘中全市场、板块资金和逐笔排队帧，不能冒充v15实时规则的"
                "实盘等价收益；财报修复前约62%的旧结果已经失效，且页面长期胜率与"
                "643帧v15结果不得混算。"
            ),
        },
    }
