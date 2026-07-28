"""Audited selection rules and dataset metadata for the limit-up desk."""

from __future__ import annotations

from alphaagent.server.services.limit_up.versions import (
    HISTORY_STRATEGY_VERSION,
    LIVE_STRATEGY_VERSION,
)
GUIDE_VERSION = "limit-up-strategy-guide-v9"


def get_limit_up_strategy_guide() -> dict[str, object]:
    """Return the reviewed point-in-time contract shown by the web desk."""

    return {
        "guide_version": GUIDE_VERSION,
        "strategy": {
            "live_version": LIVE_STRATEGY_VERSION,
            "history_version": LIVE_STRATEGY_VERSION,
            "history_dataset_version": HISTORY_STRATEGY_VERSION,
            "selection_no_lookahead": True,
            "selection_contract": LIVE_STRATEGY_VERSION,
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
            "b_first_board_minimum_time": "10:30",
            "c_tier_is_actionable": True,
            "c_daily_limit": 1,
            "c_evidence_status": "historical_proxy_pass_forward_unconfirmed",
            "priority_rule": "同一时点A优先于C、C优先于B；跨时点按真实到达顺序",
            "minimum_quality_win_probability": 0.50,
            "minimum_quality_expected_d1_net_return_pct": 0.0,
            "quality_estimate_prior_strength": 10,
            "quality_states": [
                "rejected",
                "actionable",
            ],
            "frozen_evidence": {
                "status": "historical_proxy_pass_forward_unconfirmed",
                "evidence_role": "current_v2_historical_replay",
                "source_contract": "limit-up-core-abc-v2",
                "live_equivalent": False,
                "date_start": "2025-07-10",
                "date_end": "2026-07-23",
                "closed_count": 140,
                "win_count": 97,
                "win_rate_pct": 69.2857,
                "average_net_return_pct": 2.1478,
                "max_drawdown_pct": -21.0357,
                "hard_loss_rate_pct": 7.1429,
                "a_tier": {
                    "closed_count": 41,
                    "win_count": 35,
                    "win_rate_pct": 85.3659,
                },
                "c_tier": {
                    "closed_count": 69,
                    "win_count": 44,
                    "win_rate_pct": 63.7681,
                },
                "b_tier": {
                    "closed_count": 30,
                    "win_count": 18,
                    "win_rate_pct": 60.0,
                },
                "single_position": {
                    "closed_count": 79,
                    "win_count": 55,
                    "win_rate_pct": 69.6203,
                    "total_return_pct": 376.6561,
                    "max_drawdown_pct": -19.2649,
                },
                "two_positions": {
                    "closed_count": 95,
                    "win_count": 70,
                    "win_rate_pct": 73.6842,
                    "total_return_pct": 201.9840,
                    "max_drawdown_pct": -8.6709,
                },
            },
            "forward_status": {
                "start_date": "2026-07-27",
                "closed_count": 0,
                "win_count": 0,
                "win_rate_pct": None,
                "minimum_closed_count": 15,
                "minimum_trade_days": 10,
                "status": "collecting_forward",
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
                    "历史回测和实时推荐统一使用limit-up-core-abc-v2，"
                    "任何字段缺失都按当前合同失败关闭。"
                ),
                "timing": "启动时固定合同",
            },
            {
                "order": 2,
                "title": "通过基础质量门",
                "rule": (
                    "只保留合格沪深主板的首板和二进三，并通过正确财报点时、风险、"
                    "低位结构、盘中支撑和lane结构质量。"
                ),
                "timing": "财报按披露时点，行情不晚于当前决策时点",
            },
            {
                "order": 3,
                "title": "建立A/B/C质量层",
                "rule": (
                    "A/B先要求过去126个交易日涨停2到6次并通过同股盈利门；"
                    "D-1行业成交额扩张为A，否则为B。盈利门不足但满足因果资金、"
                    "回撤或概念扩散交叉时，每日最多补一笔C。"
                ),
                "timing": "只统计信号日前已完成交易日",
            },
            {
                "order": 4,
                "title": "计算公共质量胜率与D+1预期",
                "rule": (
                    "分别用A、C、B历史层级先验，与该股票决策时点之前已有的D+1"
                    "胜率和平均净收益按10笔先验强度收缩；质量胜率低于50%或"
                    "D+1预期不为正直接淘汰。"
                ),
                "timing": "只使用决策时点之前已闭合的D+1样本",
            },
            {
                "order": 5,
                "title": "真实触板后形成正式买点",
                "rule": (
                    "开盘后持续扫描；真实首次触板或回封发生后，重新执行完整公共"
                    "A/B/C质量门。只有公共质量结论为正式可买时才进入正式买点。"
                ),
                "timing": "盘中实时",
            },
            {
                "order": 6,
                "title": "按A、C、B排序并保留A仓位",
                "rule": (
                    "全量列表输出所有通过信号；同一时点先按A、C、B，再按公共"
                    "质量胜率和D+1预期排序。正式推荐不受仓位截断；"
                    "回测两仓在尚无A时最多使用一个非A仓。C每天最多一笔，"
                    "跨时点不事后换票。"
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
            "first_board_primary": "A、C、B质量层后按公共质量胜率降序",
            "first_board_secondary": "公共D+1预期、封板率依次降序",
            "historical_win_rate_formula": (
                "个股126日封停成功率 × 同股历史首板封住后D+1收盘净赚钱率"
            ),
            "history_cutoff": "result_date < signal_date",
            "ranking_only": True,
            "portfolio_gate": (
                "公共A/B/C质量胜率不低于50%且D+1预期为正；C只覆盖三个指定"
                "排除原因并满足资金/情绪交叉，且每天最多一笔"
            ),
        },
        "field_groups": [
            {
                "key": "intraday",
                "label": "盘中实时字段",
                "selection_allowed": True,
                "fields": [
                    "当前价、涨幅、涨停价与距板",
                    "共享风险门与正式执行窗口",
                    "触板前同概念已封板数量与最高板",
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
                    "D-1市场阶段与个股前5日收益",
                ],
            },
            {
                "key": "diagnostic",
                "label": "当前仅诊断字段",
                "selection_allowed": False,
                "fields": [
                    "未冻结成员时点的概念排名与事后龙头身份",
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
    }
