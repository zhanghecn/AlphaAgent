# -*- coding: utf-8 -*-
"""一接二 · 好差票验证月度文件(完全对齐 hpr 好差票验证格式)。

结构 = 好差票验证/<组>/YYYY-MM.md + _索引_<组>.csv, 组 = 一接二阴/一接二阳(地基阴阳)。
每票区块: 标题行(票/日/好坏:原因) + 首刻/首板/地基/底盘/加分/方案 六行;
方案行: 命中=G1【阴坑满开】/S1【阳坑半开】; 未命中=—(G1差[...]；S1差[...]);
毒格=贴顶回避/顶格透支(命中也不买)。
坏票 = 买入后第二天收盘低于买价(炸板没收回/封次日负); 好票 = 连板/炸板收回/封板续涨。
"""
import os

import pandas as pd

OUT = "/tmp/research/j12_out"
DEST = f"{OUT}/好差票验证"
TOUCH = "/tmp/research/触板时间-G1S1.csv"   # 命中票首刻(2024-08-15起)

HEADER = """# 一接二 · {grp} · {month} · 好票坏票清单（G1/S1 两点标记，本月命中 {hits} 笔）
> 方案 = 竞价确认两分支（条件见 量化因子研究/一接二/一接二规则.md v1.1）


本月触发 {n} 笔 | 坏票 {bad}（炸板没收回 {blow} + 封住次日跌 {fneg}） | 好票 {good}（继续连板 {cont}） | 坏票率 {badpct}% | **命中 {hitline}**

**一接二·两点版(买入前可知 × 今天竞价，命中才出手)**
- **G1【阴坑满开】**：地基阴线(首板前一天收<开) × 今天开7.5~9.5
- **S1【阳坑半开】**：地基阳线 × 首板前10日跌超3% × 今天开7.5~8.5
- 「—」= 未命中不出手；差的条件在每票「方案」行逐条列出
- 命中也不买：地基贴60日高(0~10%)力竭；今天开≥9.5顶格透支

**判定标准**
- 买入 = 盘中碰到涨停价按涨停价买；一字板（全天没打开）买不进，已剔除
- 坏票 = 买入后第二天收盘低于买价（炸板但第二天涨回来的算好票）
- 持有到断板 = 涨停价买入，首次不再涨停的那天收盘卖出，15个交易日兜底
- E3 = 卖出纪律全套沿用 hpr v6.7（炸板当日走/断板日收盘卖/D+2深开竞价卖/一字死封顺延）

**字段说明**
- 首板 = 昨天「板型+开盘涨幅%」(板型分 一字/T字/实体/下影)；今天开 = 竞价开盘涨幅%
- 地基 = 首板前一天阴阳和涨跌幅；距新高 = 地基收盘距60日新高%
- 底盘 = 地基前60日板史（纯底盘无板/孤立板/前波连板）；前10日/前20日 = 地基日回看涨幅
- 距20日线 = 地基收盘距MA20%；加分 = 锁板(首板换手<8)/深坑(距20线<-5)/大阴洗透(跌超5%)——只管仓位不管进出
- 首刻 = 当天第一次碰涨停价的时段(9:45=9:30~9:45那根15分钟)；「—」=未采集
"""


def fmt_pct(v):
    return f"{v:+.1f}" if v == v else "—"


def classify_ticket(r):
    """返回 (好坏, 标签): 好坏 ∈ 好/坏。"""
    n1 = r["次日收%"]
    if n1 < 0:
        return "坏", ("炸板" if not r["封住"] else "封次日负")
    if r["封住"] and n1 >= 9.9:
        return "好", "连板"
    if not r["封住"]:
        return "好", "炸板收回"
    return "好", "封板续涨"


def point_line(r):
    """方案行: 命中点名 / 毒格回避 / 未命中逐条差条件。"""
    o = r["买入开盘%"]
    yin = r["地基阴阳"] == "阴"
    d60 = r["地基距60高%"]
    pre10 = r["前10日涨幅%"]
    if d60 == d60 and 0 <= d60 <= 10:
        return f"贴顶回避（地基距60日高{d60:+.1f}%，力竭命中也不买）"
    if o >= 9.5:
        return f"顶格透支（今天开{o:+.1f}≥9.5，命中也不买）"
    if yin:
        if 7.5 <= o < 9.5:
            return "G1【阴坑满开】"
        return f"—（G1差[今天开7.5~9.5，实际{fmt_pct(o)}]；S1差[地基阴线]）"
    if pre10 < -3:
        if 7.5 <= o < 8.5:
            return "S1【阳坑半开】"
        return f"—（S1差[今天开7.5~8.5，实际{fmt_pct(o)}]；G1差[地基阳线]）"
    return (f"—（G1差[地基阳线]；S1差[前10日跌超3%(实际{fmt_pct(pre10)})"
            + (f"；今天开7.5~8.5(实际{fmt_pct(o)})" if 7.5 <= o < 8.5 else "") + "]）")


def ticket_block(r, touch):
    gb, tag = classify_ticket(r)   # 返回给调用方统计用(勿从文本反解析)
    p = point_line(r)
    bonus = r.get("加分") if "加分" in r else None
    lines = [
        f"### {r['名称']} {r['代码']}｜{r['买入日'].date()}｜{gb}票：{tag}",
        "",
        f"- 首刻：{touch}｜次日开 {fmt_pct(r['次日开%'])}｜次日收 {fmt_pct(r['次日收%'])}"
        f"｜断板收益 {fmt_pct(r['持有到断板%'])}｜E3 {fmt_pct(r['E3%'])}",
        f"- 首板：{r['首板板型']}{fmt_pct(r['首板开盘%'])}(换手{r['首板换手%']:.1f})"
        f"｜今天开 {fmt_pct(r['买入开盘%'])}",
        f"- 地基：{r['地基阴阳']}{fmt_pct(r['地基涨跌%'])}｜距新高 {fmt_pct(r['地基距60高%'])}"
        f"｜距20日线 {fmt_pct(r['地基距MA20%'])}｜前10日 {fmt_pct(r['前10日涨幅%'])}",
        f"- 底盘：{r['底盘纯度']}｜前20日 {fmt_pct(r['前20日涨幅%'])}"
        f"｜当日涨停家数 {int(r['昨日涨停家数'])}",
    ]
    if bonus:
        lines.append(f"- 加分：{bonus}")
    lines.append(f"- 方案：{p}")
    lines.append("")
    return gb, tag, "\n".join(lines)


def main():
    E = pd.read_csv(f"{OUT}/全量明细.csv", parse_dates=["买入日"])
    E["年"] = E["年"].astype(str)
    d = E[~E["未完"]].copy()
    n_ow = 0
    if "首开一字" in d.columns:
        n_ow = int(d["首开一字"].sum())
        d = d[~d["首开一字"]].copy()   # 二板开盘即一字的票不进清单(含T字)
    touch_map = {}
    if os.path.exists(TOUCH):
        T = pd.read_csv(TOUCH, dtype={"代码": str})
        T = T[T["首触"] != "未触板"]
        touch_map = {(r["代码"], str(r["买入日"])[:10]): r["首触"] for _, r in T.iterrows()}

    os.makedirs(DEST, exist_ok=True)
    idx_rows = []
    for grp_name, grp_key in [("一接二阴", "阴"), ("一接二阳", "阳")]:
        gd = d[d["地基阴阳"] == grp_key]
        os.makedirs(f"{DEST}/{grp_name}", exist_ok=True)
        for month, sub in gd.groupby("月"):
            sub = sub.sort_values(["买入日", "名称"])
            blocks_bad, blocks_good = [], []
            n_cont = n_blow = n_fneg = 0
            hits = {"G1": [], "S1": []}
            for _, r in sub.iterrows():
                t = touch_map.get((r["代码"], str(r["买入日"])[:10]), "—")
                gb, tag, blk = ticket_block(r, t)
                if gb == "坏":
                    blocks_bad.append(blk)
                    if tag == "炸板":
                        n_blow += 1
                    elif tag == "封次日负":
                        n_fneg += 1
                else:
                    blocks_good.append(blk)
                    if tag == "连板":
                        n_cont += 1
                pl = blk.split("方案：")[-1]
                for p in ("G1", "S1"):
                    if pl.startswith(p):
                        hits[p].append(float(r["E3%"]))
            hit_parts = []
            for p in ("G1", "S1"):
                v = hits[p]
                if v:
                    hit_parts.append(f"{p} {len(v)}笔/胜率{(pd.Series(v) > 0).mean() * 100:.0f}%"
                                     f"/{pd.Series(v).mean():+.2f}")
            hitline = " + ".join(hit_parts) if hit_parts else "0笔"
            n = len(sub)
            n_bad, n_good = len(blocks_bad), len(blocks_good)
            head = HEADER.format(grp=grp_name, month=month, hits=sum(len(v) for v in hits.values()),
                                 n=n, bad=n_bad, blow=n_blow, fneg=n_fneg,
                                 good=n_good, cont=n_cont,
                                 badpct=round(n_bad / n * 100) if n else 0,
                                 hitline=hitline)
            body = head + "\n## 坏票 — %d 笔\n\n" % n_bad + "\n".join(blocks_bad) \
                + "\n## 好票 — %d 笔\n\n" % n_good + "\n".join(blocks_good)
            with open(f"{DEST}/{grp_name}/{month}.md", "w", encoding="utf-8") as fh:
                fh.write(body)
            idx_rows.append({"组": grp_name, "月": month, "触发": n, "炸板": n_blow,
                             "封次日负": n_fneg, "好票": n_good, "连板": n_cont,
                             "坏票率%": round(n_bad / n * 100) if n else 0})
        pd.DataFrame(idx_rows).to_csv(f"{DEST}/_索引_{grp_name}.csv",
                                      index=False, encoding="utf-8-sig")
    print(f"生成完毕: {len(idx_rows)} 行索引(剔二板一字开盘 {n_ow} 笔), 组目录 一接二阴/一接二阳")


if __name__ == "__main__":
    main()
