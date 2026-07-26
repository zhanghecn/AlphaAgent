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

GUIDE_VERSION = "limit-up-strategy-guide-v3"


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
        "core_quality": {
            "contract_version": LIVE_STRATEGY_VERSION,
            "prior_limit_window_days": 126,
            "minimum_prior_limit_count": 2,
            "maximum_prior_limit_count": 6,
            "a_tier_industry_turnover_ratio_5d": 1.0,
            "b_tier_is_actionable": True,
            "priority_rule": "A优先，B保留；行业量能不作为剔除B的硬门",
            "frozen_evidence": {
                "status": "historical_pass_forward_not_passed",
                "live_equivalent": False,
                "date_start": "2025-07-10",
                "date_end": "2026-07-23",
                "closed_count": 78,
                "win_count": 56,
                "win_rate_pct": 71.7949,
                "average_net_return_pct": 2.2512,
                "max_drawdown_pct": -14.5416,
                "hard_loss_rate_pct": 8.9744,
                "a_tier": {
                    "closed_count": 41,
                    "win_count": 35,
                    "win_rate_pct": 85.3659,
                },
                "b_tier": {
                    "closed_count": 37,
                    "win_count": 21,
                    "win_rate_pct": 56.7568,
                },
                "report": (
                    "memory/06_backtests/"
                    "limit_up_quality_reconstruction_20260726.md"
                ),
            },
            "recent_snapshot_check": {
                "date_start": "2026-07-20",
                "date_end": "2026-07-24",
                "closed_count": 24,
                "win_count": 12,
                "win_rate_pct": 50.0,
                "average_net_return_pct": -0.2351,
                "no_action_date": "2026-07-24",
                "entry": "旧保存快照的首次正式报价代理",
                "live_equivalent": False,
                "status": "below_60_requires_natural_forward",
            },
        },
        "verdict": {
            "title": "选股阶段没有使用未来数据",
            "detail": (
                "每个决策时点只使用当时已披露财报、D-1及更早日线、已完成的"
                "盘中证据和历史先验；D日最终封板与D+1收盘只用于事后结算。"
            ),
            "execution_boundary": (
                "没有逐笔委托与涨停价排队成交回报，正式扫板仍是计入滑点的价格代理，"
                "不能解释为每笔委托一定成交。"
            ),
        },
        "selection_steps": [
            {
                "order": 1,
                "title": "锁定唯一正式合同",
                "rule": (
                    "历史回测和实时推荐统一使用limit-up-core-ab-v1；旧v15只保留"
                    "只读审计，不参与准入、排序或回退。"
                ),
                "timing": "启动时固定合同",
            },
            {
                "order": 2,
                "title": "通过基础质量门",
                "rule": (
                    "只保留合格沪深主板的首板和二进三，并通过正确财报点时、风险、"
                    "低位结构、盘中支撑、lane质量和同股盈利门。"
                ),
                "timing": "财报按披露时点，行情不晚于当前决策时点",
            },
            {
                "order": 3,
                "title": "限制历史辨识度",
                "rule": (
                    "过去126个交易日涨停次数必须在2到6次之间；少于2次说明缺少"
                    "市场辨识度，超过6次视为可能已过度炒作。"
                ),
                "timing": "只统计信号日前已完成交易日",
            },
            {
                "order": 4,
                "title": "动态划分A/B优先级",
                "rule": (
                    "D-1所属行业成交额不低于此前5日基准为A；未扩张或数据不可用"
                    "为B。A优先，B仍可交易，行业名称和概念名称不写死。"
                ),
                "timing": "只使用D-1及更早行业数据",
            },
            {
                "order": 5,
                "title": "等待正式盘中触发",
                "rule": (
                    "仅在固定买入窗口、快照新鲜且原盘中支撑和触发状态全部通过时"
                    "形成正式买点；3%板前观察和概率研究不属于正式合同。"
                ),
                "timing": "盘中实时",
            },
            {
                "order": 6,
                "title": "输出全部A+B买点",
                "rule": (
                    "所有通过硬门的信号都进入正式买点列表，不限制为每天一笔；"
                    "同一交易日可以有多笔，A排在B之前。"
                ),
                "timing": "每个有效快照重新计算",
            },
            {
                "order": 7,
                "title": "按统一价格和费用结算",
                "rule": (
                    "买入使用正式触发价格代理并计滑点和费用；D+1按官方日线收盘价"
                    "卖出。缺少真实涨停价排队回报时，不把价格代理解释为必然成交。"
                ),
                "timing": "先冻结买点，后连接D+1结果",
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
                "全量正式首板要求至少5个前序D+1样本且联合率不低于30%；"
                "二进三沿用原lane质量门，全部信号再统一通过126日2到6次硬门"
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
                "正式合同仅为limit-up-core-ab-v1；板前概率当前只作研究观察，"
                "不生成买点，也不作为旧规则回退入口"
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
                    "过去126个交易日涨停次数",
                    "D-1行业成交额相对此前5日基准",
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
            "name": "旧v15保存快照（只读审计）",
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
                "643帧是旧v15历史审计数据，不是643笔交易。",
                "旧快照不参与limit-up-core-ab-v1准入、排序或回退。",
            ],
        },
        "historical_reference": {
            "name": "财报修复后旧母池对照（只读审计）",
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
                "这些数字是A+B启用前的旧母池，只用于解释财报修复后的质量下降；"
                "不能作为当前合同结果，也不能触发旧规则回退。"
            ),
        },
    }
