# -*- coding: utf-8 -*-
"""U型补涨打板(原趋势弱转强V4, 2026-08-30主人定调更名+按四组重组, 层编号退役):
只做 2板(前20日连板=2) 与 4+(前20日连板>=4), 各拆阴/阳 四组.
买点=断板后再启动的首个涨停板板上买(D0盘中触板买涨停价, 一字买不进排除) → 算打板;
形态内核=上波连板后的U型洗盘坑(无U/U坑内/U突破三状态) → 故名 U型补涨打板.

V4四组条件(主人2026-08-29定稿 + 全组「昨日未涨停」保险; 2板窗口10→20日, 对照实验定稿;
             2026-08-30 窗口扫描复核(w2s_diag_mxwin.py): 20日即合适, 15/25/30均不更优):
  2板补涨阴 c4a: 前20日连板=2 + 昨收阴 + 昨涨跌幅>-9% + 昨上影线<4% + 昨日未涨停
  2板补涨阳 c4b: 前20日连板=2 + 昨收阳 + 昨涨跌幅>-3% + 昨上影线<4% + 昨日未涨停
  4+补涨阴  c4c: 前20日连板>=4 + 昨收阴 + 昨涨跌幅>-8% + 昨上影线<4% + 昨日未涨停
  4+补涨阳  c4d: 前20日连板>=4 + 昨收阳 + 昨涨跌幅>-3% + 昨上影线<4% + 昨日未涨停
  连板=2 语义 = 截至昨日窗口内最大连板数恰为2(既有2连板且无3+连板) → 3板被结构性排除.
  2板窗口10→20日依据(w2s_v4_win20.py): 阴+0.24→+0.47/阳+0.57→+0.53, 新增层分年全正.
为何必须加「昨日未涨停」(w2s_diag_v4.py 全量证据, 2026-08-29):
  阳线组「昨幅>-3%」不排昨涨停 → 混入1633/898笔(昨孤立夹板/昨连板中继追板),
  真实板留 -0.68%/-1.04% 全负 差票65%; build_base对中继票封板存活炸板drop →
  存活偏差曾假显示+1.97%. 阴线组昨收阴天然无混入, 显式加做口径保险(同V3终版).
执行与地基口径同V3: D0盘中触板买涨停价, 排一字; 板留断走; 地基=classify_base(最近≥2板段).

任务:
  ① 五组(780簇)覆盖验证: 波首板日四组并集命中(全体/非首波两口径 + 未覆盖原因)
  ② 好差票验证md: 组/年月 分文件, 表含地基 + V3五组归属
  ③ 年月×组×地基 收益/胜率矩阵
输出: 容器 /app/w2s_v4_out/ (docker cp 回 U型补涨打板/)
"""
import os
import sys

sys.path.insert(0, "/app")
import numpy as np
import pandas as pd
import w2s_v3_wave_research as w
from w2s_base_type import add_outcome, build_base, BASE_NAME, BASE_ORDER

pd.set_option("display.width", 400)

GROUPS = [("2板补涨阴", "c4a"), ("2板补涨阳", "c4b"),
          ("4板补涨阴", "c4c"), ("4板补涨阳", "c4d")]
OUT = "/app/w2s_v4_out"

# 地基纯中文名(主人要求不用英文缩写; U/V/L型为形状描述保留)
BASE_CN = {"HIGH": "新高贴顶", "FLAT": "横盘平台", "U": "U型蹲", "V": "V末反",
           "MID": "中位浅调", "LB": "L趴底", "DN": "阴跌到点"}
# 白名单四组定稿(2026-08-29 融合版主人拍板 → 2026-08-30 重组: 层编号退役按组管理;
#   伪U规则追补(易德龙个案→全量验证): 2板系加「断板期收盘价从未站回顶上方」,
#   2板阴 211→123笔 +3.00→+4.26 / 2板阳首阳 127→74笔 +1.55→+3.02 均分年全正;
#   4+方向相反(妖股曾收顶上+4.91是强势整理)不加;
#   4+阴再剔「中坑8~15%×已回顶」毒格(华电能源个案→三档分化验证, 7笔-1.98;
#   浅擦<8%回顶+5.70/深坑>15%回顶+7.37留) 34→27笔 +4.01→+5.56 逐年变厚):
#   2板阴  U坑内蹲类×弹回≤16%×坑宽6-15×未收顶上   123笔+4.26 分年全正
#   2板阳  通道一 阴跌到点坑底首阳×未收顶上        74笔+3.02 分年全正
#          通道二 蹲类坑中×均线纠缠×D-2<D-3且D-3非涨停 60笔+4.04 分年全正
#          (纠缠态加「下探中」主人猜想验证成立收编: 118→60笔 +2.96→+4.04, w2s_diag_d2d3.py)
#   4+阴   孤立板穿插×全多头+++×U坑存在×剔中坑回顶  27笔+5.56 胜率70% 分年全正
#   4+阳   2板小波穿插(夹层, 非夹层全维度全灭)      45笔+2.45(狙击格)
WHITELIST = {
    "2板补涨阴": [
        "U坑条件：昨收距上波顶>4%（人在坑里）；坑宽6~15天；弹回3%~16%（U坑右侧,已弹起未弹飞）",
        "伪U排除：断板期收盘价从未站回最后一次涨停日收盘价上方（站回过=高位震荡贴顶，非洗盘坑）",
        "（坑底票弹回<3%未启动、U突破票距顶-4%以内，均不选）",
    ],
    "2板补涨阳": [
        "U坑条件（两条通道都要）：昨收距上波顶>4%；且断板期收盘价从未站回顶上方（伪U排除）；",
        "通道一坑底：弹回<3%且最低收盘在最近3日（首阳）；",
        "通道二坑中：弹回3%~16% + 均线纠缠态（5/10与10/20日线上下相反，此通道未收顶上可放宽）",
        " + 坑里还在下探（前日收盘低于3日前收盘）且3日前未涨停（回调已够3天，非刚从末板下来）",
    ],
    "4板补涨阴": [
        "U坑条件：断板期曾跌出距顶>4%的U（U坑存在；无U持续新高的不选；U坑内/U突破都接受）",
        " + 断板期出现过1~2个孤立涨停（再启动迹象）",
        "均线条件：5>10>20>30日线全多头（强势整理）",
        "排除：坑深8%~15%且昨收已爬回顶上（距顶4%以内）=半伤硬拉回顶、二次出货顶"
        "（7笔-1.98毒格；浅擦<8%回顶=强势、深坑>15%回顶=真二波，都留）",
    ],
    "4板补涨阳": [
        "U坑条件：大波之后出现过一段完整2板小波再整理（夹层，人工确认；非夹层全维度全灭不出手）",
    ],
}


def sandwich_of(seg_h, n_lim_mid):
    """夹层结构标签(4+组档位维度)."""
    if seg_h == 2:
        return "2板小波穿插"
    if seg_h == 3:
        return "3板小波穿插"
    if seg_h == seg_h and n_lim_mid == n_lim_mid and 1 <= n_lim_mid <= 2:
        return "孤立板穿插"
    return "无穿插"


def pos_of(low_dd, pull):
    """U三状态: 无U(断板期最低收盘也在顶上方=一直新高没洗盘) / U突破(跌过坑又爬回顶上=起二波)
    / U坑内(U进行时=买点区)."""
    if low_dd == low_dd and low_dd > -0.04:
        return "无U"
    if pull == pull and pull > -0.04:
        return "U突破"
    return "U坑内"


def tier_of(grp, base, seg_h=99, n_lim_mid=0, reb=0.0, gap=99, st="", dd=0.0, topped=True,
            pu=-9.0, d23ok=True):
    """四组出手判定 → (是否出手, 命中通道标签). st=均线排列态, gap=断板天数, dd=坑深, pu=昨收距顶,
    topped=断板期曾收在顶上方(伪U, 2板系要求 topped=False; 4+不用),
    d23ok=D-2收<D-3收且D-3非涨停(2板阳通道二要求; 其余组不查)."""
    tangle = st in ("-++", "+--")
    if grp == "2板补涨阴":
        if base in ("U", "MID", "FLAT", "V", "LB") and not topped:
            fly = reb == reb and reb > 0.16
            if not fly and 6 <= gap <= 15:
                return True, "U坑"
        return False, ""
    if grp == "2板补涨阳":
        if base == "DN" and not topped:
            return True, "坑底首阳"
        if base in ("U", "MID", "FLAT", "V", "LB") and tangle and d23ok:
            return True, "坑中纠缠"
        return False, ""
    if grp == "4板补涨阴":
        # 2026-08-30 两条追补: ①U坑存在(无U新高票-2.12毒) ②剔中坑8~15%×已回顶
        #   (半伤硬拉回顶=二次出货顶, 7笔-1.98毒格; 34→27笔 +4.01→+5.56 逐年变厚)
        toxic = pu == pu and pu > -0.04 and dd == dd and -0.15 < dd <= -0.08
        if (sandwich_of(seg_h, n_lim_mid) == "孤立板穿插" and st == "+++"
                and dd == dd and dd <= -0.04 and not toxic):
            return True, "孤板×多头"
        return False, ""
    if sandwich_of(seg_h, n_lim_mid) == "2板小波穿插":   # 4板补涨阳
        return True, "夹层"
    return False, ""


def describe_row(r):
    """每行形态人话解读（主人：数值看不懂，要文字描述）. 出手/未出手理由由 fail_reasons 给."""
    dd, pu, rb, gp, st = r["low_dd"], r["pull"], r["reb"], r["gap"], r["ma_st"]
    pos, sw = r["位置"], r["夹层"]
    parts = [f"上波{r['seg_h']:.0f}板"]
    if r["grp"].startswith("4板"):
        parts = [f"大波4+后·最近段{r['seg_h']:.0f}板"]
    if pos == "无U":
        parts.append("断板后一直在顶上新高、没洗过盘")
    elif pos == "U突破":
        parts.append(f"U坑{-dd * 100:.0f}%、已爬回顶上（突破起二波）")
    else:
        parts.append(f"跌{-dd * 100:.0f}%深坑、蹲{gp:.0f}天")
        if rb == rb:
            if rb < 0.03:
                parts.append("贴坑底还没弹")
            elif rb <= 0.16:
                parts.append(f"坑底弹起{rb * 100:.0f}%")
            else:
                parts.append(f"已弹飞{rb * 100:.0f}%")
    parts.append(f"昨收{'阴' if '阴' in r['grp'] else '阳'}（{r['p_chg'] * 100:+.1f}%）")
    if r["topped"]:
        parts.append("断板期曾收回顶上")
    if st:
        parts.append("均线" + {"+++": "全多头", "---": "全空", "-++": "纠缠·短压中多",
                               "+--": "纠缠·短修中空"}.get(st, st))
    if r["grp"].startswith("4板"):
        if sw == "2板小波穿插":
            parts.append("最近段即2板小波穿插")
        elif sw == "孤立板穿插":
            parts.append("大波断板期有孤立板")
    return "·".join(parts)


def fail_reasons(r):
    """未命中时给出卡在哪条（与 tier_of 四组口径一致）."""
    g, base = r["grp"], r["base"]
    dd, rb, gp, st = r["low_dd"], r["reb"], r["gap"], r["ma_st"]
    pu = r["pull"]
    pos, sw = r["位置"], r["夹层"]
    out = []
    if g == "2板补涨阴":
        if pos == "无U":
            out.append("无U新高票不进体系（没洗过盘）")
        elif pos == "U突破":
            out.append("已U突破贴顶（U已走完）")
        elif base == "DN":
            out.append("阴跌到点贴坑底没弹、未启动")
        elif r["topped"]:
            out.append("断板期曾收回顶上方（高位震荡伪U、非洗盘坑）")
        else:
            if rb == rb and rb > 0.16:
                out.append(f"弹回{rb * 100:.0f}%超16%已弹飞")
            if not (6 <= gp <= 15):
                out.append(f"坑宽{gp:.0f}天不在6~15")
    elif g == "2板补涨阳":
        if pos == "无U":
            out.append("无U新高票不进体系（没洗过盘）")
        elif pos == "U突破":
            out.append("已U突破贴顶（U已走完）")
        elif base == "DN" and r["topped"]:
            out.append("断板期曾收回顶上方（高位震荡伪U、非洗盘坑）")
        elif st not in ("-++", "+--"):
            out.append("均线非纠缠态")
        elif not r["d23ok"]:
            out.append("坑里已走平或回调不足3天（前日收盘未低于3日前，或3日前是涨停末板）")
    elif g == "4板补涨阴":
        if not (dd == dd and dd <= -0.04):
            out.append("无U没洗过盘")
        elif -0.15 < dd <= -0.08 and pu == pu and pu > -0.04:
            out.append("坑深8~15%又爬回顶上（半伤硬拉二次出货顶）")
        if sw != "孤立板穿插":
            out.append("断板期无孤立板穿插")
        if st != "+++":
            out.append("均线非全多头")
    elif sw != "2板小波穿插":
        out.append("无2板小波穿插")
    return out or ["条件不齐"]


def v3_group_map(clusters, waves):
    """cluster_id → 五组分类; (sid, first_pos, last_pos) 区间 → 查归属用."""
    cg = w.assign_groups(clusters, waves)
    gmap = dict(zip(cg["cluster_id"], cg["group"]))
    seg = waves[["sid", "cluster_id", "wave_no", "first_pos", "last_pos"]].copy()
    return gmap, seg


def attach_v3grp(tg, seg, gmap):
    """触发笔 D0 落在哪个波的区间内 → 簇五组归属(多出票=空)."""
    seg_by = {sid: grp[["first_pos", "last_pos", "cluster_id"]].to_numpy()
              for sid, grp in seg.groupby("sid", sort=False)}
    out = []
    for s, p in zip(tg["sid"], tg["pos"]):
        arr = seg_by.get(int(s))
        lab = ""
        if arr is not None:
            li = arr[:, 0].searchsorted(int(p), side="right")
            if li > 0 and int(p) <= arr[li - 1, 1]:
                lab = gmap.get(int(arr[li - 1, 2]), "")
        out.append(lab)
    tg["v3grp"] = [x[:2] if x else "" for x in out]
    return tg


def main():
    bars, segs, clusters, waves, bounds = w.load_all()
    w._ths_daily(bars)
    g = bars.groupby("sid", sort=False)
    stk = bars["streak"].astype(float)
    bars["mx10"] = stk.groupby(bars["sid"], sort=False).transform(
        lambda s: s.shift(1).rolling(10, min_periods=1).max())
    bars["n1_lim"] = g["is_lim"].shift(-1).fillna(False).astype(bool)
    # 均线排列态 ma_st(D-1口径, 融合五层用): 5/10/20/30日线相对位置符号串, 如"+++"
    for n in (5, 10, 20, 30):
        bars[f"ma{n}"] = g["close_price"].transform(
            lambda s, n=n: s.rolling(n, min_periods=n).mean().shift(1))
    ok = bars[["ma5", "ma10", "ma20", "ma30"]].notna().all(axis=1)
    bars["ma_st"] = ""
    bars.loc[ok, "ma_st"] = (
        np.where(bars.loc[ok, "ma5"] > bars.loc[ok, "ma10"], "+", "-")
        + np.where(bars.loc[ok, "ma10"] > bars.loc[ok, "ma20"], "+", "-")
        + np.where(bars.loc[ok, "ma20"] > bars.loc[ok, "ma30"], "+", "-"))
    mkt = bars.groupby("trade_date")["is_lim"].sum().rename("mkt_lim").reset_index()
    mkt["mkt_prev"] = mkt["mkt_lim"].shift(1)
    bars = bars.merge(mkt, on="trade_date", how="left")

    # ── V4四组(全组加~prev_lim保险; 2板=前20日恰2板, 证据见模块docstring) ──
    bars["c4a"] = (bars["mx20"] == 2) & bars["p_yin"] & (bars["p_chg"] > -0.09) \
        & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]
    bars["c4b"] = (bars["mx20"] == 2) & bars["p_yang"] & (bars["p_chg"] > -0.03) \
        & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]
    bars["c4c"] = (bars["mx20"] >= 4) & bars["p_yin"] & (bars["p_chg"] > -0.08) \
        & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]
    bars["c4d"] = (bars["mx20"] >= 4) & bars["p_yang"] & (bars["p_chg"] > -0.03) \
        & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]
    for _, c in GROUPS:
        bars[c] = bars[c].fillna(False).astype(bool)
    # 字面版(无~prev_lim)四列, 仅供混入规模对照
    bars["lit_c4a"] = (bars["mx20"] == 2) & bars["p_yin"] & (bars["p_chg"] > -0.09) & (bars["p_ush"] < 0.04)
    bars["lit_c4b"] = (bars["mx20"] == 2) & bars["p_yang"] & (bars["p_chg"] > -0.03) & (bars["p_ush"] < 0.04)
    bars["lit_c4c"] = (bars["mx20"] >= 4) & bars["p_yin"] & (bars["p_chg"] > -0.08) & (bars["p_ush"] < 0.04)
    bars["lit_c4d"] = (bars["mx20"] >= 4) & bars["p_yang"] & (bars["p_chg"] > -0.03) & (bars["p_ush"] < 0.04)
    for c in ("lit_c4a", "lit_c4b", "lit_c4c", "lit_c4d"):
        bars[c] = bars[c].fillna(False).astype(bool)

    gmap, seg = v3_group_map(clusters, waves)
    wave_keys = set(zip(waves["sid"], waves["first_pos"]))

    # ══ ① 五组覆盖验证 ══
    print("=" * 96)
    print("== ① 覆盖验证: V3五组 波首板日 → V4四组并集命中 ==")
    need = [c for _, c in GROUPS] + ["mx10", "mx20", "p_yin", "p_yang", "p_ush", "p_chg", "d0_open_lim"]
    wv = waves.merge(bars[["sid", "pos"] + need], left_on=["sid", "first_pos"],
                     right_on=["sid", "pos"], how="left")
    wv["cov4"] = wv[[c for _, c in GROUPS]].any(axis=1)
    wv["grp5"] = wv["cluster_id"].map(gmap)
    cl_cov = wv.groupby("cluster_id")["cov4"].any()
    cl_grp = pd.Series({cid: gmap[cid] for cid in wv["cluster_id"].unique()})

    def _cov_tab(d, label):
        n_all = len(d)
        hit = int(d["cov4"].sum())
        print(f"\n[{label}] 波 {n_all} 个: 并集命中 {hit} ({hit / n_all * 100:.0f}%) "
              f"其中一字买不进 {int(d[d['cov4']]['d0_open_lim'].sum())}")
        t = d.groupby("grp5").apply(lambda s: pd.Series({
            "波数": len(s), "命中": int(s["cov4"].sum()),
            "覆盖率%": round(s["cov4"].mean() * 100),
            "一字": int(s[s["cov4"]]["d0_open_lim"].sum())}), include_groups=False)
        print(t.to_string())

    _cov_tab(wv, "全体波")
    _cov_tab(wv[wv["wave_no"] > 1], "非首波")
    cc = pd.DataFrame({"命中": cl_cov})
    cc["grp5"] = cl_grp
    t = cc.groupby("grp5").apply(lambda s: pd.Series({
        "簇数": len(s), "命中": int(s["命中"].sum()),
        "簇覆盖%": round(s["命中"].mean() * 100)}), include_groups=False)
    print(f"\n[簇级] 780簇 任一波命中:")
    print(t.to_string())
    print(f"簇级合计: {int(cl_cov.sum())}/{len(cl_cov)} ({cl_cov.mean() * 100:.0f}%)")

    # 分组命中结构: 各V4组分别覆盖哪五组
    print("\n各V4组 × 五组(波级命中数):")
    hit_t = wv.groupby("grp5").apply(lambda s: pd.Series(
        {n: int(s[c].sum()) for n, c in GROUPS} | {"波数": len(s)}), include_groups=False)
    print(hit_t.to_string())

    # 未覆盖原因(非首波)
    unc = wv[(wv["wave_no"] > 1) & ~wv["cov4"]].copy()
    if len(unc):
        print(f"\n非首波未覆盖 {len(unc)} 波, 卡在哪条(非互斥):")
        d2 = unc["mx10"] != 2
        d4 = unc["mx20"] < 4
        print(f"  高度不匹配(既非前10日连板=2 也非前20日连板>=4): {int((d2 & d4).sum())}")
        print(f"    其中 前10日连板=1(断板>10日窗未罩住): {int((unc['mx10'] == 1).sum())} | "
              f"前10日连板>=3: {int((unc['mx10'] >= 3).sum())} | 前20日3板(不上不下): "
              f"{int(((unc['mx20'] == 3) & (unc['mx10'] < 3)).sum())}")
        print(f"  昨日平盘(非阴非阳): {int((~unc['p_yin'] & ~unc['p_yang']).sum())}")
        yin_ok = unc["p_yin"] & (d2 == False)
        print(f"  阴线侧缺件: 昨幅<=-9% {int((unc['p_yin'] & (unc['p_chg'] <= -0.09) & (unc['mx10'] == 2)).sum())} | "
              f"上影>=4% {int((unc['p_yin'] & (unc['p_ush'] >= 0.04) & (unc['mx10'] == 2)).sum())}")
        print(f"  阳线侧缺件: 昨幅<=-3%(深假阳) {int((unc['p_yang'] & (unc['p_chg'] <= -0.03) & (unc['mx10'] == 2)).sum())} | "
              f"上影>=4% {int((unc['p_yang'] & (unc['p_ush'] >= 0.04) & (unc['mx10'] == 2)).sum())}")

    # ══ ②③ 四组触发回测 + 地基 ══
    print("\n" + "=" * 96)
    print("== ② 四组全市场触发回测(D0触板买涨停价, 排一字; 均值/中位) ==")
    # 断板期曾收顶上判定用(伪U规则, 2026-08-30追补): 锚=昨日前最后一次涨停日
    cl_by = {sid: grp["close_price"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
    zt_by = {sid: grp["is_lim"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
    p2i = {sid: {int(p): i for i, p in enumerate(grp["pos"])}
           for sid, grp in bars.groupby("sid", sort=False)}

    def topped_of(sid, pos):
        """断板期内是否有收盘价 >= 最后一次涨停日收盘价(站回过顶上方)."""
        i = p2i[int(sid)][int(pos)]
        c, zt = cl_by[int(sid)], zt_by[int(sid)]
        j = i - 1
        while j >= 0 and not zt[j]:
            j -= 1
        if j < 0:
            return False
        return bool((c[j + 1:i] >= c[j]).any())

    def d23_of(sid, pos):
        """→ (D-2收<D-3收, D-3是否涨停=末尾板), i<4数据不足返回 (None,None)按不通过."""
        i = p2i[int(sid)][int(pos)]
        if i < 4:
            return None, None
        return cl_by[int(sid)][i - 2] < cl_by[int(sid)][i - 3], bool(zt_by[int(sid)][i - 3])

    # 4+夹层票锚修正(2026-08-30体检发现): 最近段=2/3板小波时, build_base的坑深/位置是相对
    # 小波顶算的 → 大波深坑漏算被误判「无U」(实测32笔夹层票+5.20). 重算为相对大波(≥4段)顶.
    # 只影响展示列与位置分类, 不动出手逻辑(层③要求seg_h>=4锚本就=大波; 层④只看seg_h==2).
    big4_by = {sid: grp[["last_pos", "high_price"]].to_numpy()
               for sid, grp in segs[segs["height"] >= 4].groupby("sid", sort=False)}

    def bigtop_fix(tg):
        m = tg.index[tg["seg_h"] < 4]
        for ix in m:
            r = tg.loc[ix]
            sid, pos = int(r["sid"]), int(r["pos"])
            arr = big4_by.get(sid)
            if arr is None:
                continue
            li = arr[:, 0].searchsorted(pos, side="left")
            if li == 0:
                continue
            lp2, ph2 = int(arr[li - 1, 0]), float(arr[li - 1, 1])
            i = p2i[sid][pos]
            mid = cl_by[sid][lp2 + 1:i]
            if not len(mid):
                continue
            low = mid.min()
            tg.loc[ix, "low_dd"] = low / ph2 - 1
            tg.loc[ix, "pull"] = r["prev_close"] / ph2 - 1
            tg.loc[ix, "reb"] = r["prev_close"] / low - 1
            tg.loc[ix, "gap"] = pos - lp2

    all_t = []
    for name, c in GROUPS:
        tg, drop = build_base(bars, segs, conds=(c,))
        tg = add_outcome(tg, bars)
        tg = attach_v3grp(tg, seg, gmap)
        tg["ym"] = tg["trade_date"].dt.strftime("%Y-%m")
        tg["date"] = tg["trade_date"].dt.strftime("%Y-%m-%d")
        tg["grp"] = name
        tg["topped"] = [topped_of(s, p) for s, p in zip(tg["sid"], tg["pos"])]
        r23 = [d23_of(s, p) for s, p in zip(tg["sid"], tg["pos"])]
        tg["d23ok"] = [(a is True) and (b is False) for a, b in r23]
        if name.startswith("4板"):
            bigtop_fix(tg)
        tg["is_wv"] = [(s, p) in wave_keys for s, p in zip(tg["sid"], tg["pos"])]
        # 好差票判定按实际盈亏(主人定调 2026-08-30): 差票=D+1收盘亏(炸板后次日收复也算好)
        tg["bad"] = tg["r_d1c"] <= 0
        all_t.append(tg)
        n_pl = int(tg["prev_lim"].sum())
        print(f"\n── {name} ── 触发 {len(tg)} 笔 (丢地基 {drop}) | 差票率 {tg['bad'].mean() * 100:.0f}% | "
              f"封板 {tg['is_lim'].mean() * 100:.0f}% 连板 {(tg['res'] == '连板').mean() * 100:.0f}%")
        print(f"  D1收: 均 {tg['r_d1c'].mean() * 100:+.2f}% 中位 {tg['r_d1c'].median() * 100:+.2f}% "
              f"胜率 {(tg['r_d1c'] > 0).mean() * 100:.0f}%")
        print(f"  板留: 均 {tg['r_bh'].mean() * 100:+.2f}% 中位 {tg['r_bh'].median() * 100:+.2f}% "
              f"胜率 {(tg['r_bh'] > 0).mean() * 100:.0f}%")
        for yy in (2023, 2024, 2025, 2026):
            sy = tg[tg["trade_date"].dt.year == yy]
            if len(sy):
                print(f"  {yy}: n={len(sy)} 板留均 {sy['r_bh'].mean() * 100:+.2f}% "
                      f"中位 {sy['r_bh'].median() * 100:+.2f}% 差票 {sy['bad'].mean() * 100:.0f}%")
        print(f"  地基分布: " + " ".join(
            f"{b}:{len(tg[tg['base'] == b])}" for b in BASE_ORDER if (tg["base"] == b).any()))
        print(f"  seg_h分布: " + " ".join(
            f"{h:.0f}板:{n}" for h, n in tg["seg_h"].value_counts().sort_index().items()))
        print(f"  V3五组归属: " + " ".join(
            f"{k}:{v}" for k, v in tg["v3grp"].value_counts().sort_index().items() if k))
        # 字面版(不加~prev_lim)混入规模: 混入票真实板留-0.68%~-1.04%全负(w2s_diag_v4.py)
        n_mix = int((bars["lit_" + c] & bars["prev_lim"]
                     & bars["touch"] & ~bars["d0_open_lim"]
                     & bars["n1_close"].notna() & bars["n1_open"].notna()).sum())
        if n_mix:
            print(f"  [对照] 已排除昨日涨停混入 {n_mix} 笔 (真实板留全负, 见docstring)")
        # 四组出手口径: 出手 / 未命中 两档统计 + 命中通道
        _res = [tier_of(name, b, h, nm, rb, gp, ms, dd, tp, pu, d23)
                for b, h, nm, rb, gp, ms, dd, tp, pu, d23
                in zip(tg["base"], tg["seg_h"], tg["n_lim_mid"], tg["reb"],
                       tg["gap"], tg["ma_st"], tg["low_dd"], tg["topped"], tg["pull"],
                       tg["d23ok"])]
        tg["档位"] = ["出手" if ok else "未命中" for ok, _ in _res]
        tg["通道"] = [ch for _, ch in _res]
        for tier in ("出手", "未命中"):
            s = tg[tg["档位"] == tier]
            if not len(s):
                continue
            yr = " / ".join(f"{sy['r_bh'].mean() * 100:+.2f}" for yy in (2023, 2024, 2025, 2026)
                            if len(sy := s[s["trade_date"].dt.year == yy]))
            print(f"  [{tier}] n={len(s)} 板留均 {s['r_bh'].mean() * 100:+.2f} "
                  f"中位 {s['r_bh'].median() * 100:+.2f} 胜率 {(s['r_bh'] > 0).mean() * 100:.0f}% "
                  f"差票 {s['bad'].mean() * 100:.0f}% 连板 {(s['res'] == '连板').mean() * 100:.0f}% "
                  f"| 分年 {yr}")
    t = pd.concat(all_t, ignore_index=True)

    # 地基 × 组 总表
    print("\n== ③ 地基 × 组 (板留均/差票率/连板率) ==")
    gt = t.groupby(["grp", "base"]).apply(lambda s: pd.Series({
        "n": len(s), "板留均": round(s["r_bh"].mean() * 100, 2),
        "板留中位": round(s["r_bh"].median() * 100, 2),
        "差票%": round(s["bad"].mean() * 100),
        "连板%": round((s["res"] == "连板").mean() * 100)}), include_groups=False)
    print(gt.reindex(pd.MultiIndex.from_product(
        [[n for n, _ in GROUPS], BASE_ORDER])).dropna(how="all").to_string())

    # ══ 文件输出 ══
    os.makedirs(OUT, exist_ok=True)
    # 全量csv(地基纯中文 + 档位列)
    if "档位" not in t.columns:
        _res = [tier_of(g, b, h, nm, rb, gp, ms, dd, tp, pu, d23)
                for g, b, h, nm, rb, gp, ms, dd, tp, pu, d23
                in zip(t["grp"], t["base"], t["seg_h"], t["n_lim_mid"], t["reb"],
                       t["gap"], t["ma_st"], t["low_dd"], t["topped"], t["pull"], t["d23ok"])]
        t["档位"] = ["出手" if ok else "未命中" for ok, _ in _res]
        t["通道"] = [ch for _, ch in _res]
    t["位置"] = [pos_of(dd, pu) for dd, pu in zip(t["low_dd"], t["pull"])]
    t["夹层"] = [sandwich_of(h, nm) for h, nm in zip(t["seg_h"], t["n_lim_mid"])]
    t.loc[~t["grp"].str.startswith("4板"), "夹层"] = ""
    t["出手"] = t["档位"] == "出手"
    cols = ["vt_symbol", "name", "date", "ym", "grp", "出手", "通道", "位置", "夹层", "topped", "res",
            "r_d1o", "r_d1c", "r_bh", "pull", "low_dd", "reb", "gap", "ma_st", "seg_h", "p_chg",
            "p_ush", "mkt_prev", "is_wv", "v3grp", "is_lim", "n1_lim", "prev_lim"]
    exp = t[cols].copy()
    for c in ("r_d1o", "r_d1c", "r_bh", "pull", "low_dd", "reb", "p_chg", "p_ush"):
        exp[c] = (exp[c] * 100).round(2)
    exp = exp.rename(columns={"r_d1o": "D1开%", "r_d1c": "D1收%", "r_bh": "板留%",
                              "pull": "距顶%", "low_dd": "坑深%", "reb": "弹回%",
                              "p_chg": "昨幅%", "p_ush": "昨上影%", "mkt_prev": "昨涨停家",
                              "seg_h": "上波高", "gap": "坑宽", "grp": "组",
                              "topped": "曾收顶上"})
    exp.to_csv(os.path.join(OUT, "V4四组全量.csv"), index=False, encoding="utf-8-sig")

    # 好差票md: 组/年月, 只分差票/好票两段; 每笔=文字小节(主人: 不要表格, 文字分组换行)
    def _block(r):
        hit = f"✅出手「{r['通道']}」" if r["档位"] == "出手" else "✘未出手"
        lines = [f"- **{r['vt_symbol']} {r['name']} · {r['date']} · {hit} · {r['res']}**",
                 f"  - 形态：{describe_row(r)}"]
        if r["档位"] != "出手":
            lines.append(f"  - 未出手原因：{'；'.join(fail_reasons(r))}")
        lines.append(f"  - 结果：D+1开盘 {r['r_d1o'] * 100:+.1f}%、收盘 {r['r_d1c'] * 100:+.1f}%"
                     f"；持有到首次断板 {r['r_bh'] * 100:+.1f}%")
        return lines

    for name, _ in GROUPS:
        gdir = os.path.join(OUT, "好差票验证", name)
        os.makedirs(gdir, exist_ok=True)
        for ym, sub in t[t["grp"] == name].groupby("ym"):
            # 主人定调: 库只留U形态; 但出手票永远列出(库是验证出手对不对的册子)——
            # 层④12笔无U夹层(+3.32胜率75%)=大波后高位横盘直接起小波的强势结构, 属U体系外例外
            nou = sub[(sub["位置"] == "无U") & (sub["档位"] != "出手")]
            sub = sub[(sub["位置"] != "无U") | (sub["档位"] == "出手")]
            if not len(sub):
                continue
            bad, good = sub[sub["bad"]], sub[~sub["bad"]]
            hit = sub[sub["档位"] == "出手"]
            lines = [f"# U型补涨打板 · {name} · {ym} · 好差票（U坑坐标）", "",
                     f"U形态 {len(sub)} 笔 | 差票 {len(bad)}（炸板 {int((sub['res'] == '炸板').sum())}"
                     f" + 封D1负 {int((sub['res'] == '封D1负').sum())}） | 好票 {len(good)}（连板 "
                     f"{int((sub['res'] == '连板').sum())}） | 差票率 {len(bad) / len(sub) * 100:.0f}%"
                     f" | ✅白名单出手 {len(hit)} 笔"
                     + (f"（板留均 {hit['r_bh'].mean() * 100:+.2f}% 差票 "
                        f"{hit['bad'].mean() * 100:.0f}%）" if len(hit) else "")
                     + (f" ｜ 另有无U票 {len(nou)} 笔未列入（均未出手，板留均 {nou['r_bh'].mean() * 100:+.2f}%"
                        f"——一直新高没洗盘）" if len(nou) else ""), "",
                     "**出手条件（U坑 + 均线）**"] \
                    + [f"- {line}" for line in WHITELIST[name]] \
                    + ["",
                     "**好差票判定**",
                     "- 本文件列当月全部触发票：好票/差票=事后结果，✅出手/✘未出手=白名单买不买；",
                     "  差票段的✘=拦对了（过滤器挡掉的坑），好票段的✘=漏掉的机会",
                     "- 买入口径：D0 盘中触及涨停价买入（板上买）；开盘即涨停（一字）买不进，剔除",
                     "- 差票：D+1 收盘价低于涨停买价（实亏才算差；炸板后次日收复的算好票）",
                     "- 好票：D+1 收盘不亏；「结果」列的炸板/封板/连板只是当日封板过程，不决定好差",
                     "- 持有到首次断板 = 按涨停价买入、首次断板日收盘卖出",
                     "",
                     "**形态解读口径**",
                     "- U三状态：跌X%深坑蹲N天=U坑内（买点区）；U坑X%已爬回顶上=U突破（起二波）；",
                     "  一直在顶上新高=无U（从未洗盘，2板系与4+阴不买；4+阳夹层结构例外，无U也列出）",
                     "- 弹回：昨收距坑底；<3%=贴坑底没弹（未启动），>16%=已弹飞（变相新高）",
                     "- 曾收顶上：断板期有收盘价站回过最后一次涨停日收盘价上方=高位震荡伪U"
                     "（2板系排除项；4+妖股相反，是强势整理）",
                     "- 均线：全多头=5>10>20>30日线；纠缠=短压中多（-++）或短修中空（+--）",
                     ""]
            for lab, pool, asc in (("差票", bad, True), ("好票", good, False)):
                if not len(pool):
                    continue
                lines += [f"## {lab} — {len(pool)} 笔"
                          + (f"（✅命中 {int((pool['档位'] == '出手').sum())}）"
                             if (pool["档位"] == "出手").any() else ""), ""]
                for _, r in pool.sort_values("r_d1c", ascending=asc).iterrows():
                    lines += _block(r)
                lines.append("")
            with open(os.path.join(gdir, f"{ym}.md"), "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        # _索引
        idx_rows = ["组,月,U形态,炸板,封D1负,好票,连板,差票率%"]
        gi = t[(t["grp"] == name) & (t["位置"] != "无U")]
        for ym, sub in gi.groupby("ym"):
            idx_rows.append(f"{name},{ym},{len(sub)},"
                            f"{int((sub['res'] == '炸板').sum())},{int((sub['res'] == '封D1负').sum())},"
                            f"{int((~sub['bad']).sum())},{int((sub['res'] == '连板').sum())},"
                            f"{round(sub['bad'].mean() * 100)}")
        with open(os.path.join(OUT, "好差票验证", f"_索引_{name}.csv"), "w", encoding="utf-8-sig") as f:
            f.write("\n".join(idx_rows) + "\n")

    # 年月×坑深矩阵md(U坑口径: 坑深档列 + 出手列)
    mdir = os.path.join(OUT, "汇总")
    os.makedirs(mdir, exist_ok=True)
    DD_LABS = ["浅坑<8%", "中坑8~15", "深坑15~25", "超深>25%", "U突破贴顶"]
    lines = ["# U型补涨打板四组 · 年月 × 坑深 · 收益/胜率矩阵（U坑口径）", "",
             "生成: w2s_v4_groups.py · 2026-08-30 · 板留%=板留断走均值(相对涨停价买入), "
             "单元格=n / 板留均 / 板留胜率。坑深=断板期最低收盘距上波顶；U突破贴顶=昨收距顶>-4%。"
             "出手列=四组白名单命中。", ""]
    for name, _ in GROUPS:
        sub = t[(t["grp"] == name) & (t["位置"] != "无U")].copy()   # 矩阵同库: 只留U形态
        dd = pd.cut(-sub["low_dd"], [0, 0.08, 0.15, 0.25, 99], labels=DD_LABS[:4])
        dd = dd.cat.add_categories(DD_LABS[4]).fillna(DD_LABS[4])
        sub["坑深档"] = dd
        wl_sub = sub[sub["出手"]]
        lines += [f"## {name} (全期 n={len(sub)}, 板留均 {sub['r_bh'].mean() * 100:+.2f}% | "
                  f"✅出手 n={len(wl_sub)}, 板留均 "
                  f"{wl_sub['r_bh'].mean() * 100:+.2f}%, 胜率 {(wl_sub['r_bh'] > 0).mean() * 100:.0f}%)", "",
                  "| 年月 | " + " | ".join(DD_LABS) + " | ✅出手 | 月计 |",
                  "|" + "---|" * (len(DD_LABS) + 3)]
        for ym, ms in sub.groupby("ym"):
            cells = []
            for lab in DD_LABS:
                s = ms[ms["坑深档"] == lab]
                cells.append(f"{len(s)}<br>{s['r_bh'].mean() * 100:+.2f}<br>"
                             f"{(s['r_bh'] > 0).mean() * 100:.0f}%" if len(s) else "")
            wlm = ms[ms["出手"]]
            wlcell = (f"{len(wlm)}<br>{wlm['r_bh'].mean() * 100:+.2f}<br>"
                      f"{(wlm['r_bh'] > 0).mean() * 100:.0f}%" if len(wlm) else "")
            lines.append(f"| {ym} | " + " | ".join(cells) + f" | {wlcell} "
                         + f"| {len(ms)}<br>{ms['r_bh'].mean() * 100:+.2f}<br>"
                           f"{(ms['r_bh'] > 0).mean() * 100:.0f}% |")
        lines.append("")
    # 组×年 汇总
    lines += ["# 组 × 年 汇总", "", "| 组 | 年 | n | 板留均 | 板留中位 | 板留胜率 | 差票率 | 连板率 |",
              "|---|---|---|---|---|---|---|---|"]
    for (name, yy), s in t.groupby([t["grp"], t["trade_date"].dt.year]):
        lines.append(f"| {name} | {yy} | {len(s)} | {s['r_bh'].mean() * 100:+.2f} "
                     f"| {s['r_bh'].median() * 100:+.2f} | {(s['r_bh'] > 0).mean() * 100:.0f}% "
                     f"| {s['bad'].mean() * 100:.0f}% | {(s['res'] == '连板').mean() * 100:.0f}% |")
    with open(os.path.join(mdir, "年月×坑深矩阵.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\n输出完成: {OUT}/ (V4四组全量.csv + 好差票验证/<组>/YYYY-MM.md + 汇总/年月×坑深矩阵.md)")


if __name__ == "__main__":
    main()
