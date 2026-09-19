# -*- coding: utf-8 -*-
"""高位接力 · 联动矩阵★格逐一验证（第二十二遍）。

矩阵扫出的★格做完整检验：分年全正/置换2000/去最好3笔/边界晃动/首刻叠加/与现有方案点重叠。
另两个拆解：
- B1的真实驱动是竞价档还是换手梯度？（B1×竞价档 vs 池同竞价档）
- B2的位置窗(-9~-2)是否必要？（低开×4~7×窗内 vs 窗外）

宿主机纯CSV: uv run python relay_interact2.py
"""
import numpy as np
import pandas as pd

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
YEARS = ["2023", "2024", "2025", "2026"]
rng = np.random.default_rng(20260919)


def load():
    E = pd.read_csv(f"{ROOT}/全量明细.csv", dtype={"代码": str})
    X = pd.read_csv(f"{ROOT}/地基均线反包明细.csv", dtype={"代码": str})
    E = E.merge(X[["代码", "买入日", "距MA10%", "前板高度"]], on=["代码", "买入日"], how="left")
    E = E[~E["未完"]].copy()
    E["年"] = E["年"].astype(str)
    E["胜"] = E["次日收%"] > 0
    E["换手梯度"] = E["b2换手%"] - E["b1换手%"]
    return E


def year_str(sub):
    return " | ".join(
        f"{sy['持有到断板%'].mean():+.2f}/{len(sy)}" if len(sy := sub[sub["年"] == y]) else "0笔"
        for y in YEARS)


def all_pos(sub):
    return all(len(sub[sub["年"] == y]) > 0 and
               sub[sub["年"] == y]["持有到断板%"].mean() > 0 for y in YEARS)


def verify(lines, E, name, mask, note=""):
    gname = name.split(" ")[0]
    pool = E[E["四组"] == gname]
    sub = E[mask]
    n = len(sub)
    lines.append(f"\n### {name}（{n}笔）{note}\n")
    if n < 8:
        lines.append("样本太薄不验\n")
        return
    win = sub["胜"].mean() * 100
    hold = sub["持有到断板%"].mean()
    pv = pool["持有到断板%"].to_numpy()
    p_hold = (rng.choice(pv, size=(2000, n), replace=True).mean(axis=1) >= hold).mean()
    tri = sub.sort_values("持有到断板%", ascending=False).iloc[3:]
    tri_pos = all(len(tri[tri["年"] == y]) and tri[tri["年"] == y]["持有到断板%"].mean() > 0
                  for y in YEARS)
    # 方案点重叠
    b1m = (sub["四组"] == "二接三阴") & (sub["b2开盘%"] >= 6) & (sub["b2开盘%"] < 9.5) & \
          (sub["换手梯度"] >= 0) & (sub["换手梯度"] < 2)
    b2m = (sub["四组"] == "二接三阳") & (sub["距60日新高%"] >= -9) & (sub["距60日新高%"] < -2) & \
          (sub["b2开盘%"] < 0) & (sub["买入开盘%"] >= 4) & (sub["买入开盘%"] < 7)
    ov = int((b1m | b2m).sum())
    lines.append(f"- 胜率{win:.0f}% 持有{hold:+.2f}　分年 {year_str(sub)}　"
                 f"{'✅全正' if all_pos(sub) else '❌有负年'}")
    lines.append(f"- 置换p={p_hold:.3f}；去最好3笔后 {tri['持有到断板%'].mean():+.2f}"
                 f"（分年仍全正={'是' if tri_pos else '否'}）；与B1/B2重叠 {ov}/{n} 笔")


def main():
    E = load()
    y = E["四组"] == "二接三阳"
    n = E["四组"] == "二接三阴"
    auc = E["买入开盘%"]
    b2o = E["b2开盘%"]
    lines = ["# 高位接力 · 联动矩阵★格验证（2026-09-19 第二十二遍）", "",
             "来源 = 汇总/一二三板联动.md 矩阵里的★格。全部过：分年全正/置换/去尾/重叠。", ""]

    lines.append("\n## 一、二接三阳组的★格\n")
    verify(lines, E, "二接三阳 二板顶格×竞价7~9.5", y & (b2o >= 9.5) & (auc >= 7) & (auc < 9.5),
           "（矩阵49笔55%+1.5）")
    verify(lines, E, "二接三阳 二板0~2×竞价低开", y & (b2o >= 0) & (b2o < 2) & (auc < 0),
           "（矩阵18笔50%+10.2）")
    verify(lines, E, "二接三阳 二板低开×竞价4~7 (=B2去位置窗)", y & (b2o < 0) & (auc >= 4) & (auc < 7),
           "（矩阵27笔67%+7.5 p=0.006）")

    lines.append("\n## 二、B2位置窗必要性：低开×竞价4~7 拆窗内窗外\n")
    pos = (E["距60日新高%"] >= -9) & (E["距60日新高%"] < -2)
    base = y & (b2o < 0) & (auc >= 4) & (auc < 7)
    verify(lines, E, "二接三阳 低开×4~7×位置窗内(=B2)", base & pos, "（B2本体16笔81%+12.17）")
    verify(lines, E, "二接三阳 低开×4~7×位置窗外", base & ~pos, "")

    lines.append("\n## 二接三阴组的★格（阴组方向：二板高开要竞价更高开=加速确认）\n")
    verify(lines, E, "二接三阴 二板低开×竞价低开", n & (b2o < 0) & (auc < 0))
    verify(lines, E, "二接三阴 二板4~7×竞价7~9.5", n & (b2o >= 4) & (b2o < 7) & (auc >= 7) & (auc < 9.5))
    verify(lines, E, "二接三阴 二板4~7×竞价顶格", n & (b2o >= 4) & (b2o < 7) & (auc >= 9.5))
    verify(lines, E, "二接三阴 二板7~9.5×竞价2~4", n & (b2o >= 7) & (b2o < 9.5) & (auc >= 2) & (auc < 4))
    verify(lines, E, "二接三阴 二板7~9.5×竞价4~7", n & (b2o >= 7) & (b2o < 9.5) & (auc >= 4) & (auc < 7))
    verify(lines, E, "二接三阴 二板7~9.5×竞价7~9.5", n & (b2o >= 7) & (b2o < 9.5) & (auc >= 7) & (auc < 9.5))

    lines.append("\n## 三、B1驱动拆解：B1=二板高开6~9.5×换手微增，真实驱动是竞价档还是换手？\n")
    b1_all = n & (b2o >= 6) & (b2o < 9.5)
    grad_ok = (E["换手梯度"] >= 0) & (E["换手梯度"] < 2)
    for lab, m in [("B1本体(换手微增)", b1_all & grad_ok),
                   ("二板6~9.5×换手不微增", b1_all & ~grad_ok),
                   ("B1×竞价2~9.5(中高开)", b1_all & grad_ok & (auc >= 2) & (auc < 9.5)),
                   ("B1×竞价低开或顶格", b1_all & grad_ok & ((auc < 2) | (auc >= 9.5)))]:
        sub = E[m]
        if len(sub):
            lines.append(f"- {lab}：{len(sub)}笔 胜率{sub['胜'].mean() * 100:.0f}% "
                         f"持有{sub['持有到断板%'].mean():+.2f}　分年 {year_str(sub)}")
    lines.append("")

    text = "\n".join(lines)
    with open(f"{ROOT}/汇总/一二三板联动-验证.md", "w", encoding="utf-8") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main()
