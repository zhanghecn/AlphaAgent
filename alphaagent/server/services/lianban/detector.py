"""日线涨停判定(精确命中原则, 2026-08-12 东财涨停池对账定稿).

规则要点:
- 幅度档: 创业板(300/301) 20%(2020-08-24 注册制前 10%); 科创板(688/689) 20%;
  北交所(8/4/92 开头) 30%; 主板 10%; 主板 ST 5%。
- 判定: close 精确命中理论涨停价, 容差 1e-6。
- 涨停价舍入(2026-08-14 实证分市场定稿):
  主板/创业板/科创板 = round(prev×(1+ratio), 2) 四舍五入到分, round 前 +1e-9 防浮点
  短表示(证据: 主板半值进位样本 2.10×1.05=2.205→实盘涨停价 2.21; 1.70→1.785→1.79);
  北交所 = 分位向下截断 floor(涨停价向上进位会越 30% 限制, 如浩淼科技 920856
  2026-08-12: 11.49×1.3=14.937, round→14.94 但实盘涨停价 14.93), floor 前 +1e-6 元
  防浮点短表示(真值恰为整数分时浮点可能存成 x.xx5999…)。
- 主板 ST 升档自洽(切换日): 候选档 (5%, 10%)。close 命中 5% 档价 → 涨停;
  close 超 5% 档价但未精确命中 10% 档价 → 当日已非 5% 限制但不构成涨停(ST中迪);
  close 精确命中 10% 档价 → 涨停(ST金鸿)。
- 一字板: open == high == low == close 且涨停; low 缺失时以 min(open, close) 近似。
- touched_limit: 未涨停但 high 触及最低档理论涨停价(炸板候选统计用)。
- prev_close 为空/非正 → 不涨停(新股)。

输入契约:
- symbol 为 6 位纯数字代码(无 .SSE/.SZSE 等后缀)。
- open/close/high 必须非 None;low_price 可缺省(以 min(open, close) 近似);
  prev_close 与 name 允许为 None(分别按新股、非 ST 处理)。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

_EPS = 1e-6
_ROUND_GUARD = 1e-9
_FLOOR_GUARD = 1e-4  # 分位截断的浮点防护(0.0001 分 = 1e-6 元)

_CYB_REFORM_DATE = date(2020, 8, 24)  # 创业板注册制: 涨跌幅 10% → 20%


@dataclass(frozen=True)
class LimitUpVerdict:
    is_limit_up: bool
    touched_limit: bool
    is_one_word: bool
    is_st: bool
    board: str  # main/cyb/kcb/bse
    limit_price: float | None


def board_of(symbol: str) -> str:
    if symbol.startswith(("300", "301")):
        return "cyb"
    if symbol.startswith(("688", "689")):
        return "kcb"
    if symbol.startswith(("8", "4", "92")):
        return "bse"
    return "main"


def _limit_price(prev_close: float, ratio: float, board: str) -> float:
    if board == "bse":
        # 北交所实证为分位向下截断(浩淼科技 14.937→14.93);
        # +_FLOOR_GUARD 防真值恰为整数分时的浮点短表示(28.6 存成 28.5999…)。
        return math.floor(prev_close * (1 + ratio) * 100 + _FLOOR_GUARD) / 100
    return round(prev_close * (1 + ratio) + _ROUND_GUARD, 2)


def _candidate_ratios(board: str, is_st: bool, trade_date: date) -> tuple[float, ...]:
    if board == "bse":
        return (0.30,)
    if board == "kcb":
        return (0.20,)
    if board == "cyb":
        return (0.20,) if trade_date >= _CYB_REFORM_DATE else (0.10,)
    # 主板: ST 双档候选(5% 常规 / 10% 切换日升档), 非 ST 单档 10%
    return (0.05, 0.10) if is_st else (0.10,)


def classify_limit_up(
    *,
    symbol: str,
    name: str | None,
    prev_close: float | None,
    open_price: float,
    close_price: float,
    high_price: float,
    trade_date: date,
    low_price: float | None = None,
) -> LimitUpVerdict:
    board = board_of(symbol)
    is_st = "ST" in (name or "").upper()

    if prev_close is None or prev_close <= 0:
        return LimitUpVerdict(False, False, False, is_st, board, None)

    prices = [
        _limit_price(prev_close, r, board) for r in _candidate_ratios(board, is_st, trade_date)
    ]

    # 精确命中任一候选档价即涨停(主板 ST 双档天然覆盖升档自洽:
    # 超 5% 档但未命中 10% 档时不匹配任何档价 → 不涨停)。
    hit = next((p for p in prices if abs(close_price - p) <= _EPS), None)
    is_limit_up = hit is not None

    touched_limit = not is_limit_up and high_price >= prices[0] - _EPS

    low = low_price if low_price is not None else min(open_price, close_price)
    is_one_word = is_limit_up and (
        abs(open_price - close_price) <= _EPS
        and abs(open_price - high_price) <= _EPS
        and abs(open_price - low) <= _EPS
    )

    return LimitUpVerdict(is_limit_up, touched_limit, is_one_word, is_st, board, hit)
