"""一接二 j12-v2.0 综合最终版：十条规则、统一判定与研究文案。"""
from __future__ import annotations

import math
from collections.abc import Mapping

J12_RULES_VERSION = "j12-v2.0"

# gate = [lo, hi) 今开窗，单位 %；仅 F3/F6/F9 有竞价窗。
POINTS: dict[str, dict[str, object]] = {
    "F1": {
        "name": "五日深跌·地基实体跌3~5",
        "level": "A",
        "actionable": True,
        "desc": "首板前5日涨幅 < -15% × 地基实体涨幅 ∈ [-5%,-3%)",
        "gate": None,
        "hint": "前五日跌超15%，地基实体跌3~5%",
    },
    "F2": {
        "name": "地基巨震·首板换手3~5",
        "level": "A",
        "actionable": True,
        "desc": "首板换手率 ∈ [3%,5%) × 地基振幅 ≥ 12%",
        "gate": None,
        "hint": "首板换手3~5%，地基振幅至少12%",
    },
    "F3": {
        "name": "阴地基站线·二板开7.5~8.5",
        "level": "A",
        "actionable": True,
        "desc": "今开 ∈ [7.5%,8.5%) × 阴地基 × 地基姿态为站线上",
        "gate": (7.5, 8.5),
        "hint": "阴地基站线上，今开7.5~8.5%",
    },
    "F4": {
        "name": "全空头大阴·首板开口8~12",
        "level": "A",
        "actionable": True,
        "desc": "均线状态为--- × 地基实体涨幅 < -5% × 首板开口 ∈ [8%,12%)",
        "gate": None,
        "hint": "全空头配地基大阴，首板开口8~12%",
    },
    "F5": {
        "name": "阴地基强开·前20日涨30以上",
        "level": "A",
        "actionable": True,
        "desc": "阴地基 × 首板开口 ∈ [5%,8%) × 首板前20日涨幅 ≥ 30%",
        "gate": None,
        "hint": "阴地基且前20日涨超30%，首板开口5~8%",
    },
    "F6": {
        "name": "二板高开·首板低开未破60高",
        "level": "A",
        "actionable": True,
        "desc": "今开 ∈ [8.5%,9.5%) × 首板低开 × 首板未突破60日高",
        "gate": (8.5, 9.5),
        "hint": "首板低开且未破60日高，今开8.5~9.5%",
    },
    "F7": {
        "name": "地基大阴放量·首板换手微增",
        "level": "A",
        "actionable": True,
        "desc": "地基实体涨幅 < -5% × 地量相对5日 ∈ [1.2,1.5) × 首板换手变化 ∈ [0,2)",
        "gate": None,
        "hint": "地基大阴温和放量，首板换手增加不足2个点",
    },
    "F8": {
        "name": "急跌缩量·首板换手5~8",
        "level": "A",
        "actionable": True,
        "desc": "首板换手 ∈ [5%,8%) × 首板量相对5日 ∈ [0.5,0.8) × 前三日涨幅 ∈ [-15%,-8%)",
        "gate": None,
        "hint": "前三日急跌，首板换手5~8%且缩量",
    },
    "F9": {
        "name": "全空头高开·首板换手微增",
        "level": "A",
        "actionable": True,
        "desc": "均线状态为--- × 今开 ∈ [7.5%,8.5%) × 首板换手变化 ∈ [0,2)",
        "gate": (7.5, 8.5),
        "hint": "全空头且首板换手微增，今开7.5~8.5%",
    },
    "F10": {
        "name": "近60日高·阳地基·前三日走强",
        "level": "A",
        "actionable": True,
        "desc": "距60日高 ∈ [-10%,-8%) × 地基实体涨幅 ∈ [5%,7%) × 前三日涨幅 ∈ [5%,10%)",
        "gate": None,
        "hint": "距60日高8~10%，地基中阳且前三日走强",
    },
}


def _number(fields: Mapping[str, object], key: str) -> float | None:
    """缺字段、非数值、NaN 和无穷大都视为不满足数值条件。"""
    value = fields.get(key)
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _equals(fields: Mapping[str, object], key: str, expected: object) -> bool:
    value = fields.get(key)
    if value is None:
        return False
    try:
        return bool(value == expected)
    except (TypeError, ValueError):
        return False


def _between(value: float | None, low: float, high: float) -> bool:
    return value is not None and low <= value < high


def _lt(value: float | None, high: float) -> bool:
    return value is not None and value < high


def _ge(value: float | None, low: float) -> bool:
    return value is not None and value >= low


def match_points(fields: Mapping[str, object], check_gate: bool = True) -> list[str]:
    """按 F1~F10 顺序返回全部命中规则。

    默认复核今开窗；T-1 盘后传 check_gate=False 时，只跳过 F3/F6/F9
    的今开窗，其余条件仍逐项检查，缺字段或 NaN 不会放行。
    """
    n = lambda key: _number(fields, key)
    hits: list[str] = []

    if _lt(n("pre5_pct"), -15) and _between(n("foundation_body"), -5, -3):
        hits.append("F1")
    if _between(n("b1_turn"), 3, 5) and _ge(n("foundation_amplitude"), 12):
        hits.append("F2")
    if (
        (not check_gate or _between(n("today_open"), 7.5, 8.5))
        and _equals(fields, "foundation_yang", False)
        and _equals(fields, "foundation_pose", "站线上")
    ):
        hits.append("F3")
    if (
        _equals(fields, "ma_state", "---")
        and _lt(n("foundation_body"), -5)
        and _between(n("b1_gap"), 8, 12)
    ):
        hits.append("F4")
    if (
        _equals(fields, "foundation_yang", False)
        and _between(n("b1_gap"), 5, 8)
        and _ge(n("pre20_pct"), 30)
    ):
        hits.append("F5")
    if (
        (not check_gate or _between(n("today_open"), 8.5, 9.5))
        and _lt(n("b1_open"), 0)
        and _equals(fields, "b1_break60", False)
    ):
        hits.append("F6")
    if (
        _lt(n("foundation_body"), -5)
        and _between(n("foundation_vol_rel5"), 1.2, 1.5)
        and _between(n("b1_turn_change"), 0, 2)
    ):
        hits.append("F7")
    if (
        _between(n("b1_turn"), 5, 8)
        and _between(n("b1_vol_rel5"), 0.5, 0.8)
        and _between(n("pre3_pct"), -15, -8)
    ):
        hits.append("F8")
    if (
        _equals(fields, "ma_state", "---")
        and (not check_gate or _between(n("today_open"), 7.5, 8.5))
        and _between(n("b1_turn_change"), 0, 2)
    ):
        hits.append("F9")
    if (
        _between(n("dist_h60"), -10, -8)
        and _between(n("foundation_body"), 5, 7)
        and _between(n("pre3_pct"), 5, 10)
    ):
        hits.append("F10")
    return hits


# 单规则统计来自 汇总/open9_综合最终规则.csv 的 all_* 列；合计为同票同日去重账本。
CHEAT_ROWS: list[dict[str, str]] = [
    {"口诀": "F1 五日深跌·地基实体跌3~5", "条件": "前5日<-15%×地基实体[-5%,-3%)", "级别": "出手",
     "六年": "92笔 胜68.48% 均值+3.13 trim3+2.12"},
    {"口诀": "F2 地基巨震·首板换手3~5", "条件": "首板换手[3%,5%)×地基振幅≥12%", "级别": "出手",
     "六年": "61笔 胜60.66% 均值+4.63 trim3+1.76"},
    {"口诀": "F3 阴地基站线·二板开7.5~8.5", "条件": "今开[7.5%,8.5%)×阴地基×站线上", "级别": "出手",
     "六年": "106笔 胜62.26% 均值+4.78 trim3+3.19"},
    {"口诀": "F4 全空头大阴·首板开口8~12", "条件": "均线---×地基实体<-5%×首板开口[8%,12%)", "级别": "出手",
     "六年": "94笔 胜71.28% 均值+3.76 trim3+2.45"},
    {"口诀": "F5 阴地基强开·前20日涨30以上", "条件": "阴地基×首板开口[5%,8%)×前20日≥30%", "级别": "出手",
     "六年": "82笔 胜62.20% 均值+3.29 trim3+1.26"},
    {"口诀": "F6 二板高开·首板低开未破60高", "条件": "今开[8.5%,9.5%)×首板低开×未破60日高", "级别": "出手",
     "六年": "70笔 胜61.43% 均值+7.10 trim3+3.43"},
    {"口诀": "F7 地基大阴放量·首板换手微增", "条件": "地基实体<-5%×地量/5日[1.2,1.5)×换手变化[0,2)", "级别": "出手",
     "六年": "65笔 胜67.69% 均值+4.49 trim3+2.38"},
    {"口诀": "F8 急跌缩量·首板换手5~8", "条件": "首板换手[5%,8%)×首板量/5日[0.5,0.8)×前3日[-15%,-8%)", "级别": "出手",
     "六年": "39笔 胜66.67% 均值+9.94 trim3+4.59"},
    {"口诀": "F9 全空头高开·首板换手微增", "条件": "均线---×今开[7.5%,8.5%)×首板换手变化[0,2)", "级别": "出手",
     "六年": "24笔 胜62.50% 均值+8.55 trim3+3.68"},
    {"口诀": "F10 近60日高·阳地基·前三日走强", "条件": "距60日高[-10%,-8%)×地基实体[5%,7%)×前3日[5%,10%)", "级别": "出手",
     "六年": "23笔 胜65.22% 均值+7.43 trim3+2.55"},
    {"口诀": "合计 综合最终版（同票同日去重）", "条件": "F1~F10任一命中，同票同日只算一笔", "级别": "综合",
     "六年": "624笔 胜64.10% 均值+4.93 trim3+4.31"},
]

RULES_TEXT = {
    "koujue": "孤立首板次日，十条综合条件任一命中；开盘不顶涨停，盘中严格过九个点才接。",
    "entry": "昨日孤立首板，二板日开盘非涨停；日线最高严格突破+9%即买，开盘已高于触发价按开盘价，否则按触发价成交。",
    "mechanism": "十条规则从地基、首板和二板竞价形态综合筛选，命中任一即进入同一账本；按年度展示等权逐笔收益与trim3，检验不同年份的收益表现。",
    "sell": "买入日未封住，次一交易日尾盘卖出；封住则持有至首次断板日尾盘；卖出日一字跌停无法成交则顺延；最长持有15个交易日，到期尾盘卖出。",
    "position": "十条规则命中任一才出手；同一股票同一交易日只算一笔，多规则命中不重复计算。",
    "avoid": [],
    "honest": "2021~2022回放171笔，胜率60.23%，均值+4.41%，trim3+3.37%；2021~2026各年trim3均为正；2026年统计截至10月23日。历史结果不构成收益保证。",
}

MAIN_WINDOW = {
    "start": "2023-01",
    "end": "2026-10-23",
    "note": "主窗2023-01起；2021-01~2022-12为回放/样本外段；数据截至2026-10-23",
}
