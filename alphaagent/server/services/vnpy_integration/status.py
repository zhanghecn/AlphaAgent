"""vn.py readiness inspection for AlphaAgent.

This module intentionally reports what is installed and wired today.  It does
not claim A-share trading support unless the relevant vn.py plugin is present.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Any

from alphaagent.server.services.data_sync import coverage


@dataclass(frozen=True)
class PluginSpec:
    module: str
    name: str
    category: str
    purpose: str
    required_for_a_share: bool = False


PLUGIN_SPECS: tuple[PluginSpec, ...] = (
    PluginSpec("vnpy", "vn.py core", "core", "事件引擎、主引擎、对象模型"),
    PluginSpec("vnpy_ctp", "CTP Gateway", "gateway", "期货/期权交易接口"),
    PluginSpec("vnpy_ctastrategy", "CTA Strategy", "app", "单标的 CTA 策略"),
    PluginSpec("vnpy_ctabacktester", "CTA Backtester", "app", "CTA 回测"),
    PluginSpec("vnpy_datamanager", "DataManager", "app", "历史数据管理"),
    PluginSpec("vnpy_sqlite", "SQLite Database", "database", "vn.py 本地数据库"),
    PluginSpec("vnpy_xt", "XT Datafeed/Gateway", "a_share_datafeed", "A 股行情/历史/财务数据", True),
    PluginSpec("vnpy_rqdata", "RQData Datafeed", "a_share_datafeed", "A 股历史行情数据", True),
    PluginSpec("vnpy_tushare", "TuShare Datafeed", "a_share_datafeed", "A 股历史/财务数据", True),
    PluginSpec("vnpy_xtp", "XTP Gateway", "a_share_gateway", "A 股券商交易接口", True),
    PluginSpec("vnpy_tora", "TORA Gateway", "a_share_gateway", "A 股券商交易接口", True),
    PluginSpec("vnpy_ost", "OST Gateway", "a_share_gateway", "A 股券商交易接口", True),
    PluginSpec("vnpy_emt", "EMT Gateway", "a_share_gateway", "A 股券商交易接口", True),
    PluginSpec("vnpy_scripttrader", "ScriptTrader", "app", "多标的脚本交易/扫描"),
    PluginSpec("vnpy_portfoliostrategy", "PortfolioStrategy", "app", "组合策略"),
    PluginSpec("vnpy_datarecorder", "DataRecorder", "app", "实时数据记录"),
)


def vnpy_status() -> dict[str, Any]:
    plugins = [_plugin_status(item) for item in PLUGIN_SPECS]
    installed = {item["module"] for item in plugins if item["installed"]}
    missing_required = [
        item
        for item in plugins
        if item["required_for_a_share"] and not item["installed"]
    ]
    local_coverage = coverage()
    tables = local_coverage.get("tables", {})
    daily_bars = tables.get("stock_daily_bars", {})
    minute_bars = tables.get("stock_minute_bars", {})
    stocks = tables.get("stocks", {})

    a_share_gateway_ready = any(module in installed for module in {"vnpy_xtp", "vnpy_tora", "vnpy_ost", "vnpy_emt"})
    a_share_datafeed_ready = any(module in installed for module in {"vnpy_xt", "vnpy_rqdata", "vnpy_tushare"})

    return {
        "status": "ready" if a_share_gateway_ready and a_share_datafeed_ready else "partial",
        "product": "AlphaAgent",
        "vnpy_package_name": "vnpy",
        "launcher": {
            "path": "examples/veighna_trader/run.py",
            "registered_gateways": ["CtpGateway"],
            "registered_apps": ["CtaStrategyApp", "CtaBacktesterApp", "DataManagerApp"],
            "a_share_gateway_registered": False,
        },
        "plugins": plugins,
        "missing_required_for_a_share": missing_required,
        "capabilities": {
            "alphaagent_local_daily_backtest": bool((daily_bars.get("count") or 0) > 0),
            "alphaagent_local_vnpy_bar_adapter": bool((daily_bars.get("count") or 0) > 0),
            "alphaagent_local_minute_tail_entry": bool((minute_bars.get("count") or 0) > 0),
            "alphaagent_stock_universe": bool((stocks.get("count") or 0) > 0),
            "vnpy_a_share_datafeed": a_share_datafeed_ready,
            "vnpy_a_share_gateway": a_share_gateway_ready,
            "vnpy_official_cta_backtester": "vnpy_ctabacktester" in installed,
            "vnpy_data_manager": "vnpy_datamanager" in installed,
            "vnpy_portfolio_strategy": "vnpy_portfoliostrategy" in installed,
            "vnpy_script_trader": "vnpy_scripttrader" in installed,
        },
        "notes": [
            "AlphaAgent 当前回测使用 PostgreSQL 日线数据和自研组合回测服务。",
            "AlphaAgent 可通过 /api/vnpy/local-bars 把本地日线转换为 vn.py BarData 语义，供本地研究/适配使用。",
            "stock_minute_bars 有数据时，AlphaAgent 回测可对尾盘 5 日线附近低吸做分钟级入场验证。",
            "vn.py GUI 当前只注册 CTP Gateway，不能直接连接 A 股券商。",
            "接入 A 股实盘前需要安装并配置 vnpy_xtp/vnpy_tora/vnpy_ost/vnpy_emt 之一。",
            "接入 vn.py 官方历史数据路径前需要安装并配置 vnpy_xt/vnpy_rqdata/vnpy_tushare 之一。",
        ],
        "integration_plan": [
            "安装并验证 A 股数据插件：优先 vnpy_xt 或 vnpy_rqdata；只做盘后历史可选 vnpy_tushare。",
            "在 vn.py 全局配置中设置 datafeed.name、datafeed.username、datafeed.password。",
            "安装并验证 A 股交易网关：vnpy_xtp/vnpy_tora/vnpy_ost/vnpy_emt 四选一。",
            "在 examples/veighna_trader/run.py 注册对应 Gateway，并用 Trader 查询合约确认全 A 合约可见。",
            "把 AlphaAgent 选股结果导出为 vn.py ScriptTrader/PortfolioStrategy 可消费的候选池。",
            "把本地 BarData 适配层接入后续 vn.py 策略初始化和数据检查流程；该步骤不替代官方 Datafeed/Gateway。",
        ],
    }


def _plugin_status(spec: PluginSpec) -> dict[str, Any]:
    installed = importlib.util.find_spec(spec.module) is not None
    return {
        "module": spec.module,
        "name": spec.name,
        "category": spec.category,
        "purpose": spec.purpose,
        "installed": installed,
        "required_for_a_share": spec.required_for_a_share,
    }
