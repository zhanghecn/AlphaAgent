"""U型补涨打板 · U模型共享原语（pool.py 与 backtest.py 共用，口径唯一事实源）。

移植自研究侧（量化因子研究/低吸研究/scripts/，定稿 commit f6737678）：
- classify_base ← w2s_base_type.py:29（七类互斥完备，D-1 全可观测）
- 锚/断板期口径 ← build_base + w2s_v3_wave_research.py:1098-1107（n_lim_mid 向量化公式）
- bigtop_fix ← w2s_v4_groups.py（4+夹层票锚修正：seg_h<4 时对最新≥4段顶重算）

指数对齐约定（重要）：
  研究侧事件行 = D0（触板日），p_* 为 D-1；服务侧信号行 = T-1（=研究 D-1）。
  故本模块全部函数以「信号日 T-1 收盘」为口径：
    mid（断板期）= (末板, 信号日] 含信号日；gap_d0 = (信号日+1) - 末板 = 研究 gap；
    n_lim_mid = (末板, 信号日] 内涨停日数；ma/mx20 在信号日无 shift。
  分数口径（-0.04 = -4%），与研究侧完全一致。
"""

from __future__ import annotations

import numpy as np

# 地基七类（与研究侧 BASE_ORDER 一致）
BASE_ORDER = ["HIGH", "FLAT", "U", "V", "MID", "LB", "DN"]
BASE_NAME = {"HIGH": "新高贴顶", "FLAT": "横盘平台", "U": "U型蹲", "V": "V末反",
             "MID": "中位浅调", "LB": "L趴底", "DN": "阴跌到点"}
# 蹲类地基（2板系白名单用地基集合）
SQUAT_BASES = ("U", "MID", "FLAT", "V", "LB")
# 均线纠缠态
TANGLE_MA = ("-++", "+--")

# U 三状态标签（展示层）
POS_NO_U = "无U"
POS_BREAK = "U突破"
POS_IN = "U坑内"

# 组 key（内部名，用户可见中文名在 contracts.GROUP_LABELS）
GROUP_YIN2 = "yin2"      # 2板阴 · U坑
GROUP_YANG2A = "yang2a"  # 2板阳 · 坑底首阳
GROUP_YANG2B = "yang2b"  # 2板阳 · 坑中纠缠
GROUP_YIN4 = "yin4"      # 4+阴 · 孤板多头
GROUP_YANG4 = "yang4"    # 4+阳 · 2板穿插
GROUP_KEYS = (GROUP_YIN2, GROUP_YANG2A, GROUP_YANG2B, GROUP_YIN4, GROUP_YANG4)


def classify_base(mid_c: np.ndarray, top_px: float, prev_close: float) -> dict | None:
    """断板期收盘序列 → 地基类型 + 特征。逐字移植研究侧 w2s_base_type.classify_base。

    mid_c: 断板期每日收盘（np.array，含信号日，不含上波末板与D0）；
    top_px: 上波（≥2板段）最高价；prev_close: 信号日收盘。
    """
    n = len(mid_c)
    if n == 0 or top_px != top_px or prev_close != prev_close:
        return None
    pull = prev_close / top_px - 1                    # 现位置（信号日收距顶）
    low_i = int(np.argmin(mid_c))                     # 最低收盘索引
    low_dd = mid_c[low_i] / top_px - 1                # 最深蹲（收盘口径，插针不算）
    reb = prev_close / mid_c[low_i] - 1               # 洗后反弹高度
    pos_low = (low_i / (n - 1)) if n > 1 else 0.0     # 低点位置（0=断板首日, 1=信号日）
    amp = mid_c.max() / mid_c[low_i] - 1              # 期间收盘总振幅
    brk = mid_c.max() > top_px                        # 期间破过顶
    if pull > -0.04:
        base = "HIGH"
    elif amp <= 0.10 and pull > -0.12:
        base = "FLAT"
    elif reb < 0.03 and pos_low > 0.6:
        base = "DN"
    elif low_dd <= -0.12 and reb < 0.03:
        base = "LB"
    elif low_dd <= -0.12 and reb >= 0.06:
        base = "U" if pos_low <= 0.6 else "V"
    else:
        base = "MID"
    return {"base": base, "pull": pull, "low_dd": low_dd, "reb": reb,
            "pos_low": pos_low, "amp": amp, "brk": bool(brk)}


def _last_leq(positions: np.ndarray, i: int) -> int:
    """positions（升序）中最后一个 <= i 的值；无则 -1。"""
    k = int(np.searchsorted(positions, i, side="right")) - 1
    return int(positions[k]) if k >= 0 else -1


def u_features(close: np.ndarray, high: np.ndarray, is_lim: np.ndarray,
               streak: np.ndarray, i: int, bigtop: bool = False) -> dict | None:
    """单股序列 + 信号日下标 i → U模型特征 dict；最近无≥2板段返回 None。

    close/high/is_lim/streak: 按交易日升序的等长 numpy 序列（is_lim 为 bool）。
    bigtop: 4+组票置 True——夹层票(seg_h<4)按 bigtop_fix 对最新≥4段顶重算
            low_dd/pull/reb/gap_d0（研究侧只对 4板组做此修正，2板组锚就是2板段）。
    返回字段：
      seg_h      最近≥2板段高度（末板日 streak 值）
      gap_d0     坑宽（研究口径 = D0-末板 = i+1-lp）
      n_lim_mid  断板期孤立涨停日数（(lp, i] 内涨停天数；≥2段会前移 lp 故天然是孤立板）
      topped     断板期曾收盘 ≥ 最后一次涨停日收盘（伪U；锚=最后涨停日含孤立板）
      d23ok      下探中：close[i-1] < close[i-2] 且 i-2 日非涨停（i<3 数据不足=False）
      ma_st      均线排列态（ma5/10/20/30 在信号日无 shift；数据不足=None）
      big4       是否存在最新≥4段（夹层修正用）
      base/pull/low_dd/reb/pos_low/amp/brk ← classify_base（锚=最近≥2段顶）
      pos3       U三状态（用修正后的 low_dd/pull）
    """
    n = len(close)
    if i < 1 or i >= n:
        return None
    ge2 = np.flatnonzero(streak >= 2)
    lp = _last_leq(ge2, i - 1)          # 最近≥2段末板（信号日前；信号日本身非涨停由调用方保证）
    if lp < 0:
        return None
    seg_h = int(streak[lp])
    seg_top = float(np.max(high[lp - seg_h + 1: lp + 1]))
    mid = close[lp + 1: i + 1]
    info = classify_base(mid, seg_top, float(close[i]))
    if info is None:
        return None

    # 伪U：断板期曾收在「最后一次涨停日」收盘上方（锚含孤立板，与研究口径一致）
    lim_pos = np.flatnonzero(is_lim[: i + 1])
    j = int(lim_pos[-1]) if len(lim_pos) else -1
    topped = bool(j >= 0 and j < i and (close[j + 1: i + 1] >= close[j]).any())

    n_lim_mid = int(is_lim[lp + 1: i + 1].sum())
    gap_d0 = (i + 1) - lp

    # 下探中（研究 d23: i_r=D0=i+1，c[i_r-2]=close[i-1]，c[i_r-3]=close[i-2]，i_r<4→None）
    d23ok = bool(i >= 3 and close[i - 1] < close[i - 2] and not is_lim[i - 2])

    # 均线排列态（信号日无 shift = 研究 D-1 口径）
    def _ma(w: int) -> float:
        return float(np.mean(close[i - w + 1: i + 1])) if i + 1 >= w else float("nan")

    ma5, ma10, ma20, ma30 = _ma(5), _ma(10), _ma(20), _ma(30)
    ma_st = None
    if ma30 == ma30:
        ma_st = (("+" if ma5 > ma10 else "-") + ("+" if ma10 > ma20 else "-")
                 + ("+" if ma20 > ma30 else "-"))

    # 4+组夹层票锚修正（bigtop_fix 移植, 仅 4+组启用）: seg_h<4 且有≥4段 → 对最新≥4段顶重算
    ge4 = np.flatnonzero(streak >= 4)
    b4p = _last_leq(ge4, i - 1)
    big4 = b4p >= 0
    low_dd, pull, reb = info["low_dd"], info["pull"], info["reb"]
    if bigtop and big4 and seg_h < 4:
        b4_h = int(streak[b4p])
        b4_top = float(np.max(high[b4p - b4_h + 1: b4p + 1]))
        mid4 = close[b4p + 1: i + 1]
        if len(mid4):
            low4 = float(np.min(mid4))
            low_dd = low4 / b4_top - 1
            pull = float(close[i]) / b4_top - 1
            reb = float(close[i]) / low4 - 1
            gap_d0 = (i + 1) - b4p

    if low_dd > -0.04:
        pos3 = POS_NO_U
    elif pull > -0.04:
        pos3 = POS_BREAK
    else:
        pos3 = POS_IN

    return {"base": info["base"], "pos_low": info["pos_low"], "amp": info["amp"],
            "brk": info["brk"], "seg_h": seg_h, "gap_d0": gap_d0, "n_lim_mid": n_lim_mid,
            "topped": topped, "d23ok": d23ok, "ma_st": ma_st, "big4": big4,
            "low_dd": low_dd, "pull": pull, "reb": reb, "pos3": pos3}


def actionable_of(group_key: str, f: dict) -> bool:
    """四组白名单出手判定（研究 tier_of 移植；f=u_features 返回值）。

    2板阴：蹲类 × 弹回≤16% × 坑宽6~15 × 未收顶上
    2板阳·首阳：DN × 未收顶上
    2板阳·纠缠：蹲类 × 均线纠缠 × 下探中
    4+阴：孤立板1~2 × 全多头 × U坑存在 × 剔中坑8~15%已回顶
    4+阳：seg_h==2（2板小波穿插；无U也出手=夹层例外）
    """
    if group_key == GROUP_YIN2:
        return (f["base"] in SQUAT_BASES and not f["topped"]
                and f["reb"] <= 0.16 and 6 <= f["gap_d0"] <= 15)
    if group_key == GROUP_YANG2A:
        return f["base"] == "DN" and not f["topped"]
    if group_key == GROUP_YANG2B:
        return (f["base"] in SQUAT_BASES and f["ma_st"] in TANGLE_MA and f["d23ok"])
    if group_key == GROUP_YIN4:
        toxic = f["pull"] > -0.04 and -0.15 < f["low_dd"] <= -0.08
        return (f["seg_h"] >= 4 and 1 <= f["n_lim_mid"] <= 2 and f["ma_st"] == "+++"
                and f["low_dd"] <= -0.04 and not toxic)
    if group_key == GROUP_YANG4:
        return f["seg_h"] == 2
    return False
