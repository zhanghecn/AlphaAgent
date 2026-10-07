# -*- coding: utf-8 -*-
"""一接二 · 第二轮B2: 三个第二曲线候选细挖(晃动/分年/样本外分年/与G1互斥)。"""
import numpy as np
import pandas as pd

OUT = "/tmp/research/j12_out"


def load():
    E = pd.read_csv(f"{OUT}/全量明细.csv", parse_dates=["买入日"])
    E["年"] = E["年"].astype(str)
    return E[~E["未完"]].copy()


def stat(d, m, name):
    sub = d[m]
    main = sub[sub["段"] == "主窗"]
    oos = sub[sub["段"] == "样本外"]
    out = [f"{name}"]
    for tag, s in [("主窗", main), ("OOS", oos)]:
        if len(s):
            yr = s.groupby("年")["E3%"].agg(["count", "mean"])
            ys = "/".join(f"{y[2:]}:{int(r['count'])}笔{r['mean']:+.2f}" for y, r in yr.iterrows())
            out.append(f"{tag} {len(s)}笔 胜{(s['E3%'] > 0).mean() * 100:.0f}% 均{s['E3%'].mean():+.2f}"
                       f"{'✅' if all(yr['mean'] > 0) else '❌'}({ys})")
    print(" | ".join(out))
    return main, oos


def main():
    d = load()
    g1 = (d["地基阴阳"] == "阴") & d["买入开盘%"].between(7.5, 9.5, inclusive="left")
    G1 = d[g1]
    print("=== S1 阳版镜像: 阳×前10日跌×今开7.5~8.5 ===")
    for c in [-5, -3, 0]:
        for a, b in [(7, 8.5), (7.5, 8.5), (7.5, 9.5), (6.5, 8.5)]:
            stat(d, (d["地基阴阳"] == "阳") & (d["前10日涨幅%"] < c)
                 & d["买入开盘%"].between(a, b, inclusive="left"),
                 f"阳×前10<{c}×今开{a}~{b}")
    print("\n=== S2 秒板接力: 前波连板×首板开7~9.5 ===")
    for a, b in [(7, 9.5), (7, 99), (3, 9.5)]:
        for extra_name, em in [("", pd.Series(True, index=d.index)),
                               ("×阴", d["地基阴阳"] == "阴")]:
            m = (d["底盘纯度"] == "前波连板") & d["首板开盘%"].between(a, b, inclusive="left") & em
            stat(d, m, f"前波连板×首板开{a}~{b}{extra_name}")
    print("\n=== S3 平开坑票: 今开0~2×前10日跌 第三腿提纯 ===")
    base = d["买入开盘%"].between(0, 2, inclusive="left") & (d["前10日涨幅%"] < 0)
    for name, em in [("裸格", pd.Series(True, index=d.index)),
                     ("×阴", d["地基阴阳"] == "阴"), ("×阳", d["地基阴阳"] == "阳"),
                     ("×前波连板", d["底盘纯度"] == "前波连板"), ("×距MA20<-5", d["地基距MA20%"] < -5),
                     ("×距MA20<0", d["地基距MA20%"] < 0), ("×换手<8", d["首板换手%"] < 8),
                     ("×换手<5", d["首板换手%"] < 5), ("×低位/跌透", d["位置五档"].isin(["低位", "跌透"])),
                     ("×实体板", d["首板板型"] == "实体"), ("×量比<1", d["首板量比"] < 1)]:
        stat(d, base & em, f"今开0~2×前10跌{name}")
    print("\n=== S4 与G1关系: 阴×距MA20深下(不限今开) ===")
    s4 = (d["地基阴阳"] == "阴") & (d["地基距MA20%"] < -10)
    stat(d, s4, "阴×深下 全部")
    stat(d, s4 & ~g1, "阴×深下 减G1(=今开不在7.5~9.5)")
    stat(d, s4 & g1, "阴×深下 ∩G1")
    print("\n=== 互斥检查(第二曲线格 ∩ G1) ===")
    for name, m in [("S1阳×前10跌×今开7.5~8.5", (d["地基阴阳"] == "阳") & (d["前10日涨幅%"] < 0)
                     & d["买入开盘%"].between(7.5, 8.5, inclusive="left")),
                    ("S3今开0~2×前10跌", base)]:
        inter = (m & g1).sum()
        print(f"- {name} ∩ G1 = {inter} 笔")


if __name__ == "__main__":
    main()
