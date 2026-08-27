# -*- coding: utf-8 -*-
"""趋势弱转强V3 —— 「≥2板断板 → 20交易日内再现≥2板」行情簇研究与波次切分事实源.

用法(容器内):
    python 量化因子研究/低吸研究/scripts/w2s_v3_wave_research.py explore      # 构建样本并打印总体统计
    python 量化因子研究/低吸研究/scripts/w2s_v3_wave_research.py export       # 按 规律组/YYYY-MM.csv 导出
    python 量化因子研究/低吸研究/scripts/w2s_v3_wave_research.py case 平潭发展 # 打印单票完整波次结构

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


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "explore"
    if cmd == "explore":
        cmd_explore()
    elif cmd == "case":
        cmd_case(sys.argv[2])
    elif cmd == "export":
        cmd_export(sys.argv[2] if len(sys.argv) > 2 else "/app/w2s_v3_out")
    else:
        raise SystemExit(f"unknown cmd: {cmd}")


if __name__ == "__main__":
    main()
