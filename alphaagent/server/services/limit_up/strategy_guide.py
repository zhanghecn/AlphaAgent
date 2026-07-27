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

GUIDE_VERSION = "limit-up-strategy-guide-v4"


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
            "b_first_board_minimum_time": "10:30",
            "c_tier_is_actionable": True,
            "c_daily_limit": 1,
            "c_evidence_status": "historical_proxy_pass_forward_unconfirmed",
            "priority_rule": "同一时点A优先于C、C优先于B；跨时点按真实到达顺序",
            "frozen_evidence": {
                "status": "historical_proxy_pass_forward_unconfirmed",
                "live_equivalent": False,
                "date_start": "2025-07-10",
                "date_end": "2026-07-23",
                "closed_count": 143,
                "win_count": 99,
                "win_rate_pct": 69.2308,
                "average_net_return_pct": 2.1203,
                "max_drawdown_pct": -21.0357,
                "hard_loss_rate_pct": 6.9930,
                "a_tier": {
                    "closed_count": 41,
                    "win_count": 35,
                    "win_rate_pct": 85.3659,
                },
                "c_tier": {
                    "closed_count": 72,
                    "win_count": 46,
                    "win_rate_pct": 63.8889,
                },
                "b_tier": {
                    "closed_count": 30,
                    "win_count": 18,
                    "win_rate_pct": 60.0,
                },
                "single_position": {
                    "closed_count": 80,
                    "win_count": 57,
                    "win_rate_pct": 71.25,
                    "total_return_pct": 457.7327,
                    "max_drawdown_pct": -19.4234,
                },
                "two_positions": {
                    "closed_count": 96,
                    "win_count": 72,
                    "win_rate_pct": 75.0,
                    "total_return_pct": 226.6771,
                    "max_drawdown_pct": -8.8039,
                },
                "report": (
                    "memory/06_backtests/"
                    "limit_up_abc_formal_replay_20260727.md"
                ),
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
                    "历史回测和实时推荐统一使用limit-up-core-abc-v1，"
                    "任何字段缺失都按当前合同失败关闭。"
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
                "title": "建立A/B质量基座",
                "rule": (
                    "A/B先要求过去126个交易日涨停2到6次并通过同股盈利门；"
                    "D-1行业成交额扩张为A，否则为B。"
                ),
                "timing": "只统计信号日前已完成交易日",
            },
            {
                "order": 4,
                "title": "因果补充C层",
                "rule": (
                    "只在当日此前没有A/B且C尚未使用时，按混合期低位回撤、"
                    "行业资金覆盖或触板前细分概念2到4只先行封板三类交叉补一笔C。"
                ),
                "timing": "D-1字段加当前触板前已发生事件",
            },
            {
                "order": 5,
                "title": "等待正式盘中触发",
                "rule": (
                    "A/C首板和二进三从10:00起行动；B首板只接受10:30后首次触板"
                    "或10:30后回封。二进三9:35到10:00只观察，10:00后才行动。"
                ),
                "timing": "盘中实时",
            },
            {
                "order": 6,
                "title": "按A、C、B排序并保留A仓位",
                "rule": (
                    "全量列表输出所有通过信号；同一时点按A、C、B排序。两仓在"
                    "尚无A时最多使用一个非A仓，C每天最多一笔，跨时点不事后换票。"
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
                "A/B首板要求至少5个前序D+1样本且联合率不低于30%；"
                "C只覆盖三个指定排除原因并满足资金/情绪交叉，且每天最多一笔"
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
                "正式合同仅为limit-up-core-abc-v1；板前概率当前只作研究观察，"
                "不生成买点"
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
