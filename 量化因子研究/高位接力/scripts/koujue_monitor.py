# -*- coding: utf-8 -*-
"""口诀监控报告(koujue_monitor, 主人2026-10-11指令「口诀校验监控——看看目前
行情口诀是否存在变化 或者有新的更优的口诀了」)。

用法:
  ① 先导数据(用时生成, 不留仓库):
    docker exec -i vnpy-alphaagent-api-1 python < 量化因子研究/高位接力/scripts/relay_4to5_dump.py \
      > 量化因子研究/高位接力/四进五全量明细.csv
  ② python3 量化因子研究/高位接力/scripts/koujue_monitor.py [--dig]
     --dig = 加跑当前时代锻造挖掘新候选(慢, 几分钟); 默认只出体检+衰退信号

报告三块:
  1. 13条现状体检(红黄绿: 红=近24月均值<累计均值25%且近12月为负=衰退;
     绿=近24月仍>累计均值一半)
  2. 变化信号(每条近12月均值 vs 全时段均值, 落差>50%=明显衰退, >150%=逆势变肥)
  3. (--dig) 当前时代新候选: 锻造炉挖+八门里最硬的四门(n/胜/剔3/最差年)快筛
"""
import sys
import types

import pandas as pd

_forge_src = open("量化因子研究/高位接力/scripts/koujue_forge.py", encoding="utf-8").read()
_forge_src = _forge_src.replace("\n\nmain()\n", "\n")
forge_mod = types.ModuleType("koujue_forge")
exec(compile(_forge_src, "koujue_forge.py", "exec"), forge_mod.__dict__)


def line(v):
    if len(v) == 0:
        return "0笔"
    return f"{len(v)}笔 胜{(v > 0).mean():.0%} 均{v.mean():+.1f}"


def main() -> None:
    dig = "--dig" in sys.argv
    E = forge_mod.load_events()
    months = sorted(E["月"].unique())
    m12, m24 = months[-12], months[-24]
    print(f"口诀监控报告  数据{months[0]}~{months[-1]} ({len(E)}笔)  近12月={m12}起\n")

    # ---- 1. 13条现状体检 ----
    print("=" * 22, "① 13条口诀现状体检", "=" * 22)
    print(f"{'口诀':<5}{'全时段':>26}{'近24月':>20}  状态")
    for col, gname in (("w_no", "弱市组"), ("s_no", "强市组")):
        for no in sorted(E[col].dropna().unique()):
            v_all = E.loc[E[col] == no, "E3%"]
            v24 = E.loc[(E[col] == no) & (E["月"] >= m24), "E3%"]
            v12 = E.loc[(E[col] == no) & (E["月"] >= m12), "E3%"]
            a_all = v_all.mean() if len(v_all) else 0
            a24 = v24.mean() if len(v24) else 0
            a12 = v12.mean() if len(v12) else 0
            if len(v24) == 0:
                st = "○近两年无形态"
            elif a24 < 0.25 * a_all and a12 < 0:
                st = "红·衰退"
            elif a24 < 0.5 * a_all:
                st = "黄·走弱"
            else:
                st = "绿"
            print(f"{no:<5}{line(v_all):>26}{line(v24):>20}  {st}"
                  f"{'(' + gname + ')' if col == 'w_no' else ''}")

    # ---- 2. 变化信号 ----
    print("\n" + "=" * 22, "② 变化信号(近12月 vs 全时段)", "=" * 22)
    for col in ("w_no", "s_no"):
        for no in sorted(E[col].dropna().unique()):
            v12 = E.loc[(E[col] == no) & (E["月"] >= m12), "E3%"]
            v_all = E.loc[E[col] == no, "E3%"]
            if len(v12) == 0:
                continue
            ratio = v12.mean() / v_all.mean() if v_all.mean() else 0
            if ratio < 0.5:
                sig = "↓↓ 明显衰退"
            elif ratio > 1.5:
                sig = "↑↑ 逆势变肥"
            else:
                continue
            print(f"  {no}: 近12月均{v12.mean():+.1f} vs 全时段均{v_all.mean():+.1f} ({ratio:.0%})  {sig}")

    # ---- 3. 当前时代新候选(--dig) ----
    if dig:
        print("\n" + "=" * 22, "③ 当前时代锻造挖掘(近24月窗)", "=" * 22)
        cards = forge_mod.forge(E, m24, None, ("S", "K"), f"近24月({m24}~)")
        print("(候选卡见上; 与现役重叠<50%才算新格, 边界扰动比值≥0.5才算稳)")
    else:
        print("\n(③ 当前时代挖掘未跑: 加 --dig 参数, 约2~4分钟)")


main()
