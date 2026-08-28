# -*- coding: utf-8 -*-
"""趋势弱转强V3 —— 「≥2板断板 → 20交易日内再现≥2板」行情簇研究与波次切分事实源.

用法(容器内):
    python 量化因子研究/低吸研究/scripts/w2s_v3_wave_research.py explore      # 构建样本并打印总体统计
    python 量化因子研究/低吸研究/scripts/w2s_v3_wave_research.py export       # 按 规律组/YYYY-MM.csv 导出
    python 量化因子研究/低吸研究/scripts/w2s_v3_wave_research.py case 平潭发展 # 打印单票完整波次结构
    python 量化因子研究/低吸研究/scripts/w2s_v3_wave_research.py verify      # 两分法条件(快接/缓启)覆盖验证
    python 量化因子研究/低吸研究/scripts/w2s_v3_wave_research.py optimize    # 条件实走: 炸板/D+1收益分析+连板概率挖掘
    python 量化因子研究/低吸研究/scripts/w2s_v3_wave_research.py position    # 位置形态: 好票vs差票(前N日涨幅×均线×距高点)
    python 量化因子研究/低吸研究/scripts/w2s_v3_wave_research.py history    # 历史半年首板D+1溢价辅助因子
    python 量化因子研究/低吸研究/scripts/w2s_v3_wave_research.py deep       # 分情形微观形态: 快接/缓启专场
    python 量化因子研究/低吸研究/scripts/w2s_v3_wave_research.py between    # 簇波间条件触发的孤立单板负溢价
    python 量化因子研究/低吸研究/scripts/w2s_v3_wave_research.py ths        # 主人四组同花顺条件: 覆盖率+触发回测

口径(2026-08-27 定稿, 涨停判定与 w2s_replay.py v3.0 完全一致):
- 宇宙: 主板(非300/301/688/689/8xx/4xx/92x)/非ST非退(当前名判定) / pos>=5 才参与涨停判定
- 涨停: limit_price = round(prev_close*1.10+1e-9, 2), |close-limit|<=1e-6 即封板; 不复权
- 连板段(segment): 连续封板日为一段; height=段长(几连板);
  first_date=首板日(开启), confirm_date=第2板日(达成≥2板确认), last_date=末板日(结束)
- 波(wave): height>=2 的段
- 行情簇(cluster): 从某波起, 下一波首板日距上一波末板日 1~20 个交易日(即断板后第1~20个
  交易日内开启新一波)则链入同簇, 向后延伸至断口>20 止; 入选簇要求波数>=2.
  这正是『≥2板断板→后续20日内又出现≥2板』的簇级体现.
- 20日 = 交易日(pos差); 同时记录自然日天数备用.
- 诚实标注: 波末距该票数据末端<21交易日 → next_uncertain=True(可能还有未观测的下一波).
"""
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
pd.set_option("display.width", 320)
pd.set_option("display.max_columns", 160)

MAX_GAP_TB = 20          # 上波末板 → 下波首板的最大交易日数(1=断板次日直接再板)
MIN_POS_FOR_LIMIT = 5    # 与 w2s_replay 一致, 前5个交易日不做涨停判定


# ────────────────────────── 数据加载与连板段 ──────────────────────────

def _board_of(code6: str) -> str:
    if code6.startswith(("300", "301")):
        return "cyb"
    if code6.startswith(("688", "689")):
        return "kcb"
    if code6.startswith(("8", "4", "92")):
        return "bse"
    return "main"


def load_bars(eng) -> tuple[pd.DataFrame, dict]:
    """主板非ST宇宙全部日线 + 衍生列(is_lim/streak/pos); 返回 (bars, 数据边界信息)."""
    stocks = pd.read_sql("select vt_symbol, name from stocks", eng)
    stocks["code6"] = stocks["vt_symbol"].str[:6]
    stocks["board"] = stocks["code6"].map(_board_of)
    stocks["bad"] = stocks["name"].str.upper().str.contains("ST") | stocks["name"].str.contains("退")
    keep = stocks.loc[(stocks["board"] == "main") & (~stocks["bad"]), ["vt_symbol", "name"]]

    bars = pd.read_sql(
        "select vt_symbol, trade_date, open_price, high_price, low_price, close_price, "
        "volume, turnover_rate from stock_daily_bars",
        eng, parse_dates=["trade_date"])
    bars = bars.merge(keep, on="vt_symbol", how="inner")
    bars.sort_values(["vt_symbol", "trade_date"], inplace=True, ignore_index=True)

    bars["sid"], _ = pd.factorize(bars["vt_symbol"])
    g = bars.groupby("sid", sort=False)
    bars["prev_close"] = g["close_price"].shift(1)
    bars["pos"] = g.cumcount().astype("int32")
    lim_px = np.round(bars["prev_close"] * 1.10 + 1e-9, 2)
    elig = bars["prev_close"].notna() & (bars["prev_close"] > 0) & (bars["pos"] >= MIN_POS_FOR_LIMIT)
    bars["is_lim"] = elig & ((bars["close_price"] - lim_px).abs() <= 1e-6)
    brk = (~bars["is_lim"]).groupby(bars["sid"], sort=False).cumsum()
    bars["streak"] = bars["is_lim"].astype("int8").groupby([bars["sid"], brk], sort=False).cumsum()

    bounds = {
        "last_sid_pos": bars.groupby("sid")["pos"].max(),   # 该票数据末端 pos(退市/新截断诚实标注用)
        "global_last_date": bars["trade_date"].max(),
    }
    return bars, bounds


def extract_segments(bars: pd.DataFrame) -> pd.DataFrame:
    """每票每个连板段一行(含单板段, 单板段供波间特征统计), 已按 sid/日期排序."""
    s = bars[bars["is_lim"]].copy()
    new_seg = s["streak"] == 1
    s["seg_no"] = new_seg.groupby(s["sid"], sort=False).cumsum()
    segs = s.groupby(["sid", "seg_no"], sort=True).agg(
        code=("vt_symbol", "first"),
        first_date=("trade_date", "first"),
        confirm_date=("trade_date", lambda x: x.iloc[1] if len(x) > 1 else pd.NaT),
        last_date=("trade_date", "last"),
        first_pos=("pos", "first"),
        last_pos=("pos", "last"),
        height=("streak", "max"),
        start_open=("open_price", "first"),
        start_close=("close_price", "first"),
        end_close=("close_price", "last"),
        high_price=("high_price", "max"),
        low_price=("low_price", "min"),
    ).reset_index()
    return segs


# ────────────────────────── 行情簇构建 ──────────────────────────

def build_clusters(segs_all: pd.DataFrame, bars: pd.DataFrame, bounds: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """height>=2 的段为波, 距离 1~MAX_GAP_TB 链成簇; 返回 (clusters, waves).

    waves 行 = 波自身字段 + 与前一波间隔特征:
      gap_prev_tb/gap_prev_cal       上波末板→本波首板的交易日/自然日数
      between_low_dd%                波间最低价相对上波最高价的回撤%
      between_singles                波间出现的孤立单板块数
    """
    big = segs_all[segs_all["height"] >= 2].sort_values(["sid", "first_pos"]).reset_index(drop=True)
    single_keys = set(zip(segs_all.loc[segs_all["height"] == 1, "sid"],
                          segs_all.loc[segs_all["height"] == 1, "first_pos"].astype(int)))
    lows = bars.set_index(["sid", "pos"])["low_price"].sort_index()
    last_pos_by_sid = bounds["last_sid_pos"]

    cl_rows, wv_rows = [], []
    cid = 0
    for sid, grp in big.groupby("sid", sort=True):
        seg_list = grp.to_dict("records")
        chains: list[list[dict]] = [[seg_list[0]]]
        for prev, cur in zip(seg_list[:-1], seg_list[1:]):
            gap = int(cur["first_pos"] - prev["last_pos"])
            if 1 <= gap <= MAX_GAP_TB:
                chains[-1].append(cur)
            else:
                chains.append([cur])
        tail_pos = int(last_pos_by_sid.loc[sid])
        for ch in chains:
            if len(ch) < 2:
                continue
            cid += 1
            cl_rows.append({
                "cluster_id": cid,
                "sid": sid,
                "code": ch[0]["code"],
                "n_waves": len(ch),
                "anchor_month": ch[0]["first_date"].strftime("%Y-%m"),
                "start_date": ch[0]["first_date"],
                "end_date": ch[-1]["last_date"],
                # 末波之后再起新波的机会窗口已超出数据末端 → total_waves 未定(验算时可剔除)
                "next_uncertain": bool(tail_pos - ch[-1]["last_pos"] < MAX_GAP_TB + 1),
            })
            for i, w in enumerate(ch):
                row = dict(w)
                row["cluster_id"] = cid
                row["wave_no"] = i + 1
                if i == 0:
                    row.update(gap_prev_tb=np.nan, gap_prev_cal=np.nan,
                               between_low_dd=np.nan, between_singles=np.nan)
                else:
                    prev = ch[i - 1]
                    lo_slice = lows.loc[sid, prev["last_pos"]:w["first_pos"]]
                    row["gap_prev_tb"] = int(w["first_pos"] - prev["last_pos"])
                    row["gap_prev_cal"] = float((w["first_date"] - prev["last_date"]).days)
                    row["between_low_dd"] = round(
                        (lo_slice.min() / prev["high_price"] - 1) * 100, 2) if len(lo_slice) else np.nan
                    row["between_singles"] = sum(
                        1 for p in range(int(prev["last_pos"]) + 1, int(w["first_pos"]))
                        if (sid, p) in single_keys)
                wv_rows.append(row)
    return pd.DataFrame(cl_rows), pd.DataFrame(wv_rows)


def load_all(db_url: str | None = None, cache: bool = True):
    """全量构建; 结果 pickle 缓存到容器 /tmp 以便反复探索."""
    cache_path = "/tmp/w2s_v3_cache.pkl"
    if cache and os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            return tuple(pd.read_pickle(f))
    from sqlalchemy import create_engine
    eng = create_engine(db_url or os.environ["DATABASE_URL"])
    bars, bounds = load_bars(eng)
    segs = extract_segments(bars)
    clusters, waves = build_clusters(segs, bars, bounds)
    with open(cache_path, "wb") as f:
        pd.to_pickle([bars, segs, clusters, waves, bounds], f)
    return bars, segs, clusters, waves, bounds


# ────────────────────────── 探索性统计 ──────────────────────────

def assign_groups(clusters: pd.DataFrame, waves: pd.DataFrame) -> pd.DataFrame:
    """互斥全覆盖五组分类(围绕二波形态 + 总波数):

    01_双板往复_快速接续 : n_waves==2 & h1==h2==2 & 断板后≤5交易日即开新波
    02_双板往复_缓慢重启 : n_waves==2 & h1==h2==2 & 新波在6~20交易日才启动
    03_第二波升级        : n_waves==2 & h2>h1 (越战越勇)
    04_第二波衰减        : n_waves==2 & h2<h1 (一波见顶后的余威反抽)
    05_三波及以上_多轮博弈: n_waves>=3 (波次谱系见字段, 复杂结构不入前三组的简化池)
    """
    w1h = waves[waves["wave_no"] == 1].set_index("cluster_id")["height"]
    w2h = waves[waves["wave_no"] == 2].set_index("cluster_id")["height"]
    w2g = waves[waves["wave_no"] == 2].set_index("cluster_id")["gap_prev_tb"]
    c = clusters.copy()
    c["h1"] = c["cluster_id"].map(w1h)
    c["h2"] = c["cluster_id"].map(w2h)
    c["gap_w2"] = c["cluster_id"].map(w2g)

    def _grp(r):
        if r["n_waves"] >= 3:
            return "05_三波及以上_多轮博弈"
        if r["h1"] == r["h2"]:
            return "01_双板往复_快速接续" if r["gap_w2"] <= 5 else "02_双板往复_缓慢重启"
        return "03_第二波升级_高度超越" if r["h2"] > r["h1"] else "04_第二波衰减_余威反抽"

    c["group"] = c.apply(_grp, axis=1)
    return c


def cmd_explore():
    bars, segs, clusters, waves, bounds = load_all()
    print(f"宇宙日线 {len(bars):,} 行 | {len(bars['vt_symbol'].unique()):,} 只票 | "
          f"数据末端 {bounds['global_last_date'].date()} | 连板段 {len(segs):,} 个")
    big = segs[segs['height'] >= 2]
    print(f">=2板波 {len(big):,} 个 | 行情簇(≥2波) {len(clusters):,} 个")
    nxt = clusters["next_uncertain"]
    print(f"尾部不确定簇(next_uncertain) {int(nxt.sum())} 个")

    c = clusters.copy()
    c["anchor_year"] = c["anchor_month"].str[:4]
    print("\n== 按锚定年 × 波数 ==")
    piv = c.pivot_table(index="anchor_year", columns="n_waves", values="cluster_id",
                        aggfunc="count", fill_value=0)
    print(piv.to_string())

    print("\n== 第一波高度分布 ==")
    w1 = waves[waves["wave_no"] == 1]
    print(w1["height"].value_counts().sort_index().to_string())

    print("\n== 波间隔(交易日)分布 ==")
    g = waves[waves["wave_no"] > 1]["gap_prev_tb"]
    print(pd.cut(g, [0, 1, 2, 3, 5, 8, 10, 15, 20]).value_counts().sort_index().to_string())

    print("\n== 第二波相对第一波高度(w1h×w2h) ==")
    w2 = waves[waves["wave_no"] == 2][["cluster_id", "height"]].rename(columns={"height": "h2"})
    m = w1.merge(w2, on="cluster_id").rename(columns={"height": "h1"})
    print(pd.crosstab(m["h1"], m["h2"]).to_string())

    print("\n== 高度组合 top10 (w1h→w2h) ==")
    combo = m.groupby(["h1", "h2"]).size().sort_values(ascending=False).head(10)
    print(combo.to_string())

    # ── 结构性维度: 峰值波位置 / 二波是否创新高 / 波间洗盘深度 ──
    wh = waves[["cluster_id", "wave_no", "height"]].sort_values(["cluster_id", "wave_no"])
    first_max = wh.groupby("cluster_id").apply(
        lambda x: x.loc[x["height"].idxmax(), "wave_no"], include_groups=False)
    c = c.merge(first_max.rename("peak_wave"), left_on="cluster_id", right_index=True)
    print("\n== 峰值波位置(argmax高度取首个) × 总波数 ==")
    print(pd.crosstab(c["peak_wave"], c["n_waves"]).to_string())

    # 二波 confirm 收盘 是否越过一波最高价(新高行为)
    w2x = waves[waves["wave_no"] == 2][["cluster_id", "end_close", "start_open", "first_date"]]
    w1x = waves[waves["wave_no"] == 1][["cluster_id", "high_price", "end_close"]]
    mx = w1x.merge(w2x, on="cluster_id", suffixes=("_w1", "_w2"))
    h1col = "high_price_w1" if "high_price_w1" in mx.columns else "high_price"
    mx["brk_prev_high"] = mx["end_close_w2"] >= mx[h1col]
    print("\n== 二波末收盘 越过一波最高价占比 ==")
    print(f"{mx['brk_prev_high'].mean()*100:.1f}%  (n={len(mx)})")

    dd = waves[waves["wave_no"] > 1]
    print("\n== 波间洗盘回撤分布 %(相对上波最高价) ==")
    print(pd.cut(dd["between_low_dd"], [-99, -25, -15, -10, -5, -1, 0, 99]).value_counts().sort_index().to_string())
    print("\n== 波间含孤立单板块数分布 ==")
    print(dd["between_singles"].value_counts().sort_index().head(8).to_string())

    print("\n== gap(交易日) × 二波高度均值 ==")
    print(dd.groupby(pd.cut(dd["gap_prev_tb"], [0, 2, 5, 10, 20]), observed=True).agg(
        n=("height", "size"), avg_h=("height", "mean"),
        avg_dd=("between_low_dd", "mean")).round(2).to_string())

    # ── 分组草案规模核查 ──
    gc = assign_groups(c, waves)
    print("\n== 五组分组规模 ==")
    print(gc.groupby("group").agg(n=("cluster_id", "size")).to_string())
    print("\n== 组内代表样例(最近5例) ==")
    for gk, sub in gc.sort_values(["group", "start_date"]).groupby("group"):
        names = sub.merge(bars.drop_duplicates("sid")[["sid", "name"]], on="sid")
        tail = [f"{r['code']} {r['name']}({r['anchor_month']},{r['n_waves']}波,h{int(r['h1'])}→{int(r['h2'])})"
                for _, r in names.tail(5).iterrows()]
        print(f"{gk}: " + " | ".join(tail))


def cmd_case(name: str):
    bars, segs, clusters, waves, bounds = load_all()
    st = bars.drop_duplicates("sid")[["sid", "vt_symbol", "name"]]
    target = st[st["name"].astype(str).str.contains(name) | (st["vt_symbol"] == name)]
    if len(target) == 0:
        raise SystemExit(f"找不到股票: {name}")
    for _, r in target.iterrows():
        cs = clusters[(clusters["sid"] == r["sid"])]
        print(f"{r['vt_symbol']} {r['name']}: {len(cs)} 个行情簇")
        for _, c0 in cs.iterrows():
            w = waves[(waves["cluster_id"] == c0["cluster_id"])].sort_values("wave_no")
            show = w[["wave_no", "first_date", "confirm_date", "last_date", "height",
                      "gap_prev_tb", "gap_prev_cal", "between_low_dd", "between_singles"]]
            print(f"  簇#{c0['cluster_id']} {c0['n_waves']}波 "
                  f"[{c0['start_date'].date()} ~ {c0['end_date'].date()}]"
                  f"{' (next_uncertain)' if c0['next_uncertain'] else ''}")
            print(show.to_string(index=False))


def _fmt(v, nd=None):
    """markdown 单元格格式化: NaN/None → —."""
    if v is None or (isinstance(v, float) and pd.isna(v)) or v == "":
        return "—"
    if nd is not None and isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def _cluster_block(cid_row, w_rows, name_map) -> str:
    """单簇 markdown 小节: 标题行 + 当簇波次竖表."""
    cid = cid_row["cluster_id"]
    flag = " ⚠️next_uncertain" if bool(cid_row["next_uncertain"]) else ""
    lines = [
        f"### {_fmt(name_map.get(cid_row['sid']))} `{cid_row['code']}`"
        f"　{cid_row['n_waves']}波｜{_fmt(cid_row['start_date'].date())} ~ {_fmt(cid_row['end_date'].date())}"
        f"　· 峰值第{int(cid_row['peak_wave'])}波{flag}",
        "",
        "| 波 | 开启(首板) | 确认(二板) | 结束(末板) | 板数 | 距上波(交易日/自然日) | 波间最低回撤% | 波间孤立单板 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for w in w_rows.itertuples():
        k = int(w.wave_no)
        gap = "—" if k == 1 or pd.isna(w.gap_prev_tb) else f"{int(w.gap_prev_tb)} / {int(w.gap_prev_cal)}"
        lines.append(
            f"| {k} | {w.first_date.date()} "
            f"| {_fmt(pd.Timestamp(w.confirm_date).date() if pd.notna(w.confirm_date) else '')} "
            f"| {w.last_date.date()} | {int(w.height)} | {gap} "
            f"| {_fmt(w.between_low_dd, 2)} | {_fmt(w.between_singles)} |")
    return "\n".join(lines)


def cmd_export(out_dir: str = "/app/w2s_v3_out"):
    """导出 规律组/YYYY-MM.md(页首月索引+每簇一小节波次竖表) + _汇总(all_clusters.md/all_waves.csv/summary)."""
    bars, segs, clusters, waves, bounds = load_all()
    gc = assign_groups(clusters, waves)
    name_map = bars.drop_duplicates("sid").set_index("sid")["name"]
    # 峰值波(高度最高取最早) — 1=一波见顶, 越大说明行情越靠后段接力
    peak = (waves.sort_values(["cluster_id", "height", "wave_no"], ascending=[True, False, True])
            .groupby("cluster_id")["wave_no"].first())
    gc = gc.copy()
    gc["peak_wave"] = gc["cluster_id"].map(peak)

    n_files = 0
    for gk, gsub in gc.groupby("group"):
        gdir = os.path.join(out_dir, gk)
        os.makedirs(gdir, exist_ok=True)
        for ym, ms in gsub.sort_values(["start_date"]).groupby("anchor_month"):
            ids = set(ms["cluster_id"])
            ws = waves[waves["cluster_id"].isin(ids)].sort_values(["cluster_id", "wave_no"])
            head = [
                f"# {gk} · {ym}",
                "",
                f"本月行情簇 **{len(ms)}** 个(归档月=第一波首板日所在月)。⚠️next_uncertain=末波距数据末端<21交易日,"
                "是否终结未定。",
                "",
                "| 代码 | 名称 | 波数 | 起点 | 终点 | 峰值波 | 备注 |",
                "|---|---|---|---|---|---|---|",
            ]
            for _, r in ms.iterrows():
                note = []
                if bool(r["next_uncertain"]):
                    note.append("未定终态")
                head.append(
                    f"| {r['code']} | {_fmt(name_map.get(r['sid']))} | {r['n_waves']} "
                    f"| {r['start_date'].date()} | {r['end_date'].date()} | {int(r['peak_wave'])} "
                    f"| {'、'.join(note) or ''} |")
            blocks = [_cluster_block(ms.iloc[i], ws[ws['cluster_id'] == ms.iloc[i]['cluster_id']], name_map)
                      for i in range(len(ms))]
            text = "\n".join(head) + "\n\n---\n\n" + "\n\n---\n\n".join(blocks) + "\n"
            with open(os.path.join(gdir, f"{ym}.md"), "w", encoding="utf-8") as f:
                f.write(text)
            n_files += 1

    # 汇总层: 全簇 md / 波长表 csv(机器验算入口) / 组×月透视 md
    sdir = os.path.join(out_dir, "_汇总")
    os.makedirs(sdir, exist_ok=True)
    all_lines = [
        "# 弱转强V3 · 全部行情簇索引",
        "",
        "| cluster_id | 代码 | 名称 | 组 | 归档月 | 波数 | 起点 | 终点 | 峰值波 | 未定终态 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for _, r in gc.sort_values(["anchor_month", "code"]).iterrows():
        all_lines.append(
            f"| {r['cluster_id']} | {r['code']} | {_fmt(name_map.get(r['sid']))} | {r['group']} "
            f"| {r['anchor_month']} | {r['n_waves']} | {r['start_date'].date()} | {r['end_date'].date()} "
            f"| {int(r['peak_wave'])} | {'True' if bool(r['next_uncertain']) else ''} |")
    with open(os.path.join(sdir, "all_clusters.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(all_lines) + "\n")

    long = waves.copy()
    long["name"] = long["sid"].map(name_map)
    long["first_date"] = long["first_date"].dt.date
    long["confirm_date"] = pd.to_datetime(long["confirm_date"]).dt.date
    long["last_date"] = long["last_date"].dt.date
    long = long.merge(gc[["cluster_id", "group", "anchor_month"]], on="cluster_id")
    cols = ["cluster_id", "code", "name", "group", "anchor_month", "wave_no", "n_waves",
            "first_date", "confirm_date", "last_date", "height", "gap_prev_tb",
            "gap_prev_cal", "between_low_dd", "between_singles"]
    long["n_waves"] = long["cluster_id"].map(gc.set_index("cluster_id")["n_waves"])
    long[cols].sort_values(["group", "cluster_id", "wave_no"]).to_csv(
        os.path.join(sdir, "all_waves.csv"), index=False, encoding="utf-8-sig")

    piv = gc.pivot_table(index="anchor_month", columns="group", values="cluster_id",
                         aggfunc="count", fill_value=0)
    piv.loc["合计"] = piv.sum()
    with open(os.path.join(sdir, "summary_组x月.md"), "w", encoding="utf-8") as f:
        f.write("# 组 × 锚定月 样本量\n\n")
        f.write(piv.to_markdown() + "\n")
    print(f"导出完成: {len(gc)} 簇 → {n_files} 个月度md + _汇总(all_clusters.md/all_waves.csv/summary) @ {out_dir}")
    print(piv.to_string())


# ────────────────────────── 条件覆盖验证 ──────────────────────────

VERIFY_WINDOWS = (6, 8, 10, 21)   # 候选窗口: 罩住上波末两板需 N>=gap+1 → 快接(≤5)N=6起, 缓启(≤20)N=21


def cmd_verify():
    """两分法条件(≥2板后 快速接续/缓慢重启)覆盖验证.

    条件(站在新波首板日 D0 可观测, 同花顺式): 主板非ST + 当日涨停(首板) + 前N日出现过≥2连板.
    验证: 780簇全部续波(wave_no>=2)的首板日是否被条件罩住(独立重算, 不从簇表反推);
    同时拆解全宇宙命中集(条件还捞出什么)与弱转强/补涨原始分布(波间创新高/回撤).
    """
    bars, segs, clusters, waves, bounds = load_all()

    # ── 独立重算条件列 ──
    brk = (~bars["is_lim"]).groupby(bars["sid"], sort=False).cumsum()
    bars["seg_h"] = bars.groupby([bars["sid"], brk], sort=False)["streak"].transform("max")
    g = bars.groupby("sid", sort=False)
    for N in VERIFY_WINDOWS:
        bars[f"s2max{N}"] = g["streak"].transform(lambda s: s.shift(1).rolling(N, min_periods=1).max())
    bars["prev_h2"] = bars["seg_h"].where(bars["seg_h"] >= 2).groupby(
        bars["sid"], sort=False).ffill()          # 最近一次≥2连板段的高度(分桶用)
    bars["n1_lim"] = g["is_lim"].shift(-1)

    # ── 覆盖验证: 续波首板日 vs 各窗口 ──
    wv = waves[waves["wave_no"] > 1].copy()
    wv = wv.merge(bars[["sid", "pos"] + [f"s2max{N}" for N in VERIFY_WINDOWS]],
                  left_on=["sid", "first_pos"], right_on=["sid", "pos"], how="left")
    wv["fast"] = wv["gap_prev_tb"] <= 5
    print(f"== 覆盖验证: 簇内续波 {len(wv)} 个 = 快接(gap≤5) {int(wv['fast'].sum())} "
          f"+ 缓启(6~20) {int((~wv['fast']).sum())} ==")
    print("波首板日满足「前N日(不含当日)出现过≥2连板」比例:")
    for N in VERIFY_WINDOWS:
        cov = wv[f"s2max{N}"] >= 2
        line = f"  N={N:2d}: 全部 {cov.mean()*100:6.2f}%"
        for lab, m in (("快接", wv["fast"]), ("缓启", ~wv["fast"])):
            line += f" | {lab} {cov[m].mean()*100:6.2f}%({int(cov[m].sum())}/{int(m.sum())})"
        print(line)
    bad = wv[wv["s2max21"] < 2]
    if len(bad):
        print(f"!! N=21 仍未覆盖 {len(bad)} 波(需人工核):")
        print(bad[["cluster_id", "code", "wave_no", "gap_prev_tb", "first_date", "s2max21"]].to_string(index=False))

    # ── 全宇宙命中集: 条件=首板 + 前21日≥2连板 ──
    hit = bars[bars["is_lim"] & (bars["streak"] == 1) & (bars["s2max21"] >= 2)].copy()
    big = segs[segs["height"] >= 2]
    big_first = {sid: grp["first_pos"].to_numpy() for sid, grp in big.groupby("sid")}
    big_last = {sid: grp.sort_values("last_pos")["last_pos"].to_numpy() for sid, grp in big.groupby("sid")}

    def _next2(r):
        arr = big_first.get(r["sid"])
        if arr is None:
            return np.nan
        i = np.searchsorted(arr, r["pos"], side="right")
        return float(arr[i] - r["pos"]) if i < len(arr) else np.nan

    def _pgap(r):
        arr = big_last.get(r["sid"])
        if arr is None or not len(arr):
            return np.nan
        i = np.searchsorted(arr, r["pos"], side="left")   # 第一个 >= pos
        return float(r["pos"] - arr[i - 1]) if i > 0 else np.nan

    hit["gap_next2"] = hit.apply(_next2, axis=1)           # → 下一个≥2段首板的交易日距
    hit["gap_prev2"] = hit.apply(_pgap, axis=1)            # ← 上一个≥2段末板的交易日距
    cont_keys = set(zip(wv["sid"], wv["first_pos"]))
    first_keys = set(zip(waves.loc[waves["wave_no"] == 1, "sid"],
                         waves.loc[waves["wave_no"] == 1, "first_pos"]))

    def _kind(r):
        k = (r["sid"], r["pos"])
        if k in cont_keys:
            return "簇内续波(研究票)"
        if k in first_keys:
            return "簇首波(事后成长)"
        return "孤立≥2段" if r["n1_lim"] else "次日断(单板)"

    hit["kind"] = hit.apply(_kind, axis=1)
    print(f"\n== 命中集(主板非ST+当日首板+前21日≥2连板) n={len(hit):,} 票日 ==")
    print(hit["kind"].value_counts().to_string())
    print(f"次日连板率 {hit['n1_lim'].fillna(False).mean()*100:.1f}% | "
          f"命中后20日内再现≥2段 {hit['gap_next2'].le(20).mean()*100:.1f}%")

    # 按上次≥2段高度 × 再起间隔分桶(主人: 不限于二板, 起点可能≥3板)
    hit["prev_bucket"] = pd.cut(hit["prev_h2"], [1.5, 2.5, 3.5, 5.5, 99],
                                labels=["上次2板", "上次3板", "上次4-5板", "上次6板+"])
    hit["pace"] = pd.cut(hit["gap_prev2"], [0, 5.5, 21.5, 999],
                         labels=["快接≤5", "缓启6~21", "更远"])
    print("\n== 命中 × 上次段高度: n / 次日板% / 20日再续% ==")
    by = hit.groupby("prev_bucket", observed=True).agg(
        n=("pos", "size"),
        next_lim=("n1_lim", lambda s: round(s.fillna(False).mean() * 100)),
        re20=("gap_next2", lambda s: round(s.le(20).mean() * 100)))
    print(by.to_string())
    print("\n== 命中 × 再起间隔(上次段末板→今日) ==")
    by2 = hit.groupby("pace", observed=True).agg(
        n=("pos", "size"),
        next_lim=("n1_lim", lambda s: round(s.fillna(False).mean() * 100)),
        re20=("gap_next2", lambda s: round(s.le(20).mean() * 100)))
    print(by2.to_string())

    # ── 弱转强/补涨原始分布: 续波波间是否盘中创新高 + 回撤分位 ──
    aw = waves.sort_values(["cluster_id", "wave_no"]).copy()
    aw["prev_high"] = aw.groupby("cluster_id")["high_price"].shift(1)
    aw["prev_lpos"] = aw.groupby("cluster_id")["last_pos"].shift(1)
    m = aw[aw["wave_no"] > 1]
    highs = bars.set_index(["sid", "pos"])["high_price"].sort_index()

    def _bh(r):
        # 断板期间(上波末板次日..本波首板日, 含首板日盘中): 切片不可含上波末板(其high即prev_high恒真)
        sl = highs.loc[(r["sid"], slice(int(r["prev_lpos"]) + 1, int(r["first_pos"]))), ]
        return float(sl.max() >= r["prev_high"] - 1e-9) if len(sl) else np.nan

    m = m.copy()
    m["brk_hi"] = m.apply(_bh, axis=1)   # 波间(上波末板..本波首板)盘中摸过上波最高价
    print("\n== 续波波间形态(弱转强=波间创新高 / 补涨=回落后再起) ==")
    for lab, sub in (("快接", m[m["gap_prev_tb"] <= 5]), ("缓启", m[m["gap_prev_tb"] > 5])):
        dd = sub["between_low_dd"].dropna()
        q = np.percentile(dd, [10, 25, 50, 75])
        print(f"{lab}: n={len(sub)} 波间盘中创新高 {sub['brk_hi'].mean()*100:.0f}% | "
              f"回撤p10/25/50/75 = {q[0]:.1f}/{q[1]:.1f}/{q[2]:.1f}/{q[3]:.1f}%")
    m["fast"] = m["gap_prev_tb"] <= 5
    print("快接×缓启 × 波间创新高 交叉表(1=创新高):")
    print(pd.crosstab(m["fast"], m["brk_hi"], margins=True).to_string())

    # ── 覆盖矩阵: 五组分类 × 两条件组(簇级看二波 / 波级看全部续波) ──
    gc = assign_groups(clusters, waves)
    gc["cond"] = np.where(gc["gap_w2"] <= 5, "快接条件", "缓启条件")
    print("\n== 簇级覆盖矩阵: 五组 × 二波落入的条件组(加总=780=100%) ==")
    print(pd.crosstab(gc["group"], gc["cond"], margins=True).to_string())
    wg = waves[waves["wave_no"] > 1].merge(gc[["cluster_id", "group"]], on="cluster_id")
    wg["cond"] = np.where(wg["gap_prev_tb"] <= 5, "快接条件", "缓启条件")
    print("\n== 波级覆盖矩阵: 全部续波 × 条件组(加总=1018=100%) ==")
    print(pd.crosstab(wg["group"], wg["cond"], margins=True).to_string())


# ────────────────────────── 条件优化(实走分析) ──────────────────────────

def _build_trigger(bars, segs, waves):
    """公共触发集构建(optimize/position 共用).

    衍生列直接挂在 bars 上; 触发集 = 主板非ST + 盘中≥+6% + 昨日未涨停 + 前21日≥2连板,
    排除 D0 一字板(买不进)与数据末端; 触发价=昨收×1.06, D1 收盘卖.
    返回 (t, 排除的一字板数).
    """
    brk = (~bars["is_lim"]).groupby(bars["sid"], sort=False).cumsum()
    bars["seg_h"] = bars.groupby([bars["sid"], brk], sort=False)["streak"].transform("max")
    g = bars.groupby("sid", sort=False)
    bars["s2max21"] = g["streak"].transform(lambda s: s.shift(1).rolling(21, min_periods=1).max())
    bars["prev_h2"] = bars["seg_h"].where(bars["seg_h"] >= 2).groupby(
        bars["sid"], sort=False).ffill()
    bars["prev_lim"] = g["is_lim"].shift(1).fillna(False).astype(bool)   # bool shift→object, ~会恒真, 必须astype
    bars["chg"] = bars["close_price"] / bars["prev_close"] - 1
    bars["chg_prev"] = g["chg"].shift(1)
    bars["open_g"] = bars["open_price"] / bars["prev_close"] - 1
    bars["vol_rel5"] = bars["volume"] / g["volume"].transform(
        lambda s: s.rolling(5, min_periods=3).mean())
    bars["n1_close"] = g["close_price"].shift(-1)
    bars["n1_lim"] = g["is_lim"].shift(-1).fillna(False).astype(bool)
    # 昨日量比/换手: 盘中触发可执行口径(T日收盘确认→T+1触发), 当日全天量是未来函数
    bars["p_vol_rel5"] = g["vol_rel5"].shift(1)
    bars["p_turnover"] = g["turnover_rate"].shift(1)
    bars["one_word"] = (bars["open_price"].eq(bars["high_price"])
                        & bars["open_price"].eq(bars["low_price"])
                        & bars["open_price"].eq(bars["close_price"]))
    bars["ret_d1"] = bars["n1_close"] / (bars["prev_close"] * 1.06) - 1

    big = segs[segs["height"] >= 2]
    big_first = {sid: grp["first_pos"].to_numpy() for sid, grp in big.groupby("sid")}
    big_last = {sid: grp.sort_values("last_pos")["last_pos"].to_numpy() for sid, grp in big.groupby("sid")}

    def _pgap(r):
        arr = big_last.get(r["sid"])
        if arr is None or not len(arr):
            return np.nan
        i = np.searchsorted(arr, r["pos"], side="left")
        return float(r["pos"] - arr[i - 1]) if i > 0 else np.nan

    def _next2(r):
        arr = big_first.get(r["sid"])
        if arr is None:
            return np.nan
        i = np.searchsorted(arr, r["pos"], side="right")
        return float(arr[i] - r["pos"]) if i < len(arr) else np.nan

    mkt = bars.groupby("trade_date")["is_lim"].sum().rename("mkt_lim").reset_index()
    mkt["mkt_prev"] = mkt["mkt_lim"].shift(1)
    bars = bars.merge(mkt[["trade_date", "mkt_prev"]], on="trade_date", how="left")

    t = bars[(bars["high_price"] / bars["prev_close"] - 1 >= 0.06)
             & (~bars["prev_lim"]) & (bars["s2max21"] >= 2)
             & bars["n1_close"].notna()].copy()
    n_ow = int(t["one_word"].sum())
    t = t[~t["one_word"]].copy()
    t["gap_prev2"] = t.apply(_pgap, axis=1)
    t["gap_next2"] = t.apply(_next2, axis=1)
    t["d0_seal"] = t["is_lim"]
    # 昨收距上波(≥2段)最高价回撤 + 上波高点本身(position/history/deep 共用)
    prev_info = {sid: grp.sort_values("last_pos")[["last_pos", "high_price"]].reset_index(drop=True)
                 for sid, grp in big.groupby("sid")}

    def _pull(r):
        df = prev_info.get(r["sid"])
        if df is None:
            return pd.Series({"pull_hi": np.nan, "prev_wave_high": np.nan})
        i = df["last_pos"].searchsorted(r["pos"], side="left")
        if i == 0:
            return pd.Series({"pull_hi": np.nan, "prev_wave_high": np.nan})
        ph = float(df.iloc[i - 1]["high_price"])
        return pd.Series({"pull_hi": r["prev_close"] / ph - 1, "prev_wave_high": ph})

    t[["pull_hi", "prev_wave_high"]] = t.apply(_pull, axis=1)
    wave_keys = set(zip(waves["sid"], waves["first_pos"]))
    t["kind"] = ["波首板(研究票)" if (s, p) in wave_keys else "多出票"
                 for s, p in zip(t["sid"], t["pos"])]
    t["outcome"] = np.where(~t["d0_seal"], "D0炸板",
                            np.where(t["n1_lim"], "封板→D1连板", "封板→D1未连"))
    return t, n_ow


def _res_stat(df, by):
    """触发集分组结果统计: n/封板%/连板%/D1收益%/胜率%/再起%/好票浓度%."""
    def _row(s):
        sealed = s[s["d0_seal"]]
        return pd.Series({
            "n": len(s),
            "封板%": round(s["d0_seal"].mean() * 100),
            "连板%": round(sealed["n1_lim"].mean() * 100) if len(sealed) else np.nan,
            "D1收益%": round(s["ret_d1"].mean() * 100, 2),
            "胜率%": round((s["ret_d1"] > 0).mean() * 100),
            "再起20%": round(s["gap_next2"].le(20).mean() * 100),
            "好票浓度%": round((s["kind"] == "波首板(研究票)").mean() * 100, 1),
        })
    return df.groupby(by, observed=True).apply(_row, include_groups=False).to_string()


def cmd_optimize():
    """条件组合实走一遍(盘中+6%触发买入口径): 多出票的炸板/D+1负收益 + 连板概率维度挖掘."""
    bars, segs, clusters, waves, bounds = load_all()
    t, n_ow = _build_trigger(bars, segs, waves)

    print(f"== 触发集(主板非ST + 盘中≥+6% + 昨日未涨停 + 前21日≥2连板) n={len(t):,}"
          f" (另排除D0一字板 {n_ow}) ==")
    print("\n== 结果分布: D0封板/炸板 × D1连板 ==")
    print(t.groupby("outcome").agg(n=("ret_d1", "size"),
                                   D1收益均值=("ret_d1", lambda s: round(s.mean() * 100, 2)),
                                   胜率=("ret_d1", lambda s: round((s > 0).mean() * 100)),
                                   再起20=(("gap_next2"), lambda s: round(s.le(20).mean() * 100))
                                   ).to_string())
    print("\n== 研究票 vs 多出票 ==")
    print(_res_stat(t, "kind"))

    t["上次段高"] = pd.cut(t["prev_h2"], [1.5, 2.5, 3.5, 5.5, 99], labels=["2板", "3板", "4-5板", "6板+"])
    t["再起间隔"] = pd.cut(t["gap_prev2"], [0, 5.5, 20.5, 999], labels=["快接≤5", "缓启6-20", "更远"])
    t["开盘幅度"] = pd.cut(t["open_g"] * 100, [-99, -5, 0, 3, 6, 99], labels=["<-5", "-5~0", "0~3", "3~6", "≥6"])
    t["昨日涨幅"] = pd.cut(t["chg_prev"] * 100, [-99, -5, -2, 0, 99], labels=["<-5", "-5~-2", "-2~0", ">0"])
    t["昨量比"] = pd.cut(t["p_vol_rel5"], [0, 0.7, 1.2, 2, 99], labels=["<0.7", "0.7-1.2", "1.2-2", ">2"])
    t["昨换手"] = pd.cut(t["p_turnover"], [0, 8, 15, 25, 100], labels=["<8", "8-15", "15-25", ">25"])
    t["昨涨停家数"] = pd.cut(t["mkt_prev"], [0, 50, 80, 110, 9999], labels=["<50", "50-80", "80-110", ">110"])
    for dim in ("上次段高", "再起间隔", "开盘幅度", "昨日涨幅", "昨量比", "昨换手", "昨涨停家数"):
        print(f"\n== 连板概率挖掘 · 按{dim} (量比/换手=昨日值, 无未来函数) ==")
        print(_res_stat(t, dim))

    # 组合验证(全部盘中/收盘可执行维度)
    print("\n== 组合验证 ==")
    combos = {
        "C1 昨量比<0.7": t["昨量比"] == "<0.7",
        "C2 昨量比<0.7 + 上次2-3板": (t["昨量比"] == "<0.7") & t["上次段高"].isin(["2板", "3板"]),
        "C3 昨跌>2% + 上次2-3板 + 昨换手<15": (t["chg_prev"] <= -0.02)
            & t["上次段高"].isin(["2板", "3板"]) & (t["昨换手"].isin(["<8", "8-15"])),
        "C4 开盘0~6% + 昨量比<1.2 + 上次2-3板": t["open_g"].between(0, 0.06)
            & t["昨量比"].isin(["<0.7", "0.7-1.2"]) & t["上次段高"].isin(["2板", "3板"]),
    }
    for name, mask in combos.items():
        sub = t[mask.fillna(False)]
        if not len(sub):
            print(f"  {name}: n=0")
            continue
        sealed = sub[sub["d0_seal"]]
        print(f"  {name}: n={len(sub)} 封板{sub['d0_seal'].mean()*100:.0f}% "
              f"连板{sealed['n1_lim'].mean()*100:.0f}% D1{sub['ret_d1'].mean()*100:+.2f}% "
              f"胜率{(sub['ret_d1']>0).mean()*100:.0f}% "
              f"研究票浓度{(sub['kind']=='波首板(研究票)').mean()*100:.1f}%")


# ────────────────────────── 位置形态深层分析 ──────────────────────────

def cmd_position():
    """好票vs差票的位置形态对比: 前N日累计涨幅×均线偏离×距上波高点回撤 + 场景适用性."""
    bars, segs, clusters, waves, bounds = load_all()
    g = bars.groupby("sid", sort=False)
    for N in (2, 3, 5, 10, 20):
        bars[f"ret{N}p"] = g["close_price"].transform(
            lambda s, n=N: s.pct_change(n).shift(1))                 # 前N日累计涨幅(不含触发日)
    for w in (5, 10, 20):
        bars[f"bias{w}p"] = g["close_price"].transform(
            lambda s, w=w: (s / s.rolling(w).mean() - 1).shift(1))   # 昨收偏离均线%
    t, n_ow = _build_trigger(bars, segs, waves)

    good_m = t["kind"] == "波首板(研究票)"
    print(f"== 位置形态: 好票(波首板 n={int(good_m.sum())}) vs 差票(多出票 n={int((~good_m).sum())}) ==")
    print("\n== 分位数对比 p25/p50/p75 (%) ==")
    zh = {"ret2p": "前2日涨幅", "ret3p": "前3日涨幅", "ret5p": "前5日涨幅", "ret10p": "前10日涨幅",
          "ret20p": "前20日涨幅", "bias5p": "昨收偏离MA5", "bias10p": "昨收偏离MA10",
          "bias20p": "昨收偏离MA20", "pull_hi": "昨收距上波高点"}
    feats = list(zh)
    rows = []
    for c in feats:
        qg = np.percentile(t.loc[good_m, c].dropna(), [25, 50, 75]) * 100
        qb = np.percentile(t.loc[~good_m, c].dropna(), [25, 50, 75]) * 100
        rows.append({"特征": zh[c],
                     "好票p25/50/75": "/".join(f"{v:+.1f}" for v in qg),
                     "差票p25/50/75": "/".join(f"{v:+.1f}" for v in qb)})
    print(pd.DataFrame(rows).to_string(index=False))

    t["前2日涨幅"] = pd.cut(t["ret2p"] * 100, [-99, -10, -5, -2, 0, 2, 5, 99],
                           labels=["<-10", "-10~-5", "-5~-2", "-2~0", "0~2", "2~5", ">5"])
    t["前3日涨幅"] = pd.cut(t["ret3p"] * 100, [-99, -12, -6, -2, 0, 3, 99],
                           labels=["<-12", "-12~-6", "-6~-2", "-2~0", "0~3", ">3"])
    t["前5日涨幅"] = pd.cut(t["ret5p"] * 100, [-99, -15, -8, -3, 0, 5, 99],
                           labels=["<-15", "-15~-8", "-8~-3", "-3~0", "0~5", ">5"])
    t["偏离MA10"] = pd.cut(t["bias10p"] * 100, [-99, -10, -5, -2, 0, 2, 5, 99],
                           labels=["<-10", "-10~-5", "-5~-2", "-2~0", "0~2", "2~5", ">5"])
    t["距上波高点"] = pd.cut(t["pull_hi"] * 100, [-99, -30, -20, -12, -6, 0, 99],
                            labels=["<-30", "-30~-20", "-20~-12", "-12~-6", "-6~0", "≥0(高位)"])
    for dim in ("前2日涨幅", "前3日涨幅", "前5日涨幅", "偏离MA10", "距上波高点"):
        print(f"\n== 按{dim} ==")
        print(_res_stat(t, dim))

    # 场景适用性: 同一形态区间在不同场景下的收益是否移动(什么情况下更适用)
    t["再起间隔"] = pd.cut(t["gap_prev2"], [0, 5.5, 20.5, 999], labels=["快接≤5", "缓启6-20", "更远"])
    t["上次段高"] = pd.cut(t["prev_h2"], [1.5, 2.5, 3.5, 99], labels=["2板", "3板", "4板+"])
    for dim, scene in (("前3日涨幅", "再起间隔"), ("前3日涨幅", "上次段高"),
                       ("距上波高点", "再起间隔"), ("偏离MA10", "上次段高")):
        sub = t[[dim, scene, "ret_d1"]].dropna()
        n = sub.pivot_table(index=dim, columns=scene, values="ret_d1", aggfunc="size")
        r = (sub.pivot_table(index=dim, columns=scene, values="ret_d1", aggfunc="mean") * 100).round(2)
        print(f"\n== {dim} × {scene}  [上表 n / 下表 D1收益%] ==")
        print(n.to_string())
        print(r.to_string())


# ────────────────────────── 历史首板溢价(辅助因子) ──────────────────────────

def cmd_history():
    """历史半年(120交易日)首板D+1收益辅助因子: 个股历史打板隔日溢价习性对本次触发的预测力.

    fb_ret = 首板收盘(=涨停价)买入, D+1 收盘卖; hist_fb = 过去120交易日(不含今日)该票
    历史首板的 fb_ret 均值(rolling→shift 严格无泄漏), hist_fb_n = 同窗口首板次数.
    """
    bars, segs, clusters, waves, bounds = load_all()
    bars["is_first"] = bars["is_lim"] & (bars["streak"] == 1)
    n1c = bars.groupby("sid", sort=False)["close_price"].shift(-1)
    bars["fb_ret"] = np.where(bars["is_first"], n1c / bars["close_price"] - 1, np.nan)
    g = bars.groupby("sid", sort=False)
    bars["hist_fb"] = g["fb_ret"].transform(
        lambda s: s.rolling(120, min_periods=1).mean().shift(1))
    bars["hist_fb_n"] = bars["is_first"].astype(float).groupby(bars["sid"], sort=False).transform(
        lambda s: s.rolling(120, min_periods=1).sum().shift(1))
    t, n_ow = _build_trigger(bars, segs, waves)

    has = t["hist_fb_n"] >= 1
    print(f"== 历史首板D+1溢价辅助因子(120交易日窗口) 触发集 n={len(t):,} ==")
    print(f"有历史首板样本: {int(has.sum())} ({has.mean()*100:.0f}%) | 无样本(半年未首板): {int((~has).sum())}")
    t["历史首板溢价"] = pd.cut(t["hist_fb"] * 100, [-99, -5, -2, 0, 2, 5, 99],
                              labels=["<-5", "-5~-2", "-2~0", "0~2", "2~5", ">5"]
                              ).cat.add_categories(["无样本"]).fillna("无样本")
    t["历史首板次数"] = pd.cut(t["hist_fb_n"], [-1, 0.5, 1.5, 2.5, 4.5, 99],
                              labels=["0", "1", "2", "3-4", "5+"])
    t["再起间隔"] = pd.cut(t["gap_prev2"], [0, 5.5, 20.5, 999], labels=["快接≤5", "缓启6-20", "更远"])
    t["距上波高点"] = pd.cut(t["pull_hi"] * 100, [-99, -30, -12, -6, 0, 99],
                            labels=["<-30", "-30~-12", "-12~-6", "-6~0", "≥0"])
    print("\n== 按历史首板溢价%(首板收盘买→D1收盘卖的历史均值) ==")
    print(_res_stat(t, "历史首板溢价"))
    print("\n== 按历史首板次数(120日内) ==")
    print(_res_stat(t, "历史首板次数"))
    for scene in ("历史首板次数", "再起间隔", "距上波高点"):
        sub = t[["历史首板溢价", scene, "ret_d1"]].dropna()
        n = sub.pivot_table(index="历史首板溢价", columns=scene, values="ret_d1", aggfunc="size")
        r = (sub.pivot_table(index="历史首板溢价", columns=scene, values="ret_d1", aggfunc="mean") * 100).round(2)
        print(f"\n== 历史首板溢价 × {scene} [上 n / 下 D1收益%] ==")
        print(n.to_string())
        print(r.to_string())


# ────────────────────────── 分情形微观形态深挖 ──────────────────────────

def cmd_deep():
    """快接/缓启 分情形专场: 每个情形用各自的形态显微镜.

    快接专场: 断板期间洗盘深度 + 昨日K线(阴/阳实体·上下影线) + 两日涨幅 + 昨收区间位置.
    缓启专场: 断板天数 + 乖离率(MA5/10/20 对比) + 横盘天数 + 涨跌交替 + 期间振幅 + 洗盘深度.
    断板期间 = 上波末板次日 .. 昨日(触发日为再起日, 期间全部已知, 无未来函数).
    """
    bars, segs, clusters, waves, bounds = load_all()
    g = bars.groupby("sid", sort=False)
    pc, po = g["close_price"].shift(1), g["open_price"].shift(1)
    hi_oc = pd.concat([pc, po], axis=1).max(axis=1)
    lo_oc = pd.concat([pc, po], axis=1).min(axis=1)
    bars["body_prev"] = (pc - po) / bars["prev_close"] * 100          # 昨日实体%(阳正阴负)
    bars["ush_prev"] = (g["high_price"].shift(1) - hi_oc) / bars["prev_close"] * 100
    bars["lsh_prev"] = (lo_oc - g["low_price"].shift(1)) / bars["prev_close"] * 100
    bars["ret2p"] = g["close_price"].transform(lambda s: s.pct_change(2).shift(1))
    for w in (5, 10, 20):
        bars[f"bias{w}p"] = g["close_price"].transform(
            lambda s, w=w: (s / s.rolling(w).mean() - 1).shift(1))
    t, n_ow = _build_trigger(bars, segs, waves)

    # 断板期间过程结构(逐行切片: 区间小, 1.6万行可承受); pos升int64防int32索引切片边界报错
    idx = bars.set_index([bars["sid"], bars["pos"].astype("int64")])[
        ["high_price", "low_price", "chg"]].sort_index()

    def _pf(r):
        lp = int(r["pos"] - r["gap_prev2"])
        # DataFrame.loc[(sid, slice), :]: 末尾,: 必须显式, 否则 slice 被解释为列索引
        seg = idx.loc[(r["sid"], slice(lp + 1, int(r["pos"]) - 1)), :]
        phw = r["prev_wave_high"]
        if not len(seg) or pd.isna(phw):
            return pd.Series(dtype=float)
        hi, lo = float(seg["high_price"].max()), float(seg["low_price"].min())
        chgs = seg["chg"].dropna().to_numpy()
        return pd.Series({
            "lo_dd": (lo / phw - 1) * 100,                    # 断板期间最低距上波高点%
            "amp_w": (hi - lo) / phw * 100,                   # 期间高低振幅%
            "switches": int((np.diff(np.sign(chgs)) != 0).sum()) if len(chgs) > 1 else 0,
            "n_flat": int((np.abs(chgs) < 0.02).sum()),       # ±2%内窄幅天数
            "n_up": int((chgs > 0).sum()), "n_dn": int((chgs < 0).sum()),
            "close_pos": (r["prev_close"] - lo) / (hi - lo) * 100 if hi > lo else np.nan,
        })

    t = pd.concat([t, t.apply(_pf, axis=1)], axis=1)

    def _overall(sub, name):
        sealed = sub[sub["d0_seal"]]
        print(f"{name}: n={len(sub)} 封板{sub['d0_seal'].mean()*100:.0f}% "
              f"连板{sealed['n1_lim'].mean()*100:.0f}% D1{sub['ret_d1'].mean()*100:+.2f}% "
              f"胜率{(sub['ret_d1']>0).mean()*100:.0f}%")

    # ══ 快接专场 ══
    fast = t[t["gap_prev2"].between(2, 5)].copy()
    print("\n" + "═" * 62 + f"\n== 快接专场(断板后2~5日再起) n={len(fast)} ==")
    _overall(fast, "整体")
    fast["洗盘深度%"] = pd.cut(fast["lo_dd"], [-99, -15, -10, -7, -5, -3, 0, 99],
                              labels=["<-15", "-15~-10", "-10~-7", "-7~-5", "-5~-3", "-3~0", "≥0未破高"])
    fast["昨日K线"] = pd.cut(fast["body_prev"], [-99, -3, -1, 0, 1, 3, 99],
                            labels=["大阴<-3", "阴-3~-1", "小阴-1~0", "小阳0~1", "阳1~3", "大阳>3"])
    fast["昨日上影"] = pd.cut(fast["ush_prev"], [-99, 0.005, 1, 2, 4, 99],
                             labels=["无", "0~1", "1~2", "2~4", "4+"])
    fast["昨日下影"] = pd.cut(fast["lsh_prev"], [-99, 0.005, 1, 2, 4, 99],
                             labels=["无", "0~1", "1~2", "2~4", "4+"])
    fast["两日涨幅%"] = pd.cut(fast["ret2p"] * 100, [-99, -8, -4, -2, 0, 2, 4, 99],
                              labels=["<-8", "-8~-4", "-4~-2", "-2~0", "0~2", "2~4", ">4"])
    fast["昨收区间位"] = pd.cut(fast["close_pos"], [-1, 20, 40, 60, 80, 101],
                               labels=["底20%", "20-40", "40-60", "60-80", "顶20%"])
    for dim in ("洗盘深度%", "昨日K线", "昨日上影", "昨日下影", "两日涨幅%", "昨收区间位"):
        print(f"\n-- 快接 · 按{dim} --")
        print(_res_stat(fast, dim))
    sub = fast[["昨日K线", "洗盘深度%", "ret_d1"]].dropna()
    print("\n-- 快接 · 昨日K线 × 洗盘深度 [上 n / 下 D1%] --")
    print(sub.pivot_table(index="昨日K线", columns="洗盘深度%", values="ret_d1", aggfunc="size").to_string())
    print((sub.pivot_table(index="昨日K线", columns="洗盘深度%", values="ret_d1", aggfunc="mean") * 100).round(2).to_string())

    # ══ 缓启专场 ══
    slow = t[t["gap_prev2"].between(6, 20)].copy()
    print("\n" + "═" * 62 + f"\n== 缓启专场(断板后6~20日再起) n={len(slow)} ==")
    _overall(slow, "整体")
    slow["断板天数"] = pd.cut(slow["gap_prev2"] - 1, [0, 3, 5, 7, 10, 19],
                             labels=["1-3", "4-5", "6-7", "8-10", "11-19"])
    bias_bins = [-99, -7, -3, 0, 3, 7, 99]
    bias_lab = ["<-7", "-7~-3", "-3~0", "0~3", "3~7", ">7"]
    for w in (5, 10, 20):
        slow[f"乖离MA{w}%"] = pd.cut(slow[f"bias{w}p"] * 100, bias_bins, labels=bias_lab)
    slow["横盘天数"] = pd.cut(slow["n_flat"], [-1, 0.5, 1.5, 3.5, 99], labels=["0", "1", "2-3", "4+"])
    slow["涨跌交替"] = pd.cut(slow["switches"], [-1, 0.5, 2.5, 4.5, 99], labels=["0-1", "2", "3-4", "5+"])
    slow["红绿结构"] = np.where(slow["n_up"] > slow["n_dn"], "红>绿",
                            np.where(slow["n_up"] < slow["n_dn"], "红<绿", "红=绿"))
    slow["期间振幅%"] = pd.cut(slow["amp_w"], [-1, 8, 15, 25, 40, 999],
                              labels=["<8", "8-15", "15-25", "25-40", ">40"])
    slow["洗盘深度%"] = pd.cut(slow["lo_dd"], [-99, -30, -20, -12, -6, 0, 99],
                              labels=["<-30", "-30~-20", "-20~-12", "-12~-6", "-6~0", "≥0未破高"])
    slow["昨收区间位"] = pd.cut(slow["close_pos"], [-1, 20, 40, 60, 80, 101],
                               labels=["底20%", "20-40", "40-60", "60-80", "顶20%"])
    for dim in ("断板天数", "乖离MA5%", "乖离MA10%", "乖离MA20%", "横盘天数", "涨跌交替",
                "红绿结构", "期间振幅%", "洗盘深度%", "昨收区间位"):
        print(f"\n-- 缓启 · 按{dim} --")
        print(_res_stat(slow, dim))
    for scene in ("断板天数", "涨跌交替", "昨收区间位"):
        sub = slow[["洗盘深度%", scene, "ret_d1"]].dropna()
        print(f"\n-- 缓启 · 洗盘深度 × {scene} [上 n / 下 D1%] --")
        print(sub.pivot_table(index="洗盘深度%", columns=scene, values="ret_d1", aggfunc="size").to_string())
        print((sub.pivot_table(index="洗盘深度%", columns=scene, values="ret_d1", aggfunc="mean") * 100).round(2).to_string())


# ────────────────────────── 波间条件触发溢价分析 ──────────────────────────

def cmd_between():
    """780簇波间「条件带出的涨停」负溢价分析.

    波间断板后的首板涨停, 其结构条件(主板非ST+昨日未涨停+前21日≥2连板)在簇内波间
    自动满足 → 每个都是条件本身带出的信号, 无需另找:
    - 真信号 = 波i+1首板(次日必板, D+1≈+10%);
    - 假信号 = 波间孤立单板(次日断), 统计 D+1 溢价(首板收盘买→D1收盘卖)与隔夜溢价.
    """
    bars, segs, clusters, waves, bounds = load_all()
    g = bars.groupby("sid", sort=False)
    bars["fb_d1"] = g["close_price"].shift(-1) / bars["close_price"] - 1
    bars["fb_d1_open"] = g["open_price"].shift(-1) / bars["close_price"] - 1
    # 单板日前一日K线实体%(依据展示用)
    bars["body_prev"] = (g["close_price"].shift(1) - g["open_price"].shift(1)) / bars["prev_close"] * 100
    bars_by_sid = {sid: grp for sid, grp in bars.groupby("sid")}

    rows = []
    for cid, wgrp in waves.sort_values(["cluster_id", "wave_no"]).groupby("cluster_id"):
        ws = wgrp.to_dict("records")
        bd = bars_by_sid[ws[0]["sid"]]
        for i in range(len(ws) - 1):
            a, b = ws[i], ws[i + 1]
            seg = bd[(bd["pos"] > a["last_pos"]) & (bd["pos"] < b["first_pos"])]
            for _, L in seg[seg["is_lim"] & (seg["streak"] == 1)].iterrows():
                rows.append({
                    "cluster_id": cid, "wave_i": i + 1,
                    "sid": int(L["sid"]), "code": L["vt_symbol"], "name": L["name"],
                    "date": L["trade_date"],
                    "gap_tb": int(b["first_pos"] - a["last_pos"]),
                    "after_prev": int(L["pos"] - a["last_pos"]),   # 距上波末板第几日
                    "before_next": int(b["first_pos"] - L["pos"]),  # 距下波(真)首板还有几日
                    "body_prev": L["body_prev"],
                    "d1": L["fb_d1"], "d1_open": L["fb_d1_open"],
                })
    mid = pd.DataFrame(rows)
    n_pairs = int((clusters["n_waves"] - 1).sum())
    has_mid = mid.groupby("cluster_id").size() if len(mid) else pd.Series(dtype=int)

    print(f"== 波间条件触发: {len(clusters)}簇 / 相邻波对 {n_pairs} / "
          f"含孤立单板簇 {len(has_mid)} ({len(has_mid)/len(clusters)*100:.0f}%) / 孤立单板总数 {len(mid)} ==")
    if not len(mid):
        return

    def _dist(s, name):
        s = s.dropna()
        print(f"  {name}: n={len(s)} 均值{s.mean()*100:+.2f}% 中位{s.median()*100:+.2f}% "
              f"负占比{(s < 0).mean()*100:.0f}% | <-2% {(s < -0.02).mean()*100:.0f}% "
              f"<-5% {(s < -0.05).mean()*100:.0f}% | >+2% {(s > 0.02).mean()*100:.0f}%")

    print("\n== 孤立单板(条件带出的假信号) D+1 溢价 ==")
    _dist(mid["d1"], "收盘买→D1收盘卖")
    _dist(mid["d1_open"], "收盘买→D1开盘卖(隔夜)")
    wf = bars.set_index([bars["sid"], bars["pos"]])["fb_d1"]
    wave_first_d1 = [wf.loc[(r["sid"], r["first_pos"])] for _, r in waves.iterrows()]
    print(f"  对照·真波首板(n={len(wave_first_d1)}): D+1均值 {np.mean(wave_first_d1)*100:+.2f}% (次日必板≈+10%)")

    mid["间隔类型"] = pd.cut(mid["gap_tb"], [0, 5.5, 20.5], labels=["快接≤5", "缓启6-20"])
    mid["距上波末板"] = pd.cut(mid["after_prev"], [0, 2.5, 5.5, 99], labels=["1-2日", "3-5日", "6日+"])
    mid["距下波首板"] = pd.cut(mid["before_next"], [0, 2.5, 5.5, 10.5, 99],
                              labels=["1-2日", "3-5日", "6-10日", "11日+"])
    mid["所在波间"] = np.where(mid["wave_i"] == 1, "波1→波2", "波2之后")

    def _agg(df, by):
        return df.groupby(by, observed=True).agg(
            n=("d1", "size"),
            D1均值=("d1", lambda s: round(s.mean() * 100, 2)),
            负占比=("d1", lambda s: round((s < 0).mean() * 100)),
            隔夜均值=("d1_open", lambda s: round(s.mean() * 100, 2)),
        ).to_string()

    for dim in ("间隔类型", "距上波末板", "距下波首板", "所在波间"):
        print(f"\n== 孤立单板 D+1 溢价 · 按{dim} ==")
        print(_agg(mid, dim))
    print("\n== 按 波间隔类型 × 距下波首板 [n / D1%] ==")
    print(mid.pivot_table(index="间隔类型", columns="距下波首板", values="d1", aggfunc="size").to_string())
    print((mid.pivot_table(index="间隔类型", columns="距下波首板", values="d1", aggfunc="mean") * 100).round(2).to_string())

    # ── 票例依据(逐票带特征) ──
    mid["date"] = pd.to_datetime(mid["date"]).dt.date
    show_cols = ["code", "name", "date", "wave_i", "after_prev", "before_next", "body_prev", "d1", "d1_open"]
    fmt = {"d1": lambda v: f"{v*100:+.1f}%", "d1_open": lambda v: f"{v*100:+.1f}%",
           "body_prev": lambda v: f"{v:+.1f}"}

    def _show(sub, title, n=12):
        print(f"\n== {title} ==")
        print(sub[show_cols].head(n).to_string(index=False, formatters=fmt))

    _show(mid.nsmallest(12, "d1"), "全量最差12票(按D1收盘)")
    _show(mid[mid["after_prev"] <= 2].nsmallest(12, "d1"), "最毒桶·距上波末板1-2日 最差12")
    _show(mid[(mid["d1_open"] > 0) & (mid["d1"] < 0)].nsmallest(12, "d1"), "背离·隔夜正/收盘负 典型12")
    _show(mid[mid["after_prev"] >= 6].nlargest(8, "d1"), "无害桶·距上波末板≥6日 最好8")

    out = "/app/w2s_v3_out/波间孤立单板.md"
    lines = [
        f"# 波间孤立单板(条件带出的假信号) 全量{len(mid)}例",
        "",
        "生成: w2s_v3_wave_research.py between · 2026-08-27",
        "口径: 780簇波间断板后首板(结构条件自动满足); D1%=单板收盘买→次日收盘卖; 隔夜%=次日开盘卖;",
        "昨实体%=单板前一日K线实体(阳正阴负); 排序=D1%升序(最差在前)。",
        "",
        "| 代码 | 名称 | 单板日 | 波间 | 距上波末板 | 距下波首板 | 昨实体% | D1% | 隔夜% |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for _, r in mid.sort_values("d1").iterrows():
        lines.append(
            f"| {r['code']} | {r['name']} | {r['date']} | 波{r['wave_i']}→波{r['wave_i'] + 1} "
            f"| {r['after_prev']}日 | {r['before_next']}日 | {r['body_prev']:+.1f} "
            f"| {r['d1'] * 100:+.1f} | {r['d1_open'] * 100:+.1f} |")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\n全量票例已导出: {out}")


# ────────────────────────── 同花顺四组条件验证 ──────────────────────────

THS_CONDS = {"补涨阴": "c_by", "补涨阳": "c_by2", "双板缓启": "c_dh",
             "弱转强": "c_rzq", "结构雷达": "c_g"}


def _ths_daily(bars):
    """主人四组同花顺条件的日线部分(全部为 D-1 昨日可观测口径), 挂列到 bars 上.

    口径:
      前20日/前4日连板 = 截至昨日(含昨日)窗口内出现过的最大连板数(streak的rolling max)
      前二/前三日涨跌幅 = 昨收/三(四)日前收-1 (含昨日的累计涨幅)
      昨日上影线% = (昨高 - max(昨开,昨收)) / 前日收
    四组(主板非ST宇宙已由load_bars保证):
      补涨阴   前20日连板>=3 + 昨收阴 + 前三日涨跌幅<6% + 昨上影线<4% + 昨涨跌幅>-9%
      补涨阳   前20日连板>=3 + 昨收阳 + 前二日涨跌幅<6% + 昨上影线<4%
      二板快接 前4日连板=2 + 昨收阴 + 昨涨跌幅<-3%
      弱转强   前20日连板>=3 + 昨日涨停 + 昨日开板次数>5 (c_rzq_daily为日线部分, opens由1m补)
    2026-08-28 终版四组(主人定稿: 高度门槛统一>=2, 快接阴/阳并入; 首板组统一加昨日未涨停):
      补涨阴   前20日连板>=2 + 昨收阴 + 前三日涨跌幅<6% + 昨上影线<4% + 昨涨跌幅>-9% + 昨日未涨停
      补涨阳   前20日连板>=2 + 昨收阳 + 前二日涨跌幅<6% + 昨上影线<4% + 昨日未涨停
      双板缓启 前20日连板=2 + 前4日连板<2 + 昨日未涨停 + 距上波顶回撤>4%
               (回撤=昨收/上波(≥2板段)最高价-1, cmd_ths补充)
      弱转强   前20日连板>=3 + 昨日涨停 + 昨日开板次数>5 (c_rzq_daily为日线部分, opens由1m补)
      结构雷达 前20日连板>=2 + 昨日未涨停 (看盘兜底, 不作买入条件)
      (c_kj/c_kj2 快接阴/阳保留作历史对照, 已被补涨阴/阳(>=2)吸收, 不在THS_CONDS)
    """
    g = bars.groupby("sid", sort=False)
    po = g["open_price"].shift(1)
    ph = g["high_price"].shift(1)
    pc1 = g["close_price"].shift(1)
    ppc = g["prev_close"].shift(1)
    bars["p_yin"] = (pc1 < po).fillna(False).astype(bool)
    bars["p_yang"] = (pc1 > po).fillna(False).astype(bool)
    bars["p_chg"] = pc1 / ppc - 1
    bars["p_ret2"] = pc1 / g["close_price"].shift(3) - 1
    bars["p_ret3"] = pc1 / g["close_price"].shift(4) - 1
    bars["p_ush"] = (ph - np.maximum(po, pc1)) / ppc
    bars["p_streak"] = g["streak"].shift(1)
    bars["p_ydate"] = g["trade_date"].shift(1)
    bars["prev_lim"] = g["is_lim"].shift(1).fillna(False).astype(bool)  # bool shift→object陷阱, 必须astype
    stk = bars["streak"].astype(float)
    bars["mx20"] = stk.groupby(bars["sid"], sort=False).transform(
        lambda s: s.shift(1).rolling(20, min_periods=1).max())
    bars["mx4"] = stk.groupby(bars["sid"], sort=False).transform(
        lambda s: s.shift(1).rolling(4, min_periods=1).max())
    # D0 触板执行列: 触板=high>=涨停价; 开盘即涨停(含一字)实盘排不到 → 保守排除
    bars["lim_px"] = np.round(bars["prev_close"] * 1.10 + 1e-9, 2)
    bars["touch"] = bars["high_price"] >= bars["lim_px"] - 1e-6
    bars["d0_open_lim"] = bars["open_price"] >= bars["lim_px"] - 1e-6
    bars["n1_open"] = g["open_price"].shift(-1)
    bars["n1_close"] = g["close_price"].shift(-1)
    base = bars["mx20"] >= 3
    base2 = bars["mx20"] >= 2
    # 首板组统一排除昨日涨停(主人2026-08-28验票发现: 横盘后单日涨停时 p_ret2 被 D-3 前高抵消,
    # 补涨阳会漏进「昨日涨停追二板」票, 如风范股份2026-08-18; 补涨阴昨收阴天然排除, 显式加保险)
    bars["c_by"] = base2 & bars["p_yin"] & (bars["p_ret3"] < 0.06) \
        & (bars["p_ush"] < 0.04) & (bars["p_chg"] > -0.09) & ~bars["prev_lim"]
    bars["c_by2"] = base2 & bars["p_yang"] & (bars["p_ret2"] < 0.06) & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]
    bars["c_kj"] = (bars["mx4"] == 2) & bars["p_yin"] & (bars["p_chg"] < -0.03) & ~bars["prev_lim"]
    bars["c_kj2"] = (bars["mx4"] == 2) & bars["p_yang"] & ~bars["prev_lim"]
    bars["c_rzq_daily"] = base & bars["prev_lim"]
    bars["c_dh"] = (bars["mx20"] == 2) & (bars["mx4"] < 2) & ~bars["prev_lim"]
    bars["c_g"] = base2 & ~bars["prev_lim"]
    # 通用条件「断板期夹板1~2次」(2026-08-28 定稿, 试盘活跃度):
    # 断板期 = 上波(≥2板段)末板之后、D0之前; 夹板数 = 期间孤立涨停日数(向量化=涨停累计差)
    nxt_lim = g["is_lim"].shift(-1).fillna(False).astype(bool)
    wave_end = bars["is_lim"] & (bars["streak"] >= 2) & ~nxt_lim
    lim_cum = bars["is_lim"].astype(int).groupby(bars["sid"], sort=False).cumsum()
    we_cum = pd.Series(np.where(wave_end, lim_cum, np.nan), index=bars.index)
    we_cum_ff = we_cum.groupby(bars["sid"], sort=False).ffill()
    prev_lim_cum = lim_cum - bars["is_lim"].astype(int)
    bars["n_lim_mid"] = prev_lim_cum - we_cum_ff
    bars.loc[we_cum_ff.isna(), "n_lim_mid"] = np.nan
    bars["c_mid"] = bars["n_lim_mid"].between(1, 2)
    for c in ("c_by", "c_by2", "c_kj", "c_kj2", "c_rzq_daily", "c_dh", "c_g"):
        bars[c] = bars[c].fillna(False).astype(bool)


def _open_counts(eng, bars):
    """1m分钟数据统计『昨日涨停日』盘中开板次数(触涨停→跌破涨停→再触的循环数).

    分钟级状态机(向量化): up=分钟high触板, dn=分钟low跌破且当分钟未触板;
    开板事件=处于开板且此前本日触过板, 连续开板段只计首分钟.
    完整性: 当日1m根数<200 视为缺数 → NaN.
    返回 {(sid, D0pos): opens}; 1m数据只覆盖2024-08后(2026全年, 2024/25零星).
    """
    cand = bars.loc[bars["prev_lim"] & bars["p_ydate"].notna(),
                    ["sid", "pos", "vt_symbol", "p_ydate"]].copy()
    cand["p_ydate"] = cand["p_ydate"].dt.date
    yrow = bars[["sid", "pos", "prev_close"]].rename(columns={"pos": "ypos", "prev_close": "y_pc"})
    cand["ypos"] = cand["pos"] - 1
    cand = cand.merge(yrow, on=["sid", "ypos"], how="left").dropna(subset=["y_pc"])
    cand["lim"] = np.round(cand["y_pc"] * 1.10 + 1e-9, 2)
    with eng.begin() as conn:
        cand[["vt_symbol", "p_ydate"]].drop_duplicates().to_sql(
            "tmp_lim_days", conn, index=False, if_exists="replace")
        m = pd.read_sql(
            "select m.vt_symbol, t.p_ydate as ydate, m.high_price h, m.low_price lo "
            "from stock_minute_bars m join tmp_lim_days t "
            "on m.vt_symbol = t.vt_symbol and m.trade_date = t.p_ydate "
            "where m.interval = '1m' order by m.vt_symbol, m.trade_date, m.bar_time", conn)
    if not len(m):
        return {}
    key = ["vt_symbol", "ydate"]
    cl = cand[["vt_symbol", "p_ydate", "lim"]].drop_duplicates(["vt_symbol", "p_ydate"])
    cl = cl.rename(columns={"p_ydate": "ydate"})
    m = m.merge(cl, on=key, how="inner")
    lim = m["lim"].to_numpy()
    m["_up"] = m["h"].to_numpy() >= lim - 1e-6
    m["_dn"] = (m["lo"].to_numpy() < lim - 1e-6) & ~m["_up"].to_numpy()
    gk = m.groupby(key, sort=False)
    touched = gk["_up"].cummax()
    prev_touched = touched.groupby([m["vt_symbol"], m["ydate"]], sort=False).shift(1).fillna(False)
    open_ev = m["_dn"] & prev_touched
    prev_ev = open_ev.groupby([m["vt_symbol"], m["ydate"]], sort=False).shift(1).fillna(False)
    m["_op"] = open_ev & ~prev_ev
    agg = m.groupby(key, sort=False).agg(opens=("_op", "sum"), nbars=("_up", "size")).reset_index()
    agg.loc[agg["nbars"] < 200, "opens"] = np.nan
    out = cand[["sid", "pos", "vt_symbol", "p_ydate"]].rename(columns={"p_ydate": "ydate"})
    out = out.merge(agg[["vt_symbol", "ydate", "opens"]], on=key, how="inner")
    print(f"[1m开板次数] 昨日涨停日候选 {len(cand):,} → 1m命中 {len(agg):,} 天次 "
          f"(开板>5占 {(agg['opens'] > 5).mean() * 100:.0f}%)")
    return dict(zip(zip(out["sid"], out["pos"]), out["opens"]))


def _ths_row(df):
    """单组触发集的执行统计行(均值/中位/胜率 三联, 所有收益相对买入价=涨停价)."""
    sealed = df[df["is_lim"]]
    broke = df[~df["is_lim"]]
    n_d1dn = int((df["n1_open"] <= np.round(df["close_price"] * 0.90 + 1e-9, 2) + 1e-6).sum())

    def mms(s):
        return f"{s.mean() * 100:+.2f}/{s.median() * 100:+.2f}/{(s > 0).mean() * 100:.0f}%"

    rows = [("触发n", f"{len(df)}",
             f"封板 {len(sealed)} ({len(sealed) / len(df) * 100:.0f}%) / 炸板 {len(broke)} ({len(broke) / len(df) * 100:.0f}%)")]
    if len(sealed):
        rows.append(("封板票 D1开盘卖", mms(sealed["r_d1o"]), f"D1再板 {sealed['n1_lim'].mean() * 100:.0f}%"))
        rows.append(("封板票 D1收盘卖", mms(sealed["r_d1c"]), ""))
    if len(broke):
        rows.append(("炸板票 D0尾盘卖", mms(broke["r_d0c"]), ""))
        rows.append(("炸板票 D1开盘卖", mms(broke["r_d1o"]), ""))
        rows.append(("炸板票 D1收盘卖", mms(broke["r_d1c"]), ""))
    rows.append(("合计 D1开盘卖", mms(df["r_d1o"]), ""))
    rows.append(("合计 D1收盘卖", mms(df["r_d1c"]), f"D1开盘即跌停 {n_d1dn} 笔"))
    return rows


def cmd_ths():
    """主人四组同花顺条件验证: ①V3研究票覆盖率(含未命中原因) ②全市场触发的详细回测报表."""
    bars, segs, clusters, waves, bounds = load_all()
    _ths_daily(bars)
    # 缓启组背离度条件(2026-08-28 主人定稿): 昨收距上波(≥2板段)最高价回撤>4%, 剔掉52%贴顶低质票
    big = segs[segs["height"] >= 2].sort_values(["sid", "last_pos"])
    big_by = {sid: grp[["last_pos", "high_price"]].to_numpy()
              for sid, grp in big.groupby("sid", sort=False)}
    pull = np.full(len(bars), np.nan)
    for i, (s, p, pc) in enumerate(zip(bars["sid"], bars["pos"], bars["prev_close"])):
        arr = big_by.get(s)
        if arr is None or pc != pc:
            continue
        li = arr[:, 0].searchsorted(p, side="left")
        if li == 0:
            continue
        pull[i] = pc / arr[li - 1, 1] - 1
    bars["pull_top"] = pull
    bars["c_dh"] = bars["c_dh"] & (bars["pull_top"] < -0.04)
    g = bars.groupby("sid", sort=False)
    bars["n1_lim"] = g["is_lim"].shift(-1).fillna(False).astype(bool)
    from sqlalchemy import create_engine
    eng = create_engine(os.environ["DATABASE_URL"])
    opens_map = _open_counts(eng, bars)
    bars["opens"] = [opens_map.get((s, p), np.nan) for s, p in zip(bars["sid"], bars["pos"])]
    bars["c_rzq"] = bars["c_rzq_daily"] & (bars["opens"] > 5)

    wave_keys = set(zip(waves["sid"], waves["first_pos"]))
    rzq2 = bars.loc[bars["c_rzq"], ["sid", "pos"]]
    rzq_wave_keys = set(zip(rzq2["sid"], rzq2["pos"] - 1))   # 弱转强触发的昨日=波首板

    # ── ① 覆盖验证: 1798波首板, 昨日条件是否满足(波首板日必触板) ──
    need = ["c_by", "c_by2", "c_kj", "c_kj2", "c_dh", "c_g", "c_rzq_daily", "opens", "mx20", "mx4",
            "p_yin", "p_yang", "p_ush", "p_ret2", "p_ret3", "p_chg", "touch", "d0_open_lim"]
    wv = waves[["cluster_id", "sid", "wave_no", "height", "first_pos", "gap_prev_tb"]].merge(
        bars[["sid", "pos"] + need], left_on=["sid", "first_pos"], right_on=["sid", "pos"], how="left")
    wv["cov_fb3"] = wv[["c_by", "c_by2", "c_dh"]].any(axis=1)
    wv["cov_rzq"] = [(s, p) in rzq_wave_keys for s, p in zip(wv["sid"], wv["first_pos"])]
    wv["cov_any"] = wv["cov_fb3"] | wv["cov_rzq"]
    n_wv = len(wv)
    print("=" * 96)
    print(f"== ① 覆盖验证: {n_wv} 波(首板口径) / {len(clusters)} 簇 ==")
    for name, c in list(THS_CONDS.items())[:3] + [("结构雷达", "c_g")]:
        sub = wv[wv[c]]
        print(f"  {name}: 波首板命中 {len(sub)} ({len(sub) / n_wv * 100:.0f}%)  "
              f"其中一字无法买入 {int(sub['d0_open_lim'].sum())}")
    rzq_hit = wv[wv["cov_rzq"]]
    print(f"  弱转强(开板>5, 仅1m覆盖期): 波二板命中 {len(rzq_hit)} ({len(rzq_hit) / n_wv * 100:.0f}%)")
    print(f"  前三组并集: {int(wv['cov_fb3'].sum())} ({wv['cov_fb3'].mean() * 100:.0f}%) | "
          f"任一组含弱转强: {int(wv['cov_any'].sum())} ({wv['cov_any'].mean() * 100:.0f}%)")
    cl_cov = wv.groupby("cluster_id")["cov_any"].any()
    print(f"  簇覆盖: {int(cl_cov.sum())}/{len(cl_cov)} ({cl_cov.mean() * 100:.0f}%)")

    unc = wv[~wv["cov_any"]].copy()
    if len(unc):
        print(f"\n  -- 未覆盖波 {len(unc)} 个: 卡在哪条(非互斥, 各条件独立计数) --")
        print(f"  高度不足: 前20日连板<3 且 前4日连板!=2 "
              f"{int(((unc['mx20'] < 3) & (unc['mx4'] != 2)).sum())}")
        print(f"  昨日平盘(非阴非阳): {int((~unc['p_yin'] & ~unc['p_yang']).sum())}")
        print(f"  阴线侧缺件: 上影>=4% {int((unc['p_yin'] & (unc['p_ush'] >= 0.04)).sum())} | "
              f"前三日涨幅>=6% {int((unc['p_yin'] & (unc['p_ret3'] >= 0.06)).sum())} | "
              f"昨跌幅<=-9% {int((unc['p_yin'] & (unc['p_chg'] <= -0.09)).sum())}")
        print(f"  阳线侧缺件: 上影>=4% {int((unc['p_yang'] & (unc['p_ush'] >= 0.04)).sum())} | "
              f"前二日涨幅>=6% {int((unc['p_yang'] & (unc['p_ret2'] >= 0.06)).sum())}")
        print(f"  快接缺件(收阴但): 昨跌幅>=-3% {int((unc['p_yin'] & (unc['p_chg'] >= -0.03) & (unc['mx4'] == 2)).sum())} | "
              f"窗口没罩住双板(mx20>=3以外的双板断口>4日) "
              f"{int(((unc['mx4'] != 2) & (unc['mx20'] < 3) & (unc['p_chg'] < -0.03)).sum())}")
        gapbins = [-2, 0.5, 1.5, 2.5, 3.5, 5.5, 10.5, 15.5, 20.5, 999]
        gaplabs = ["首波", "1", "2", "3", "4-5", "6-10", "11-15", "16-20", ">20"]
        wv["gap_b"] = pd.cut(wv["gap_prev_tb"].fillna(-1), gapbins, labels=gaplabs)
        unc["gap_b"] = pd.cut(unc["gap_prev_tb"].fillna(-1), gapbins, labels=gaplabs)
        tab = pd.DataFrame({"未覆盖": unc.groupby("gap_b", observed=True).size(),
                            "全体": wv.groupby("gap_b", observed=True).size()})
        tab["未覆盖率%"] = (tab["未覆盖"] / tab["全体"] * 100).round(0)
        print("\n  未覆盖波 × 断板间隔分布(对照全体):")
        print(tab.fillna(0).to_string())

    # 修正口径: 首波数学上不可覆盖(首波前20日内若有≥2板早被链入簇) → 正确分母=非首波1018
    wv2 = wv[wv["wave_no"] > 1]
    print(f"\n  [修正口径] 非首波分母 {len(wv2)}: 前三组 {int(wv2['cov_fb3'].sum())} "
          f"({wv2['cov_fb3'].mean() * 100:.0f}%) | 含弱转强 {int(wv2['cov_any'].sum())} "
          f"({wv2['cov_any'].mean() * 100:.0f}%)")
    unc2 = wv2[~wv2["cov_any"]]
    n_dual = int(((unc2["mx20"] < 3) & (unc2["mx4"] != 2)).sum())
    print(f"  非首波未覆盖 {len(unc2)}: 其中双板簇缓启缺口(上波仅2板且断口>4日, 快接窗口外) "
          f"{n_dual} ({n_dual / len(unc2) * 100:.0f}%)")

    # 放宽实验: 补涨阴/阳的 前20日连板>=3 → >=2 (接住双板簇缓启)
    alt_yin = (wv2["mx20"] >= 2) & wv2["p_yin"] & (wv2["p_ret3"] < 0.06) \
        & (wv2["p_ush"] < 0.04) & (wv2["p_chg"] > -0.09)
    alt_yang = (wv2["mx20"] >= 2) & wv2["p_yang"] & (wv2["p_ret2"] < 0.06) & (wv2["p_ush"] < 0.04)
    alt_any = (alt_yin | alt_yang | wv2["c_kj"] | wv2["cov_rzq"])
    print(f"  [放宽实验] 补涨阴/阳改 前20日连板>=2: 覆盖 {int(alt_any.sum())} "
          f"({alt_any.mean() * 100:.0f}%)  (原 {int(wv2['cov_any'].sum())})")

    # 票级覆盖(主人核心指标): 四组精准 / 四组×试盘(夹板) / 含结构雷达
    cond_ok_cov = bars["touch"] & ~bars["d0_open_lim"]
    v3_stocks = set(waves.merge(
        bars[["sid", "vt_symbol"]].drop_duplicates(), on="sid")["vt_symbol"])
    hit6 = np.zeros(len(bars), dtype=bool)
    hit6m = np.zeros(len(bars), dtype=bool)
    for c in ("c_by", "c_by2", "c_dh", "c_rzq"):
        hit6 |= bars[c].to_numpy()
        hit6m |= (bars[c] & bars["c_mid"]).to_numpy()
    tg6 = set(bars.loc[hit6 & cond_ok_cov, "vt_symbol"])
    tg6m = set(bars.loc[hit6m & cond_ok_cov, "vt_symbol"])
    tgg = set(bars.loc[bars["c_g"] & cond_ok_cov, "vt_symbol"])
    print(f"  [票级] V3 {len(v3_stocks)} 只: 四组精准 {len(v3_stocks & tg6)} "
          f"({len(v3_stocks & tg6) / len(v3_stocks) * 100:.1f}%) | "
          f"四组×试盘(夹板1~2) {len(v3_stocks & tg6m)} "
          f"({len(v3_stocks & tg6m) / len(v3_stocks) * 100:.1f}%) | "
          f"+结构雷达 {len(v3_stocks & (tg6 | tgg))} "
          f"({len(v3_stocks & (tg6 | tgg)) / len(v3_stocks) * 100:.1f}%)")

    # ── ② 全市场触发回测: 昨日满足条件 + 今日触板, 买入价=涨停价 ──
    cond_ok = bars["touch"] & ~bars["d0_open_lim"] & bars["n1_close"].notna() & bars["n1_open"].notna()
    print("\n" + "=" * 96)
    print("== ② 全市场触发回测(昨日满足条件 + 今日触板买入=涨停价; 收益=均值/中位/胜率) ==")
    all_t = []
    for name, c in THS_CONDS.items():
        tg = bars[bars[c] & cond_ok].copy()
        tg["buy"] = tg["lim_px"]
        tg["r_d1o"] = tg["n1_open"] / tg["buy"] - 1
        tg["r_d1c"] = tg["n1_close"] / tg["buy"] - 1
        tg["r_d0c"] = tg["close_price"] / tg["buy"] - 1
        tg["grp"] = name
        tg["is_wave1"] = [(s, p) in wave_keys for s, p in zip(tg["sid"], tg["pos"])]
        all_t.append(tg)
        n_ow = int((bars[c] & bars["touch"] & bars["d0_open_lim"]).sum())
        print(f"\n── {name} (另: 开盘即涨停无法买入 {n_ow} 笔未计入) ──")
        for k, v, extra in _ths_row(tg):
            print(f"  {k:20s} {v:44s} {extra}")
        if name == "弱转强":   # 结构拆分: 昨日首板(断板后重启) vs 昨日中继
            for lbl, mk in (("昨日=首板", tg["p_streak"] == 1), ("昨日=连板中继", tg["p_streak"] >= 2)):
                sub = tg[mk]
                if len(sub):
                    print(f"    [{lbl}] n={len(sub)} 封板{sub['is_lim'].mean() * 100:.0f}% "
                          f"D1收 {sub['r_d1c'].mean() * 100:+.2f}% 胜率{(sub['r_d1c'] > 0).mean() * 100:.0f}%")
        sub = tg[tg["is_wave1"]]
        if len(sub):
            print(f"  其中V3波首板: {len(sub)} 笔 ({len(sub) / len(tg) * 100:.0f}%) "
                  f"D1收 {sub['r_d1c'].mean() * 100:+.2f}%")
        # 通用试盘条件(断板期夹板1~2次)对照行
        tm = tg[tg["c_mid"]]
        if len(tm):
            print(f"  [{name}·试盘] n={len(tm)} 封板{tm['is_lim'].mean() * 100:.0f}% "
                  f"D1开 {tm['r_d1o'].mean() * 100:+.2f}% D1收 {tm['r_d1c'].mean() * 100:+.2f}% "
                  f"胜率{(tm['r_d1c'] > 0).mean() * 100:.0f}%")
    t = pd.concat(all_t, ignore_index=True)
    t["year"] = t["trade_date"].dt.year

    # 分年 × 组 的 D1收盘口径
    print("\n== 分年 × 组 (D1收盘卖: 均值%/胜率%) ==")
    yr = t.groupby(["grp", "year"]).apply(
        lambda s: pd.Series({"n": len(s), "封板%": round(s["is_lim"].mean() * 100),
                             "D1开%": round(s["r_d1o"].mean() * 100, 2),
                             "D1收%": round(s["r_d1c"].mean() * 100, 2),
                             "胜率%": round((s["r_d1c"] > 0).mean() * 100)}), include_groups=False)
    print(yr.to_string())

    # 开板次数阈值验证(弱转强日线触发集内, 1m覆盖期)
    rz = bars[bars["c_rzq_daily"] & cond_ok & bars["opens"].notna()].copy()
    if len(rz):
        rz["r_d1c"] = rz["n1_close"] / rz["lim_px"] - 1
        rz["ob"] = pd.cut(rz["opens"], [-1, 0.5, 2.5, 5.5, 99], labels=["0(硬板)", "1-2", "3-5", ">5"])
        print(f"\n== 开板次数阈值验证 (昨日涨停+前20日≥3板触发集, 1m覆盖 n={len(rz)}) ==")
        print(rz.groupby("ob", observed=True).apply(
            lambda s: pd.Series({"n": len(s), "封板%": round(s["is_lim"].mean() * 100),
                                 "D1收%": round(s["r_d1c"].mean() * 100, 2),
                                 "胜率%": round((s["r_d1c"] > 0).mean() * 100)}),
            include_groups=False).to_string())

    # 放宽版回测: 前20日连板>=3 → >=2 (覆盖率25%→53%的代价/收益)
    print("\n== 放宽版回测(前20日连板>=3 → >=2) ==")
    extra_t = []
    for name, cmask in (
        ("补涨阴(≥2板)", (bars["mx20"] >= 2) & bars["p_yin"] & (bars["p_ret3"] < 0.06)
            & (bars["p_ush"] < 0.04) & (bars["p_chg"] > -0.09)),
        ("补涨阳(≥2板)", (bars["mx20"] >= 2) & bars["p_yang"] & (bars["p_ret2"] < 0.06)
            & (bars["p_ush"] < 0.04)),
    ):
        tg = bars[cmask.fillna(False).astype(bool) & cond_ok].copy()
        tg["buy"] = tg["lim_px"]
        tg["r_d1o"] = tg["n1_open"] / tg["buy"] - 1
        tg["r_d1c"] = tg["n1_close"] / tg["buy"] - 1
        tg["r_d0c"] = tg["close_price"] / tg["buy"] - 1
        tg["is_wave1"] = [(s, p) in wave_keys for s, p in zip(tg["sid"], tg["pos"])]
        extra_t.append((name, tg))
        print(f"\n── {name} ──")
        for k, v, extra in _ths_row(tg):
            print(f"  {k:20s} {v:44s} {extra}")
        sub = tg[tg["is_wave1"]]
        if len(sub):
            print(f"  其中V3波首板: {len(sub)} 笔 ({len(sub) / len(tg) * 100:.0f}%) "
                  f"D1收 {sub['r_d1c'].mean() * 100:+.2f}%")

    # ── ③ 详细数据: 胜率矩阵 + 严格卖出(跌停顺延) + 分布分位 + 炸板深度 + 期望分解 ──
    print("\n" + "=" * 96)
    print("== ③ 详细数据: 胜率矩阵 + 严格卖出(D1开盘跌停顺延到能卖出日) + 分布 + 炸板深度 ==")
    idx = {}
    for sid, grp in bars.groupby("sid", sort=False):
        idx[sid] = {
            "p2i": {int(p): i for i, p in enumerate(grp["pos"])},
            "o": grp["open_price"].to_numpy(), "c": grp["close_price"].to_numpy(),
            "pc": grp["prev_close"].to_numpy(),
        }

    def _strict(sid, pos0):
        """严格卖出价: D1开盘跌停(卖不出)则当日盘中打开按收盘、全天跌停顺延, 最多D5."""
        bd = idx.get(sid)
        if bd is None:
            return np.nan, 0
        for d in range(1, 6):
            i = bd["p2i"].get(int(pos0) + d)
            if i is None:
                return np.nan, d - 1
            dn = round(bd["pc"][i] * 0.90 + 1e-9, 2)
            if bd["o"][i] > dn + 1e-6:
                return bd["o"][i], d
            if bd["c"][i] > dn + 1e-6:
                return bd["c"][i], d
        i = bd["p2i"].get(int(pos0) + 5)
        return (bd["o"][i], 5) if i is not None else (np.nan, 5)

    for name, tg in [(x["grp"].iloc[0], x) for x in all_t] + extra_t:
        sealed, broke = tg[tg["is_lim"]], tg[~tg["is_lim"]]
        st = [_strict(s, p) for s, p in zip(tg["sid"], tg["pos"])]
        r_st = pd.Series([px / b - 1 if pd.notna(px) else np.nan for (px, _), b in zip(st, tg["buy"])])
        dly = sum(1 for _, d in st if d > 1)

        def row(label, s):
            return f"  {label:14s} n={len(s):5d}  胜率{(s > 0).mean() * 100:3.0f}%  " \
                   f"均值{s.mean() * 100:+6.2f}%  中位{s.median() * 100:+6.2f}%"

        print(f"\n── {name} (n={len(tg)}, 封板{len(sealed)} 炸板{len(broke)}) ──")
        print(row("封板·D1开", sealed["r_d1o"]))
        print(row("封板·D1收", sealed["r_d1c"]))
        print(row("炸板·D1开", broke["r_d1o"]))
        print(row("炸板·D1收", broke["r_d1c"]))
        print(row("全体·D1开", tg["r_d1o"]))
        print(row("全体·D1收", tg["r_d1c"]))
        print(row("全体·严格卖出", r_st.dropna()) + f"   (D1跌停顺延 {dly} 笔)")
        q = tg["r_d1c"].quantile([0.1, 0.25, 0.5, 0.75, 0.9]) * 100
        print(f"  D1收分布分位%: P10 {q[0.1]:+.1f} | P25 {q[0.25]:+.1f} | P50 {q[0.5]:+.1f} "
              f"| P75 {q[0.75]:+.1f} | P90 {q[0.9]:+.1f} | ≤-10%占 {(tg['r_d1c'] <= -0.10).mean() * 100:.0f}%")
        pc, pb = len(sealed) / len(tg), len(broke) / len(tg)
        ec, eb = sealed["r_d1c"].mean(), broke["r_d1c"].mean()
        print(f"  期望分解(D1收): 封板 {pc * 100:.0f}%×{ec * 100:+.2f} + 炸板 {pb * 100:.0f}%×{eb * 100:+.2f} "
              f"= {(pc * ec + pb * eb) * 100:+.2f}%")
        broke = broke.copy()
        broke["深度"] = pd.cut(broke["r_d0c"], [-0.11, -0.06, -0.03, -0.01, 0.001],
                               labels=["深炸>6%", "炸3-6%", "炸1-3%", "浅炸<1%"])
        dz = broke.groupby("深度", observed=True).apply(
            lambda s: pd.Series({"n": len(s), "D1收%": round(s["r_d1c"].mean() * 100, 2),
                                 "胜率%": round((s["r_d1c"] > 0).mean() * 100),
                                 "严格%": round(s["r_d0c"].mean() * 100, 2)}), include_groups=False)
        print("  炸板深度(D0收盘距涨停价回落):")
        print(dz.to_string())

    # ── ④ 整体平均: 卖法对比(D1开/D1收/D2-D10持有/板留断走) + 封板票后续修复 ──
    print("\n" + "=" * 96)
    print("== ④ 整体平均收益: 卖法对比 + 封板票的后续 ==")

    def _fut(sid, pos0, n):
        bd = idx.get(sid)
        if bd is None:
            return np.nan
        i = bd["p2i"].get(int(pos0) + n)
        return bd["c"][i] if i is not None else np.nan

    def _banhold(sid, pos0):
        """板留断走: D1起收盘涨停继续持有, 断板日收盘卖出(≤20日)."""
        bd = idx.get(sid)
        if bd is None:
            return np.nan, 0
        for d in range(1, 21):
            i = bd["p2i"].get(int(pos0) + d)
            if i is None:
                j = bd["p2i"].get(int(pos0) + d - 1)
                return (bd["c"][j], d - 1) if j is not None else (np.nan, 0)
            lim = round(bd["pc"][i] * 1.10 + 1e-9, 2)
            if abs(bd["c"][i] - lim) > 1e-6:
                return bd["c"][i], d
        i = bd["p2i"].get(int(pos0) + 20)
        return bd["c"][i], 20

    def _st(s):
        return f"{s.mean() * 100:+.2f}/{s.median() * 100:+.2f}/{(s > 0).mean() * 100:.0f}%"

    for name, tg in [(x["grp"].iloc[0], x) for x in all_t] + extra_t:
        print(f"\n── {name} (n={len(tg)}) 均值/中位/胜率, 全部相对买入价=涨停价 ──")
        print(f"  {'D1开盘卖':10s} {_st(tg['r_d1o'])}")
        print(f"  {'D1收盘卖':10s} {_st(tg['r_d1c'])}")
        for n in (2, 3, 5, 10):
            s = pd.Series([_fut(s_, p_, n) for s_, p_ in zip(tg["sid"], tg["pos"])])
            s = s / tg["buy"].to_numpy() - 1
            print(f"  {'D%d收盘卖' % n:10s} {_st(s.dropna())}  n={int(s.notna().sum())}")
        bh = [_banhold(s_, p_) for s_, p_ in zip(tg["sid"], tg["pos"])]
        rbh = pd.Series([px / b - 1 if pd.notna(px) else np.nan
                         for (px, _), b in zip(bh, tg["buy"])]).dropna()
        hold_d = pd.Series([d for _, d in bh])
        print(f"  {'板留断走':10s} {_st(rbh)}  平均持有{hold_d.mean():.1f}日")
        sealed = tg[tg["is_lim"]]
        for lbl, mk in (("D1再板", sealed["n1_lim"].fillna(False)),
                        ("D1未再板", ~sealed["n1_lim"].fillna(False))):
            sub = sealed[mk]
            if not len(sub):
                continue
            s3 = pd.Series([_fut(s_, p_, 3) for s_, p_ in zip(sub["sid"], sub["pos"])])
            s5 = pd.Series([_fut(s_, p_, 5) for s_, p_ in zip(sub["sid"], sub["pos"])])
            s3 = (s3 / sub["buy"].to_numpy() - 1).dropna()
            s5 = (s5 / sub["buy"].to_numpy() - 1).dropna()
            print(f"  封板·{lbl}: n={len(sub)} D1收{_st(sub['r_d1c'])}"
                  + (f" D3收{_st(s3)}" if len(s3) else "")
                  + (f" D5收{_st(s5)}" if len(s5) else ""))

    # 触发明细导出(供翻票例)
    out = "/app/w2s_v3_out/同花顺终版触发明细.md"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    lines = ["# 同花顺终版四组条件 · 全市场触发明细", "",
             "生成: w2s_v3_wave_research.py ths · 2026-08-28 终版(补涨阴/阳>=2 + 缓启背离 + 弱转强 + 结构雷达)",
             "", "买入=触板时涨停价; 开盘即涨停已排除; 收益相对涨停价。", ""]
    for name in THS_CONDS:
        sub = t[t["grp"] == name].sort_values("r_d1c")
        lines += [f"## {name} (n={len(sub)}, D1收盘最差在前)", "",
                  "| 代码 | 名称 | D0 | 封板 | D1开% | D1收% | V3波首板 |", "|---|---|---|---|---|---|---|"]
        for _, r in sub.iterrows():
            lines.append(f"| {r['vt_symbol']} | {r['name']} | {r['trade_date'].strftime('%Y-%m-%d')} "
                         f"| {'封' if r['is_lim'] else '炸'} | {r['r_d1o'] * 100:+.1f} "
                         f"| {r['r_d1c'] * 100:+.1f} | {'✓' if r['is_wave1'] else ''} |")
        lines.append("")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\n全量触发明细已导出: {out}")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "explore"
    if cmd == "explore":
        cmd_explore()
    elif cmd == "case":
        cmd_case(sys.argv[2])
    elif cmd == "export":
        cmd_export(sys.argv[2] if len(sys.argv) > 2 else "/app/w2s_v3_out")
    elif cmd == "verify":
        cmd_verify()
    elif cmd == "optimize":
        cmd_optimize()
    elif cmd == "position":
        cmd_position()
    elif cmd == "history":
        cmd_history()
    elif cmd == "deep":
        cmd_deep()
    elif cmd == "between":
        cmd_between()
    elif cmd == "ths":
        cmd_ths()
    else:
        raise SystemExit(f"unknown cmd: {cmd}")


if __name__ == "__main__":
    main()
