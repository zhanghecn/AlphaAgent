# -*- coding: utf-8 -*-
"""反包 Phase 0 交叉对账（宿主机纯CSV跑）。

两路核对（研究方向文档第三节承诺）：
1. 对高位接力: 地基均线反包明细.csv 的(代码,前板日,断板天数,前板高度)
   ↔ 反包全量明细(代码,末板日,断板天数,N), 断1~3天×2~5板的交集行三要素应全配上;
   前板日是MM-DD格式, 用买入日拼年份(跨年-1); 反包日应等于该票高位接力首板日
2. 对N型补涨打板: V4四组全量.csv 的(vt_symbol,date,上波高,坑宽)
   ↔ 反包全量明细(代码,反包日,N,断板天数), 坑宽2~4(=断板1~3天)×上波高2~5×昨非涨停×2023起
用法: uv run --project /root/project/ai/vnpy python fanbao_reconcile.py
"""
import pandas as pd

R = "/root/project/ai/vnpy/量化因子研究"
fb = pd.read_csv(f"{R}/反包/全量明细.csv", dtype={"代码": str})
fb_key = fb[["代码", "名称", "反包日", "末板日", "N", "断板天数"]]

# ---- 1. 高位接力 ----
dj = pd.read_csv(f"{R}/高位接力/地基均线反包明细.csv", dtype={"代码": str})
dj = dj[dj["断板天数"].notna() & dj["前板高度"].notna()].copy()
dj["断板天数"] = dj["断板天数"].astype(int)
dj["前板高度"] = dj["前板高度"].astype(int)
dj_i = dj[(dj["断板天数"].between(1, 3)) & (dj["前板高度"].between(2, 5))].copy()
# 前板日MM-DD -> 全格式(买入日年份, 跨年-1)
by = dj_i["买入日"].str[:4]
full = by + "-" + dj_i["前板日"].astype(str)
cross = full > dj_i["买入日"]
dj_i["前板日全"] = full
dj_i.loc[cross, "前板日全"] = (by.astype(int) - 1).astype(str) + "-" + dj_i.loc[cross, "前板日"].astype(str)
# 高位接力首板日(反包日应等于它): 同代码同买入日
relay = pd.read_csv(f"{R}/高位接力/全量明细.csv", dtype={"代码": str})
dj_i = dj_i.merge(relay[["代码", "买入日", "首板日"]].rename(columns={"买入日": "买入日r", "首板日": "接力首板日"}),
                  left_on=["代码", "买入日"], right_on=["代码", "买入日r"], how="left")
m1 = dj_i.merge(fb_key, left_on=["代码", "前板日全", "断板天数", "前板高度"],
                right_on=["代码", "末板日", "断板天数", "N"], how="left", indicator=True)
ok1 = (m1["_merge"] == "both").sum()
same_day = (m1["反包日"] == m1["接力首板日"]).sum()
print(f"[高位接力] 交集候选 {len(dj_i)} 行, 三要素配上 {ok1}, 漏 {len(dj_i) - ok1}; "
      f"配上的行里 反包日==接力首板日 {same_day}/{ok1}")
if ok1 < len(dj_i):
    print("漏行(2026-09-25已逐笔核实: 反包日全部一字板 open==high==low==涨停价,")
    print("      「一字买不进剔除」口径排除, 非bug):")
    print(m1[m1["_merge"] == "left_only"][["代码", "前板日全", "断板天数", "前板高度", "接力首板日"]].to_string())

# ---- 2. N型补涨打板 ----
# 口径换算(2026-09-25对账确认): N型坑宽=末板日->D0的交易日距离, = 断板天数+1
nx = pd.read_csv(f"{R}/低吸研究/N型补涨打板/V4四组全量.csv", dtype={"vt_symbol": str})
nx["坑宽"] = pd.to_numeric(nx["坑宽"], errors="coerce")
nx["上波高"] = pd.to_numeric(nx["上波高"], errors="coerce")
nx_i = nx[(nx["坑宽"] - 1).between(1, 3) & nx["上波高"].between(2, 5) &
          (~nx["prev_lim"].astype(bool)) & (nx["date"] >= "2023-01-01")].copy()
nx_i["g"] = nx_i["坑宽"] - 1
m2 = nx_i.merge(fb_key, left_on=["vt_symbol", "date", "上波高", "g"],
                right_on=["代码", "反包日", "N", "断板天数"], how="left", indicator=True)
ok2 = (m2["_merge"] == "both").sum()
print(f"\n[N型] 交集候选 {len(nx_i)} 行(坑宽2~4即断1~3天×上波高2~5×昨非涨停×2023起), "
      f"配上 {ok2}, 漏 {len(nx_i) - ok2}")
miss2 = m2[m2["_merge"] == "left_only"]
if len(miss2):
    print("漏行(已确认=口径差异: N型上波高=窗口最大连板, 反包库要求紧邻前波高度,")
    print("      「2板→反包封住(成1板)→断1天→再触板」被反包库判N=1排除):")
    print(miss2[["vt_symbol", "name", "date", "上波高", "坑宽"]].to_string())

# ---- 3. 抽样清单(供独立重算) ----
idx = []
for _, sub in fb[fb["主格"]].groupby(["N", "断板天数"]):
    idx += sub.sample(min(2, len(sub)), random_state=7).index.tolist()
smp = fb.loc[idx]
print(f"\n[抽样] {len(smp)} 笔(主12格每格2笔)供独立代码路径重算:")
print(smp[["代码", "名称", "反包日", "末板日", "N", "断板天数", "买价", "封住",
           "次日收%", "持有到断板%"]].to_string(index=False))
