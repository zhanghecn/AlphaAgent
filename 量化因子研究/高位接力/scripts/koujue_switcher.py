# -*- coding: utf-8 -*-
"""口诀切换器优化实验(koujue_switcher, 主人2026-10-11指令「看看能不能把这个
脚本用于复用优化口诀切换器」)。

基线=产品v7.8动态组口径: 上月末状态管本月(判m月用m前12个交易月),
两组(强市8条/弱市K系)各自命中笔E3均值高者整组启用, 样本<8笔或均非正=双开。
变体:
  A. 五类开关——每类(锁仓/强开/低吸/换手/转弱)近12月均值>0且n≥5则开该类,
     出手=开着的类里任一口诀命中(五大类来自koujue_family, 换手系六年全正的
     类级时代属性→变体E: 换手系常开)
  B. 口诀级滚动——每条口诀近12月均值>0且n≥3则开(旧研究: 弱市稀疏失灵, 复现)
  C. 窗口敏感性——基线换6/9/18月
  D. 全开对照(两组都开)
输出: 各口径七年总账+分年, 唯一标准=同分年一致性下均值更高/更稳。
"""
import types

import pandas as pd

_forge_src = open("量化因子研究/高位接力/scripts/koujue_forge.py", encoding="utf-8").read()
_forge_src = _forge_src.replace("\n\nmain()\n", "\n")   # 剥掉脚本级main()调用
forge_mod = types.ModuleType("koujue_forge")
exec(compile(_forge_src, "koujue_forge.py", "exec"), forge_mod.__dict__)

# 五大类映射(koujue_family定稿: 按链形态语言, 不按票重叠)
FAMILY = {
    "A1": "锁仓", "A2": "锁仓", "B3": "锁仓", "C3": "锁仓", "K5": "锁仓",
    "B1": "强开",
    "B2": "低吸", "K3": "低吸", "K9": "低吸",
    "C2": "换手", "K2": "换手", "K4": "换手",
    "C1": "转弱",
}
GRP = {no: ("weak" if no.startswith("K") else "strong") for no in FAMILY}


def load_trades(E):
    """逐笔(月, 口诀, 组, 类, E3); 双命中归K系(产品交割单口径)。"""
    rows = []
    for idx, r in E.iterrows():
        s, w = r.get("s_no"), r.get("w_no")
        no = w if isinstance(w, str) else s
        if not isinstance(no, str):
            continue
        rows.append((r["月"], no, GRP[no], FAMILY[no], float(r["E3%"]), int(r["年"])))
    return rows


def simulate(trades, months, mode="group", window=12, min_group=8, min_small=5):
    """逐月模拟: 判m月用months中m之前的window个交易月。返回出手列表。"""
    out = []
    for i, m in enumerate(months):
        ms = set(months[max(0, i - window):i])
        hist = [(no, g, fam, r) for (mm, no, g, fam, r, _y) in trades if mm in ms]
        if mode == "both":
            allowed = set(FAMILY)
        elif mode == "group":
            wk = [r for no, g, fam, r in hist if g == "weak"]
            st = [r for no, g, fam, r in hist if g == "strong"]
            wa = sum(wk) / len(wk) if wk else None
            sa = sum(st) / len(st) if st else None
            if len(wk) >= min_group and len(st) >= min_group and wa and sa:
                keep = "weak" if wa > sa else "strong"
            elif len(wk) >= min_group and wa and wa > 0:
                keep = "weak"
            elif len(st) >= min_group and sa and sa > 0:
                keep = "strong"
            else:
                keep = "both"
            allowed = set(FAMILY) if keep == "both" else \
                {no for no in FAMILY if GRP[no] == keep}
        elif mode in ("family", "family_huanshou"):
            allowed = set()
            for fam in ("锁仓", "强开", "低吸", "换手", "转弱"):
                fr = [r for no, g, f, r in hist if f == fam]
                if mode == "family_huanshou" and fam == "换手" and len(fr) >= min_small:
                    allowed |= {no for no in FAMILY if FAMILY[no] == fam}
                    continue
                if len(fr) >= min_small and fr and sum(fr) / len(fr) > 0:
                    allowed |= {no for no in FAMILY if FAMILY[no] == fam}
        elif mode == "koujue":
            allowed = set()
            for no in FAMILY:
                nr = [r for n2, g, f, r in hist if n2 == no]
                if len(nr) >= 3 and nr and sum(nr) / len(nr) > 0:
                    allowed.add(no)
        for (mm, no, g, fam, r, y) in trades:
            if mm == m and no in allowed:
                out.append((m, no, g, fam, r, y))
    return out


def report(name, out, months):
    if not out:
        print(f"  {name:<22} 0笔(从不出手)")
        return
    v = pd.Series([t[4] for t in out])
    yr = {y: sum(t[4] for t in out if t[5] == y) for y in sorted({t[5] for t in out})}
    print(f"  {name:<22} {len(v)}笔 胜{(v > 0).mean():.0%} 均{v.mean():+.2f} 和{v.sum():+.1f}"
          f" | 分年 " + " ".join(f"{y}:{s:+.0f}" for y, s in yr.items()))


def main() -> None:
    E = forge_mod.load_events()
    trades = load_trades(E)
    months = sorted(E["月"].unique())
    print(f"底数 {len(E)}笔, 口诀命中 {len(trades)}笔(双命中归K系), "
          f"{months[0]}~{months[-1]} 共{len(months)}月\n")
    print("=" * 24, "切换器口径对比(七年模拟)", "=" * 24)
    report("D.全开对照", trades, months)
    report("基线.两组切换(12月)", simulate(trades, months, "group", 12), months)
    for w in (6, 9, 18):
        report(f"C.两组切换窗{w}月", simulate(trades, months, "group", w), months)
    report("A.五类开关(12月)", simulate(trades, months, "family", 12), months)
    report("E.换手系常开+类开关", simulate(trades, months, "family_huanshou", 12), months)
    report("B.口诀级滚动", simulate(trades, months, "koujue", 12), months)
    # 变体月度出手序列(诊断: 哪年开了什么)
    for mode in ("group", "family"):
        out = simulate(trades, months, mode, 12)
        by_m = {}
        for t in out:
            by_m.setdefault(t[0][:4], set()).add(t[1])
        print(f"\n[{mode}] 分年启用口诀:")
        for y in sorted(by_m):
            print(f"  {y}: {'/'.join(sorted(by_m[y]))}")


main()
