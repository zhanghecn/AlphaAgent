# -*- coding: utf-8 -*-
"""自动选诀器+端到端演练(koujue_autopick, 主人终极问题「目前能够做到么
自动发现新口诀 包括实时监控 口诀变化」的实证回答)。

把「人工挑口诀」写成明确规则(不再依赖人审拍板):
  第一步 挖: 锻造炉完整管线(合并档网格+交互腿+差票过滤)→全时段合格格
  第二步 硬过滤(八门): n≥10 / 胜≥60% / 剔3>0 / 分年最差>-10 / 均值≤13(R6彩票线)
  第三步 排序规则(人工挑选的数据化):
    主排序 = 剔3均值×ln(n)(剔3防单笔妖票撑格, 是人工看「去掉大肉还剩多少」)
    同类近亲合并(票重叠≥60%取分高者), 每类最多2条, 全体最多8条(口诀规模对照人工13条)
  第四步 对照: 机器口诀 vs 该段人工定型口诀(判定重叠J) + 样本外回放

端到端演练(只给过去, 验证能不能自动得出当时的口诀):
  演练1: 只给 2020-01~2023-08(弱市段) → 机器应产出 ≈K系
  演练2: 只给 2023-09~2026-10(强市段) → 机器应产出 ≈八条
  样本外: 演练1的口诀放到 2023-09后 回放(真换代场景: 挖出的诀在下个时代活没活)
"""
import math
import types

import numpy as np
import pandas as pd

_forge_src = open("量化因子研究/高位接力/scripts/koujue_forge.py", encoding="utf-8").read()
_forge_src = _forge_src.replace("\n\nmain()\n", "\n")
forge_mod = types.ModuleType("koujue_forge")
exec(compile(_forge_src, "koujue_forge.py", "exec"), forge_mod.__dict__)


def family_of(t):
    """格→五大类(koujue_family判据: 链开窗触一字贴零→锁仓/强开→强开/低开→低吸/换手腿→换手)。"""
    pool, legs, tr, inc, exc, _ = t
    def touches(rng, seg):
        return not (rng[1] <= seg[0] or rng[0] >= seg[1])
    wins = [r for _, r in legs] + [tr]
    if any(touches(r, (9.5, 99)) or touches(r, (0, 3)) for r in wins):
        return "锁仓"
    if any(touches(r, (7, 9.5)) for r in wins):
        return "强开"
    if any(touches(r, (-99, 0)) for r in wins):
        return "低吸"
    if any("换手" in a for a, _ in inc):
        return "换手"
    return "转弱"


def autopick(E, lo, hi, label, max_koujue=8):
    """自动选诀: 挖→硬过滤→规则排序→类内取代表。返回机器口诀列表。"""
    W = pd.Series(True, index=E.index)
    if lo:
        W &= E["月"] >= lo
    if hi:
        W &= E["月"] <= hi
    wn = W.to_numpy()
    e3v = E["E3%"].to_numpy()
    yr = E["年"].to_numpy()

    # 挖(forge完整管线)——盲测: 打标列置空, forge的现役对照/剔除全部失效,
    # 机器只看数据不许抄答案(现役口诀标签=人工答案, 只用于事後对照)
    import io
    import contextlib
    E_blind = E.copy()
    E_blind["s_no"] = None
    E_blind["w_no"] = None
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cards = forge_mod.forge(E_blind, lo, hi, ("S", "K"), label)
    print(f"\n{'=' * 22} {label}: 自动选诀 {'=' * 22}")

    def stats(m):
        mv = m.to_numpy() & wn
        v = e3v[mv]
        n = len(v)
        if n == 0:
            return None
        t3 = np.sort(v)[:-3].mean() if n > 3 else v.mean()
        yrs = pd.Series(v).groupby(yr[mv])
        per_year = {int(y): (int(len(g)), float((g > 0).mean()), float(g.mean()))
                    for y, g in yrs}
        return dict(n=n, avg=v.mean(), win=(v > 0).mean(), t3=t3,
                    worst_yr=yrs.mean().min(), idx=set(E.index[mv]),
                    per_year=per_year)

    picked, used_idx = [], set()
    cand = []
    for sc, t, s, ov, bp in cards:
        stt = stats(t[5])
        if stt is None:
            continue
        # 硬过滤 v3(主人2026-10-11柔性年门槛: 年笔数3/9/0都正常=行情差异, 不硬卡):
        # ①n≥3的年份胜率须≥60%(1~2笔小年样本不够不检验) ②最大年份占比≤60%(防一年撑格)
        # ③有票年份数≥2 + 原五门(n/总胜/剔3/最差年/R6)
        years = stt["per_year"]
        testable = [wy for ny, wy, _a in years.values() if ny >= 3]
        ok_years = bool(testable) and all(wy >= 0.60 for wy in testable)
        max_share = max(ny for ny, _w, _a in years.values()) / stt["n"]
        ok_spread = len(years) >= 2 and max_share <= 0.60
        if (stt["n"] < 10 or stt["win"] < 0.60 or stt["t3"] <= 0
                or stt["worst_yr"] <= -10 or stt["avg"] > 13
                or not ok_years or not ok_spread):
            continue
        cand.append((stt["t3"] * math.log(stt["n"]), t, stt, bp))
    cand.sort(key=lambda x: -x[0])
    fam_cnt = {}
    for score, t, stt, bp in cand:
        fam = family_of(t)
        if fam_cnt.get(fam, 0) >= 2 or len(picked) >= max_koujue:
            continue
        if stt["idx"] & used_idx and len(stt["idx"] & used_idx) / len(stt["idx"]) >= 0.6:
            continue   # 近亲合并: 与已选票重叠≥60%跳过
        picked.append((t, stt, fam, bp))
        used_idx |= stt["idx"]
        fam_cnt[fam] = fam_cnt.get(fam, 0) + 1
    print(f"候选{len(cards)} → 过滤后{len(cand)} → 自动立诀 {len(picked)} 条:")
    for t, stt, fam, bp in picked:
        desc = forge_mod.describe(t, lambda m: (stt["n"], stt["avg"], stt["win"], stt["t3"]))
        yr_txt = " ".join(f"{y}:{ny}笔胜{wy:.0%}"
                          for y, (ny, wy, _a) in sorted(stt["per_year"].items()))
        print(f"  [{fam}] {desc}")
        print(f"        分年 {yr_txt} | 扰动比{bp:.2f}")
    return picked


def replay(E, picked, lo, hi, label):
    """样本外回放: 机器口诀(格条件)在另一时段的成绩。"""
    W = pd.Series(True, index=E.index)
    if lo:
        W &= E["月"] >= lo
    if hi:
        W &= E["月"] <= hi
    print(f"\n—— {label} ——")
    total = []
    for t, stt, fam, bp in picked:
        m = t[5] & W   # t[5]是全E mask
        v = E.loc[m.to_numpy(), "E3%"]
        if len(v) == 0:
            print(f"  [{fam}] 形态消失 0笔")
            continue
        t3 = v.drop(v.nlargest(3).index).mean() if len(v) > 3 else v.mean()
        print(f"  [{fam}] {len(v)}笔 胜{(v > 0).mean():.0%} 均{v.mean():+.1f} 剔3{t3:+.1f}"
              f" 和{v.sum():+.1f}")
        total.extend(v.tolist())
    if total:
        tv = pd.Series(total)
        print(f"  合计 {len(tv)}笔 胜{(tv > 0).mean():.0%} 均{tv.mean():+.2f} 和{tv.sum():+.1f}")
    return total


def compare_manual(E, picked, lo, hi, label):
    """对照: 机器口诀票集 vs 该段人工定型口诀命中集(逐条J + 总覆盖)。"""
    W = pd.Series(True, index=E.index)
    if lo:
        W &= E["月"] >= lo
    if hi:
        W &= E["月"] <= hi
    print(f"\n—— {label}: 机器 vs 人工对照 ——")
    manual = {}
    for col, pre in (("w_no", "K"), ("s_no", "S")):
        for no in E[col].dropna().unique():
            m = (E[col] == no) & W
            if int(m.sum()) >= 3:
                manual[str(no)] = set(E.index[m])
    mach_sets = [stt["idx"] for _, stt, _, _ in picked]
    mach_union = set().union(*mach_sets) if mach_sets else set()
    for no, mset in sorted(manual.items()):
        best = max((len(s & mset) / len(s | mset) if s | mset else 0) for s in mach_sets) \
            if mach_sets else 0
        cov = len(mach_union & mset) / len(mset) if mset else 0
        print(f"  {no}({len(mset)}笔): 最佳J={best:.2f} 被机器并集覆盖{cov:.0%}")
    print(f"  人工{len(manual)}条 ↔ 机器{len(picked)}条")


def main() -> None:
    import sys
    roll_only = "--roll" in sys.argv
    E = forge_mod.load_events()
    if not roll_only:
        # 演练1: 只给弱市段 → 机器自动立诀 → 对照真K系 + 强市段样本外(真换代场景)
        p1 = autopick(E, "2020-01", "2023-08", "演练1·只给弱市段(2020-01~2023-08)")
        compare_manual(E, p1, "2020-01", "2023-08", "演练1")
        replay(E, p1, "2023-09", None, "演练1口诀 → 强市段(2023-09~今)样本外回放")
        # 演练2: 只给强市段 → 对照八条
        p2 = autopick(E, "2023-09", None, "演练2·只给强市段(2023-09~今)")
        compare_manual(E, p2, "2023-09", None, "演练2")
    # 演练3: 滚动逐年终审——站在每年末只用之前数据自动选诀, 下一年回放
    print(f"\n{'=' * 22} 演练3·滚动逐年终审(柔性年门槛规则) {'=' * 22}")
    for y_end in (2021, 2022, 2023, 2024, 2025):
        hi = f"{y_end}-12"
        lo_next, hi_next = f"{y_end + 1}-01", (f"{y_end + 1}-12" if y_end < 2025 else None)
        pk = autopick(E, None, hi, f"滚动{y_end}末(数据截至{hi})")
        replay(E, pk, lo_next, hi_next, f"滚动{y_end}末口诀 → {y_end + 1}年回放")


main()
