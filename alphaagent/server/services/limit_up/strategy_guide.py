"""Audited selection rules and dataset metadata for the limit-up desk."""

from __future__ import annotations

from alphaagent.server.services.limit_up.versions import (
    HISTORY_STRATEGY_VERSION,
    LIVE_STRATEGY_VERSION,
)

GUIDE_VERSION = "limit-up-strategy-guide-v1"


def get_limit_up_strategy_guide() -> dict[str, object]:
    """Return the reviewed point-in-time contract shown by the web desk."""

    return {
        "guide_version": GUIDE_VERSION,
        "strategy": {
            "live_version": LIVE_STRATEGY_VERSION,
            "history_version": HISTORY_STRATEGY_VERSION,
            "selection_no_lookahead": True,
            "selection_contract": "first_eligible_saved_snapshot",
            "entry_windows": ["10:00-11:30", "13:00-14:30"],
            "entry_mode": "sweep",
            "exit_mode": "next_close",
            "max_positions": 2,
        },
        "verdict": {
            "title": "选股阶段没有使用未来数据",
            "detail": (
                "每只股票只取按 captured_at 排序后第一次通过规则的保存快照；"
                "D 日最终封板和 D+1 收盘只在选股完成后用于结算。"
            ),
            "execution_boundary": (
                "没有 Tick/L2 排队成交回报，扫板成交仍是计入滑点的价格代理，"
                "不能解释为每笔委托一定成交。"
            ),
        },
        "selection_steps": [
            {
                "order": 1,
                "title": "限定可交易范围",
                "rule": "仅主板首板和二进三进入正式推荐；高板只研究。",
                "timing": "盘中已知",
            },
            {
                "order": 2,
                "title": "检查市场与数据质量",
                "rule": "快照必须新鲜、处于买入窗口，且市场风险门允许执行。",
                "timing": "盘中实时",
            },
            {
                "order": 3,
                "title": "确认首板动能",
                "rule": (
                    "股票进入 5% 雷达后，点时承接与动能分至少 55；"
                    "未封板、已封板和回封状态使用同一套质量检查。"
                ),
                "timing": "盘中实时",
            },
            {
                "order": 4,
                "title": "确认板块路径",
                "rule": (
                    "盘中行业扩散达标，或实时概念达到 launch、至少 2 只涨超 5%"
                    "且该股位列概念前 3；任一路径成立即可。"
                ),
                "timing": "盘中实时",
            },
            {
                "order": 5,
                "title": "形成正式推荐并排序",
                "rule": (
                    "通过硬门的股票全部保留。首板先按历史胜率降序，再按当前涨幅降序；"
                    "二进三沿用自身结构、质量和风险排序。"
                ),
                "timing": "仅使用当时及此前数据",
            },
            {
                "order": 6,
                "title": "首次信号成交与事后结算",
                "rule": (
                    "同股同日只取第一次正式出现的快照，最多两仓按真实到达顺序；"
                    "D+1 以官方收盘价结算，缺价直接剔除。"
                ),
                "timing": "先选股，后结算",
            },
        ],
        "ranking": {
            "first_board_primary": "历史胜率降序",
            "first_board_secondary": "当前涨幅降序",
            "historical_win_rate_formula": (
                "个股126日封停成功率 × 同股历史首板封住后D+1收盘净赚钱率"
            ),
            "history_cutoff": "result_date < signal_date",
            "ranking_only": True,
            "portfolio_gate": "两仓组合仍要求至少5个前序D+1样本且联合率不低于30%",
        },
        "field_groups": [
            {
                "key": "intraday",
                "label": "盘中实时字段",
                "selection_allowed": True,
                "fields": [
                    "captured_at 与快照新鲜度",
                    "当前价、涨幅、涨停价与盘口状态",
                    "承接/动能分、封板或回封状态",
                    "行业触板扩散与当日资金状态",
                    "概念 launch、涨超5%数量、概念Top3排名",
                    "市场阶段与风险门",
                ],
            },
            {
                "key": "prior",
                "label": "信号前已知字段",
                "selection_allowed": True,
                "fields": [
                    "D-1及更早官方日线",
                    "D-1行业热度（只诊断和排序）",
                    "信号日前已经闭合的封停成功率",
                    "信号日前已经闭合的D+1收盘赚钱率",
                    "当时已经披露的财务与风险信息",
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
            "name": "800日历史候选代理",
            "kind": "historical_candidate_proxy",
            "tables": ["limit_up_history_replays", "stock_daily_bars"],
            "date_start": "2023-03-28",
            "date_end": "2026-07-16",
            "trade_day_count": 800,
            "qualified_signal_count": 168,
            "closed_recommendation_count": 164,
            "account_trade_count": 97,
            "recommendation_win_rate_pct": 62.1951,
            "account_win_rate_pct": 70.1031,
            "live_equivalent": False,
            "purpose": "长期检验候选结构、时间窗口、费用、仓位和D+1收盘退出",
            "limitation": (
                "缺少历史盘中全市场、板块资金和Tick/L2帧，不能冒充v15实时规则的"
                "实盘等价收益；页面长期胜率与643帧v15结果不得混算。"
            ),
        },
    }
