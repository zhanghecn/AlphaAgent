# -*- coding: utf-8 -*-
"""口诀逐条重演引擎v2(koujue_derive): 13条全量——每条单独走一遍当年发现它的研究路径。

七步(v2·分支组版, 严格按口诀诞生管线的原始纪律):
  1 池基线 → 2 单腿全谱(锚定腿可发现性验证)
  3 锚窗跨档精修(目标=分支矩阵质量——肥子格(均×ln n, 均值封顶13=walk-forward R6
  天花板)Top3和−毒格罚; 当年人工把「贴零档」修成「<1」的跨档扩展即此步)
  4 分支矩阵检测(形态轴对: 开盘×今开/换手×今开/开盘×开盘; 肥子格n≥8;
  区域生长=并邻格不稀释)
  5 每分支按人工纪律收口: 胜率≥60%剔3>0即收; 未过→差票过滤腿拯救(含入/排除/
  姿态/2D过滤格, 取救活且留票最多的); 过了→边界洞检验式精修(±扰动找剔3最优,
  纪律与n≥8保持)
  6 分支组并集纪律终检(n≥10胜≥60%剔3>0) → 7 对照人工定义(tag命中集Jaccard)

核心命题(v1实证): 口诀基本单位=分支组——A1/B1/B2/C3皆双分支并集,
中间毒带被行为逻辑排除; 单格重演在结构上永远对不齐口诀。
era对齐定型段: 强市口诀2023-01起 / 弱市口诀2020-08~2023-08。
"""
import math
from collections import Counter

import numpy as np
import pandas as pd

from alphaagent.server.services.high_relay import contracts as C
from alphaagent.server.services.high_relay.pool import tag_scheme, tag_weak

pd.set_option("display.width", 250)

CSV = "量化因子研究/高位接力/四进五全量明细.csv"
LIVE_POOLS = ("二接三阳", "二接三阴", "三接四阳", "三接四阴")

OPEN_BINS = [("低开", -99, 0), ("贴零", 0, 3), ("温开", 3, 7), ("强开", 7, 9.5), ("一字", 9.5, 99)]
TODAY_BINS = [("低开", -99, 0), ("平开", 0, 3), ("温开", 3, 6), ("强开", 6, 9.5)]
DIMS = {  # 数值维(加腿/排除候选); "三换-二换"=派生关系腿(K4缩量承接)
    "b1开盘%": OPEN_BINS,
    "b2开盘%": OPEN_BINS,
    "b3开盘%": OPEN_BINS,
    "b1换手%": [("<5", 0, 5), ("5~12", 5, 12), (">12", 12, 999)],
    "b2换手%": [("<5", 0, 5), ("5~12", 5, 12), ("12~20", 12, 20), (">20", 20, 999)],
    "b3换手%": [("<5", 0, 5), ("5~10", 5, 10), ("10~15", 10, 15), ("15~20", 15, 20), (">20", 20, 999)],
    "地基涨跌%": [("<1", -99, 1), ("1~3", 1, 3), ("≥3", 3, 999)],
    "首10日涨幅%": [("<10", 0, 10), ("10~20", 10, 20), ("≥20", 20, 9999)],
    "前波60日最高板": [("=0", -0.5, 0.5), ("1~2", 0.5, 2.5), ("≥3", 2.5, 99)],
    "距60日新高%": [("<-8", -99, -8), ("≥-8", -8, 999)],
    "买入开盘%": TODAY_BINS,
    "锚位%": [("<3", -99, 3), ("3~5", 3, 5), ("≥5", 5, 999)],
    "锚距": [("≤3", -99, 3), (">3", 3, 999)],
    "三换-二换": [("缩量", -999, 0), ("放量", 0, 999)],
}
POSES = ("站线上", "骑线", "贴线", "掉线下")
# 分支矩阵轴(开盘五档粗轴; today三粒度——粗轴养分支n, 细轴看A2今开7~8.5人工细窗,
# 弱开三档看C1块结构[b1强∪一字×今开低∪平=2×2块, 单格n<8])
TODAY_WEAK = [(-99, 3), (3, 6), (6, 9.5)]
TODAY_COARSE = [(-99, 0), (0, 3), (3, 6), (6, 9.5)]
TODAY_FINE = [(-99, 0), (0, 3), (3, 5), (5, 7), (7, 8.5), (8.5, 9.5)]
TODAY_AXES = (TODAY_WEAK, TODAY_COARSE, TODAY_FINE)
MAT_AXES = {
    "b1开盘%": [(-99, 0), (0, 3), (3, 7), (7, 9.5), (9.5, 99)],
    "b2开盘%": [(-99, 0), (0, 3), (3, 7), (7, 9.5), (9.5, 99)],
    "b3开盘%": [(-99, 0), (0, 3), (3, 7), (7, 9.5), (9.5, 99)],
    "买入开盘%": TODAY_COARSE,
    "b1换手%": [(0, 5), (5, 12), (12, 999)],
    "b2换手%": [(0, 5), (5, 12), (12, 20), (20, 999)],
    "b3换手%": [(0, 5), (5, 10), (10, 15), (15, 20), (20, 999)],
    "三换-二换": [(-999, 0), (0, 999)],
}
# 锚窗精修/分支窗精修的边界候选(人工常用边界∪档界数字)
BOUND_POOL = [-99.0, -8.0, -3.0, -2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0, 3.0, 5.0,
              6.0, 7.0, 8.5, 9.5, 10.0, 12.0, 15.0, 20.0, 999.0]
# 2D过滤格候选(C2两个不碰的交互形态 / A2假锁: 板弱(b1<3)却放量(vol2≥5)≠真锁仓)
EXCL_2D = [
    (("地基涨跌%", (1.0, 3.0)), ("买入开盘%", (-99.0, 7.0))),
    (("锚位%", (-2.0, 0.0)), ("锚距", (-99.0, 7.0))),
    (("b1开盘%", (-99.0, 3.0)), ("b2换手%", (5.0, 999.0))),
]
AVG_CAP = 13.0   # 质量公式均值封顶(walk-forward R6: 训练窗均值>13样本外全灭)
# 一板/换手交互过滤器(管线层3原步骤): 格子本身剔3不正时, 加一条人工语言窗再判肥
# ——A1分支2(b1平×今开温 24笔剔3-1.4)正是靠 vol2<12 交互才成格(→10笔80%剔3+5.0)
INTERACT = [
    ("b1换手%", (0, 12)), ("b2换手%", (0, 12)), ("b2换手%", (0, 20)),
    ("b3换手%", (0, 15)), ("b3换手%", (0, 20)),
    ("b1开盘%", (-99, 1)), ("b1开盘%", (-99, 3)),
    ("地基涨跌%", (-99, 1)), ("首10日涨幅%", (0, 10)),
    ("前波60日最高板", (-0.5, 0.5)), ("距60日新高%", (-8, 999)),
]


class Ctx:
    """单条口诀重演上下文: era+池过滤后的df + 列/格mask缓存 + E3数组。"""

    def __init__(self, df):
        self.df = df.reset_index(drop=True)
        self.e3 = self.df["E3%"].to_numpy(float)
        self.pose = self.df["地基姿态"].to_numpy()
        self._col = {}
        self._mask = {}

    def col(self, dim):
        if dim not in self._col:
            if dim == "三换-二换":
                self._col[dim] = (self.df["b3换手%"].astype(float)
                                  - self.df["b2换手%"].astype(float)).to_numpy()
            else:
                self._col[dim] = self.df[dim].astype(float).to_numpy()
        return self._col[dim]

    def m(self, dim, rng):
        key = (dim, rng)
        if key not in self._mask:
            a = self.col(dim)
            self._mask[key] = (a >= rng[0]) & (a < rng[1])
        return self._mask[key]

    def cover(self, dim):  # 非NaN数(二三接池的b3列为NaN自动淘汰该维)
        key = (dim, "cover")
        if key not in self._mask:
            self._mask[key] = np.isfinite(self.col(dim))
        return self._mask[key]

    def st(self, mask, cheap=False):
        v = self.e3[mask]
        n = len(v)
        if n == 0:
            return dict(n=0, avg=None, win=None, t3=None)
        return dict(n=n, avg=float(v.mean()), win=float((v > 0).mean()),
                    t3=None if cheap else float(np.sort(v)[:-3].mean() if n > 3 else v.mean()))


def fmt(s):
    if s["n"] == 0:
        return "0笔"
    t3 = f" 剔3{s['t3']:+.1f}" if s["t3"] is not None else ""
    return f"{s['n']}笔 均{s['avg']:+.1f} 胜{s['win']:.0%}{t3}"


def rng_txt(r):
    return f"{r[0]:g}~{r[1]:g}"


def full_spectrum(ctx, topn=8):
    """单腿全谱: 每维每档成绩, 输出肥档排行(锚定腿可发现性验证)。"""
    rows = []
    for col, bins in DIMS.items():
        for nm, lo, hi in bins:
            s = ctx.st(ctx.m(col, (lo, hi)))
            if s["n"] >= 30 and s["avg"] is not None:
                rows.append((col, nm, (lo, hi), s))
    for p in POSES:
        s = ctx.st(ctx.pose == p)
        if s["n"] >= 30 and s["avg"] is not None:
            rows.append(("地基姿态", p, None, s))
    rows.sort(key=lambda x: -x[3]["avg"])
    return rows[:topn]


def cand_bounds(dim, rng=None):
    """窗精修边界候选: 常用边界∪语言档界∪(当前±扰动)。"""
    b = set(BOUND_POOL)
    for nm, lo, hi in DIMS.get(dim, []):
        b.update((lo, hi))
    if rng:
        b.update(rng[i] + d for i in (0, 1) for d in (-2, -1, -0.5, 0.5, 1, 2))
    return sorted(x for x in b if -99 <= x <= 999)


def anchor_candidates(dim, start, span=2, trim=3):
    """锚窗候选=当年人工的跨档路径: 起点档∪相邻档(每侧≤span档)→边界±trim内扰动。"""
    bins = [(lo, hi) for nm, lo, hi in DIMS[dim]]
    i0 = next(i for i, b in enumerate(bins) if (b[0], b[1]) == start)
    merged = {(bins[i][0], bins[j][1])
              for i in range(max(0, i0 - span), i0 + 1)
              for j in range(i0, min(len(bins), i0 + span + 1))}

    def near(v):
        return {b for b in cand_bounds(dim) if abs(b - v) <= trim}

    out = set(merged)
    for lo, hi in merged:
        for lo2 in near(lo):
            for hi2 in near(hi):
                if lo2 < hi2 and hi2 - lo2 >= 0.5:
                    out.add((lo2, hi2))
    return sorted(out)


OPEN_MERGED = [(-99, 0), (0, 3), (3, 7), (7, 99)]   # 强开∪一字(人工语言「≥7」)
OPEN_FULL = [(-99, 99)]                             # 不限(A2/C2结构=今开单维条, b1不限)


def axis_variants(dim):
    """轴变体: 开盘轴=五档/强一字合并档(转温格b1≥7)/全并(不限);
    今开轴=弱开三档(C1块)/粗四档/细六档(A2今开7~8.5)。"""
    if dim == "买入开盘%":
        return list(TODAY_AXES)
    if dim.endswith("开盘%"):
        return [MAT_AXES[dim], OPEN_MERGED, OPEN_FULL]
    return [MAT_AXES[dim]]


def allowed_pairs(dims):
    """形态轴对(分支只长在开盘形态语言上): 开盘×今开 / 开盘×开盘 /
    缩量关系×今开(K4)。单板换手不作轴——换手以交互过滤器进分支(人工语言如此)。"""
    opens = [d for d in dims if d.endswith("开盘%") and d != "买入开盘%"]
    today = "买入开盘%" if "买入开盘%" in dims else None
    pairs = []
    if today:
        pairs += [(o, today) for o in opens]
        if "三换-二换" in dims:
            pairs.append(("三换-二换", today))
    pairs += [(opens[i], opens[j]) for i in range(len(opens)) for j in range(i + 1, len(opens))]
    return pairs


def matrix_cells(ctx, m_core, d1, d2, ax1=None, ax2=None, layers=2):
    """矩阵格子: 本身不肥(n≥8剔3不正)时套交互过滤器再判——
    过滤后肥的格子记录交互腿(分支构建时并入, 管线层3「一板/换手交互」)。"""
    ax1 = ax1 or MAT_AXES[d1]
    ax2 = ax2 or MAT_AXES[d2]
    cells = []
    for i, r1 in enumerate(ax1):
        for j, r2 in enumerate(ax2):
            mask = m_core & ctx.m(d1, r1) & ctx.m(d2, r2)
            s = ctx.st(mask)
            leg = None
            if not is_fat(s) and s["n"] >= 8:
                excl2d = []
                for item in EXCL_2D:
                    mm = np.ones(len(ctx.e3), bool)
                    for d, r in item:
                        mm &= ctx.m(d, r)
                    excl2d.append((item, mm))
                best_t3 = None
                for dim, rng in INTERACT:                       # 一层: 含入窗
                    if dim in (d1, d2):
                        continue
                    s2 = ctx.st(mask & ctx.m(dim, rng))
                    if is_fat(s2) and (best_t3 is None or s2["t3"] > best_t3):
                        s, leg, best_t3 = s2, (("in", dim, rng),), s2["t3"]
                for item, mm in excl2d:                          # 一层: 2D排除格
                    s2 = ctx.st(mask & ~mm)
                    if is_fat(s2) and (best_t3 is None or s2["t3"] > best_t3):
                        s, leg, best_t3 = s2, (("x2", item),), s2["t3"]
                if leg is None and layers >= 2:
                    # 二层交互: 含入窗×2D排除格(A2型=假锁排除∩首10<10, 裸格38笔→14笔)
                    for dim, rng in INTERACT:
                        if dim in (d1, d2):
                            continue
                        m1 = mask & ctx.m(dim, rng)
                        for item, mm in excl2d:
                            s2 = ctx.st(m1 & ~mm)
                            if is_fat(s2) and (best_t3 is None or s2["t3"] > best_t3):
                                s, leg, best_t3 = s2, (("in", dim, rng), ("x2", item)), s2["t3"]
                if leg is not None:
                    for part in leg:
                        if part[0] == "in":
                            mask = mask & ctx.m(part[1], part[2])
                        else:
                            mm = np.ones(len(ctx.e3), bool)
                            for d, r in part[1]:
                                mm &= ctx.m(d, r)
                            mask = mask & ~mm
            cells.append(dict(i=i, j=j, r1=r1, r2=r2, mask=mask, s=s, leg=leg))
    return cells


def cell_q(s):
    """肥子格质量: 剔3均值封顶13×ln n(剔3防单笔妖票撑格; 13=walk-forward R6天花板)。"""
    return min(s["t3"] or 0.0, AVG_CAP) * math.log(s["n"]) if s["n"] else 0.0


def is_fat(s, min_n=8):
    return (s["n"] >= min_n and s["t3"] is not None and s["t3"] > 0
            and s["win"] is not None and s["win"] >= 0.5)


def matrix_score(ctx, m_core, skip_dims, layers=2):
    """全形态轴对×轴变体扫描: 得分=肥子格质量Top3和(人工锚窗判据=分支亮不亮)。
    弱票系(B2/B3)地基姿态是前置过滤——仅当姿态基结构有决定性优势(>1.5倍且≥3)才启用。
    返回 (d1, d2, score, pose_base, ax1, ax2)。"""
    dims = [d for d in MAT_AXES
            if d not in skip_dims and int(ctx.cover(d).sum()) >= 30]
    pose_ok = (ctx.pose == "站线上") | (ctx.pose == "骑线")

    def scan(base):
        best = (None, None, -1e9, None, None)
        for d1, d2 in allowed_pairs(dims):
            for ax1 in axis_variants(d1):
                for ax2 in axis_variants(d2):
                    if ax1 is OPEN_FULL and ax2 is OPEN_FULL:
                        continue   # 全并×全并=核心自身, 无信息
                    cells = matrix_cells(ctx, base, d1, d2, ax1, ax2, layers)
                    fat = [c for c in cells if is_fat(c["s"]) and c["s"]["n"] >= 8]
                    fat_q = sorted((cell_q(c["s"]) for c in fat), reverse=True)
                    score = sum(fat_q[:3])
                    if score > best[2]:
                        best = (d1, d2, score, ax1, ax2)
        return best

    d1, d2, s_plain, ax1, ax2 = scan(m_core)
    pd1, pd2, s_pose, pax1, pax2 = scan(m_core & pose_ok)
    if s_pose > 3.0 and s_pose > 1.5 * s_plain:
        return (pd1, pd2, s_pose, True, pax1, pax2)
    return (d1, d2, s_plain, False, ax1, ax2)


def print_matrix(ctx, cells, d1, d2, ax1=None, ax2=None):
    ax1 = ax1 or MAT_AXES[d1]
    ax2 = ax2 or MAT_AXES[d2]
    print(f"    矩阵 {d1}(行)×{d2}(列), 单元=n笔/均值/胜率(◆=肥子格, ◆F=交互后肥):")
    hdr = "        " + "".join(f"{rng_txt(r):>15s}" for r in ax2)
    print(hdr)
    for i, r1 in enumerate(ax1):
        row = f"  {rng_txt(r1):<6s}"
        for j in range(len(ax2)):
            c = cells[i * len(ax2) + j]
            s = c["s"]
            fat = is_fat(s)
            cell = f"{s['n']}/{s['avg']:+.1f}/{s['win']:.0%}" if s["n"] else "—"
            mark = ("◆F" if c.get("leg") else "◆") if fat else ""
            row += f"{cell + mark:>15s}"
        print(row)


def grow_region(ctx, cells, seed):
    """区域生长: 并相邻格须本身非毒(胜≥40%均>-1)且并后剔3不降超0.3、胜≥50% n≥8。"""
    pos = {(c["i"], c["j"]): k for k, c in enumerate(cells)}
    taken = {seed}
    cur = cells[seed]["mask"]
    cur_s = ctx.st(cur)
    while True:
        cand = set()
        for k in taken:
            i, j = cells[k]["i"], cells[k]["j"]
            for nb in ((i - 1, j), (i + 1, j), (i, j - 1), (i, j + 1)):
                if nb in pos and pos[nb] not in taken:
                    cand.add(pos[nb])
        best = None
        for k in cand:
            s_c = cells[k]["s"]
            if s_c["n"] == 0 or s_c["win"] is None:
                continue
            if s_c["win"] < 0.4 or (s_c["avg"] or 0) <= -1:
                continue
            m2 = cur | cells[k]["mask"]
            s2 = ctx.st(m2)
            if (s2["n"] >= 8 and s2["win"] >= 0.5
                    and cur_s["t3"] is not None and s2["t3"] >= cur_s["t3"] - 0.3):
                if best is None or s2["t3"] > best[1]["t3"]:
                    best = (m2, s2, k)
        if best is None:
            break
        cur, _, k = best
        cur_s = ctx.st(cur)
        taken.add(k)
    return taken, cur, cur_s


def axis_full(dim, rng):
    bins = MAT_AXES.get(dim)
    if not bins:
        return False
    return rng[0] <= bins[0][0] and rng[1] >= bins[-1][1]


def branch_mask(ctx, br):
    m = np.ones(len(ctx.e3), bool)
    for dim, rng in br["inc"].items():
        m &= ctx.m(dim, rng)
    for item in br["excl"]:
        mm = np.ones(len(ctx.e3), bool)
        for dim, rng in item:
            mm &= ctx.m(dim, rng)
        m &= ~mm
    if br["pose_in"]:
        pm = np.zeros(len(ctx.e3), bool)
        for p in br["pose_in"]:
            pm |= ctx.pose == p
        m &= pm
    for p in br["pose_out"]:
        m &= ~(ctx.pose == p)
    return m


def discipline(s, min_n=8):
    return s["n"] >= min_n and s["win"] is not None and s["win"] >= 0.6 \
        and s["t3"] is not None and s["t3"] > 0


def trim_to_pass(ctx, br, min_n=8, rounds=2):
    """边界收口: 未过纪律时每腿边界±2内找「能过且留票最多」的窗;
    已过纪律不动(人工纪律=胜率>60%即收口, 不再优化)。"""
    for _ in range(rounds):
        if discipline(ctx.st(branch_mask(ctx, br)), min_n):
            return True
        best = None
        for dim in list(br["inc"]):
            lo, hi = br["inc"][dim]
            los = {b for b in cand_bounds(dim, (lo, hi)) if abs(b - lo) <= 2}
            his = {b for b in cand_bounds(dim, (lo, hi)) if abs(b - hi) <= 2}
            for lo2 in los:
                for hi2 in his:
                    if lo2 >= hi2 or hi2 - lo2 < 0.5:
                        continue
                    br["inc"][dim] = (lo2, hi2)
                    s2 = ctx.st(branch_mask(ctx, br))
                    if discipline(s2, min_n) and (best is None or s2["n"] > best[0]):
                        best = (s2["n"], dim, (lo2, hi2))
            br["inc"][dim] = (lo, hi)
        if best is None:
            return False
        _, dim, w = best
        br["inc"][dim] = w
        if axis_full(dim, w):
            del br["inc"][dim]
    return discipline(ctx.st(branch_mask(ctx, br)), min_n)


def leg_candidates(ctx, br, cur, kinds=("in", "excl")):
    """全腿候选生成: 含入(语言档)/排除(合并档)/姿态/2D过滤格 → (mask, 描述, 应用, 形)。"""
    out = []
    n_cur = max(int(cur.sum()), 1)
    for dim, bins in DIMS.items():
        if dim in br["inc"]:
            continue
        for nm, lo, hi in bins:
            out.append((cur & ctx.m(dim, (lo, hi)), f"+{dim}{nm}",
                        lambda b, d=dim, r=(lo, hi): b["inc"].__setitem__(d, r), "in"))
        edge = [x[1] for x in bins] + [bins[-1][2]]
        for i0 in range(len(bins)):
            for j0 in range(i0 + 1, min(i0 + 3, len(bins)) + 1):
                rng = (edge[i0], edge[j0])
                n_ex = int((cur & ctx.m(dim, rng)).sum())
                if n_ex == 0 or n_ex > 0.5 * n_cur:
                    continue
                out.append((cur & ~ctx.m(dim, rng), f"-剔{dim}{rng_txt(rng)}",
                            lambda b, it=((dim, rng),): b["excl"].append(it), "excl"))
    for p in POSES:
        n_ex = int((cur & (ctx.pose == p)).sum())
        if not n_ex:
            continue
        if p in ("站线上", "骑线"):
            out.append((cur & (ctx.pose == p), f"+姿态{p}",
                        lambda b, pp=p: b["pose_in"].append(pp), "in"))
        else:
            out.append((cur & ~(ctx.pose == p), f"-剔姿态{p}",
                        lambda b, pp=p: b["pose_out"].append(pp), "excl"))
    for item in EXCL_2D:
        mm = np.ones(len(ctx.e3), bool)
        for d, r in item:
            mm &= ctx.m(d, r)
        n_ex = int((cur & mm).sum())
        if n_ex == 0 or n_ex > 0.5 * n_cur:
            continue
        out.append((cur & ~mm, "-剔" + "×".join(f"{d}{rng_txt(r)}" for d, r in item),
                    lambda b, it=item: b["excl"].append(it), "excl"))
    return [c for c in out if c[3] in kinds]


def rescue_legs(ctx, br, min_n=8, max_legs=3):
    """差票过滤腿拯救: 分支未过纪律时, 取「救活且留票最多」的腿, 否则剔3最大改善。"""
    for _ in range(max_legs):
        cur = branch_mask(ctx, br)
        s = ctx.st(cur)
        if discipline(s, min_n):
            break
        saving, improving = [], []
        for m2, desc, apply, _kind in leg_candidates(ctx, br, cur):
            s2 = ctx.st(m2)
            if s2["t3"] is None:
                continue
            if discipline(s2, min_n):
                saving.append((s2["n"], s2["t3"], desc, apply))
            elif s2["t3"] > (s["t3"] if s["t3"] is not None else -99) + 0.3 \
                    and s2["win"] >= s["win"]:
                improving.append((s2["n"], s2["t3"], desc, apply))
        cands = saving or improving
        if not cands:
            return False
        cands.sort(key=lambda x: -x[0])
        cands[0][3](br)
        print(f"        拯救腿: {cands[0][2]}")
    return discipline(ctx.st(branch_mask(ctx, br)), min_n)


def interact_leg(ctx, br, min_n=8, gain=0.5):
    """一板/换手交互腿(管线原步骤): 已收口分支允许加一条排除形腿,
    须剔3增益≥gain、纪律保持、留票≥70%(人工交互/过滤腿九成是排除形)。"""
    cur = branch_mask(ctx, br)
    s = ctx.st(cur)
    best = None
    for m2, desc, apply, _kind in leg_candidates(ctx, br, cur, kinds=("excl",)):
        s2 = ctx.st(m2)
        if (discipline(s2, min_n) and s2["n"] >= min_n
                and s2["n"] >= 0.7 * max(int(cur.sum()), 1)
                and s2["t3"] > s["t3"] + gain
                and (best is None or s2["t3"] > best[1])):
            best = (desc, s2["t3"], apply)
    if best:
        best[2](br)
        print(f"        交互腿: {best[0]}")
        return True
    return False


def leg_txt(br):
    parts = [f"{d}{rng_txt(r)}" for d, r in br["inc"].items()]
    parts += ["剔" + "×".join(f"{d}{rng_txt(r)}" for d, r in it) for it in br["excl"]]
    if br["pose_in"]:
        parts.append("+姿态" + "|".join(br["pose_in"]))
    parts += [f"剔姿态{p}" for p in br["pose_out"]]
    return " × ".join(parts)


def nn(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else v


def tag_row(row):
    g4 = row["四组"]
    s = tag_scheme(g4, nn(row["b1开盘%"]), nn(row["b2开盘%"]), nn(row["b3开盘%"]),
                   auction_pct=nn(row["买入开盘%"]), b2_turn=nn(row["b2换手%"]),
                   b3_turn=nn(row["b3换手%"]), foundation_chg=nn(row["地基涨跌%"]),
                   pre10_pct=nn(row["首10日涨幅%"]), foundation_pose=nn(row["地基姿态"]),
                   anchor_pos=nn(row["锚位%"]), anchor_dist=nn(row["锚距"]))
    w = tag_weak(g4, nn(row["b1开盘%"]), nn(row["b2开盘%"]), nn(row["b3开盘%"]),
                 auction_pct=nn(row["买入开盘%"]), b1_turn=nn(row["b1换手%"]),
                 b2_turn=nn(row["b2换手%"]), b3_turn=nn(row["b3换手%"]),
                 foundation_chg=nn(row["地基涨跌%"]), prev_wave60=nn(row["前波60日最高板"]),
                 dist_h60=nn(row["距60日新高%"]))
    return (str(s["no"]) if s else None, str(s.get("sub") or "") if s else "",
            str(w["no"]) if w else None, str(w.get("sub") or "") if w else "")


def derive(E, no, pools, anchor_dim, anchor_nm, era):
    weak = no.startswith("K")
    df = E[E["四组"].isin(pools)].copy()
    df = df[df["月"] >= era[0]]
    if era[1]:
        df = df[df["月"] <= era[1]]
    ctx = Ctx(df)
    era_txt = f"{era[0]}~{era[1] if era[1] else '今'}"
    print(f"\n{'=' * 20} {no} 重演({'/'.join(pools)}, {era_txt}) {'=' * 20}")
    # 1 池基线
    print(f"[1] 池基线: {fmt(ctx.st(np.ones(len(ctx.e3), bool)))}")
    # 2 单腿全谱
    spec = full_spectrum(ctx)
    start = next((lo, hi) for nm, lo, hi in DIMS[anchor_dim] if nm == anchor_nm)
    print(f"[2] 单腿全谱Top8(锚定腿 {anchor_dim}={anchor_nm} 应可见):")
    for col, nm, rng, s in spec:
        mark = "  ←锚" if col == anchor_dim and nm == anchor_nm else ""
        print(f"    {col}={nm}: {fmt(s)}{mark}")
    # 3 锚窗选择(当年人工路径): 语言档有结构→档内微调(±1档并/边界±2);
    # 语言档无结构→跨档搜索(±2档并/边界±3)——A1贴零→<1的跨档精修即此模式
    FLOOR = 3.0

    def sc(w):
        m = ctx.m(anchor_dim, w)
        if int(m.sum()) < 10:
            return -1e9, 0
        _, _, score, _, _, _ = matrix_score(ctx, m, skip_dims={anchor_dim}, layers=1)
        return score, int(m.sum())

    print(f"[3] 锚窗选择(起点=语言档 {anchor_nm}{rng_txt(start)}):")
    s0, n0 = sc(start)
    print(f"    语言档自检: 矩阵分{s0:.1f} 核心{n0}笔")
    if s0 > 0.5:
        # 锚定腿=全谱发现的语言档, 档内有结构→原样保留(边界微调留给分支窗收口)
        mode = "保留语言档"
        cands = []
    else:
        mode = "跨档搜索"
        cands = [w for w in anchor_candidates(anchor_dim, start, span=2, trim=3)]
    scored = sorted(((sc(w)[0], int(ctx.m(anchor_dim, w).sum()), w)
                     for w in cands if w != start), key=lambda x: (-x[0], -x[1], x[2][1] - x[2][0]))
    aw, best_s = start, s0
    if scored and scored[0][0] > s0 + 0.5:
        aw, best_s = scored[0][2], scored[0][0]
    for score, n_w, w in scored[:3]:
        print(f"    {anchor_dim}{rng_txt(w)}: 矩阵分{score:.1f} 核心{n_w}笔")
    m_core = ctx.m(anchor_dim, aw)
    move = "" if aw == start else f"({mode}: {rng_txt(start)}→{rng_txt(aw)})"
    print(f"    选定锚窗: {anchor_dim}{rng_txt(aw)} {move} 核心{fmt(ctx.st(m_core))}")
    if best_s < FLOOR:
        print("    (语言档与邻档均无结构信号 → 下面回退单分支路径)")
    # 4 分支矩阵检测(弱票系姿态前置: 站线上|骑线 先筛)
    d1, d2, _, pose_base, ax1, ax2 = matrix_score(ctx, m_core, skip_dims={anchor_dim})
    pose_pre = False
    if pose_base:
        pose_ok = (ctx.pose == "站线上") | (ctx.pose == "骑线")
        m_core = m_core & pose_ok
        pose_pre = True
        print(f"    [姿态前置生效: 站线上|骑线 — 弱票接口诀的地基尺] 核心剩{fmt(ctx.st(m_core))}")
    cells = matrix_cells(ctx, m_core, d1, d2, ax1, ax2)
    print(f"[4] 分支矩阵检测(最优形态轴对 {d1}×{d2}):")
    print_matrix(ctx, cells, d1, d2, ax1, ax2)
    fat = [k for k, c in enumerate(cells) if is_fat(c["s"])]
    regions, used = [], set()
    for k in sorted(fat, key=lambda k: -cell_q(cells[k]["s"])):
        if k in used:
            continue
        taken, m_r, s_r = grow_region(ctx, cells, k)
        key = frozenset(taken)
        if any(key <= r[0] for r in regions):
            used.add(k)
            continue
        regions.append((key, m_r, s_r))
        used |= taken
    branches = []
    if not regions:
        # 回退: 锚格×今开合并档最优单格
        tbins = [(lo, hi) for nm, lo, hi in TODAY_BINS]
        twins = list(dict.fromkeys((tbins[i][0], tbins[j][1])
                                   for i in range(len(tbins))
                                   for j in (i, i + 1) if j < len(tbins)))
        best = None
        for w in twins:
            m2 = m_core & ctx.m("买入开盘%", w)
            s2 = ctx.st(m2)
            if (s2["n"] >= 5 and s2["avg"] > 0
                    and (best is None or s2["t3"] > best[1]["t3"])):
                best = (m2, s2, w)
        if best is None:
            print("    无肥子格且无合格单格 → 重演失败(样本不足)")
            return None
        m_r, s_r, w = best
        br = {"inc": {anchor_dim: aw, "买入开盘%": w}, "excl": [],
              "pose_in": [], "pose_out": []}
        print(f"    无肥子格 → 回退单分支: 今开{rng_txt(w)} {fmt(s_r)}")
        branches.append(br)
    else:
        for key, m_r, s_r in regions:
            r1s = [cells[k]["r1"] for k in key]
            r2s = [cells[k]["r2"] for k in key]
            inc = {anchor_dim: aw,
                   d1: (min(r[0] for r in r1s), max(r[1] for r in r1s)),
                   d2: (min(r[0] for r in r2s), max(r[1] for r in r2s))}
            br = {"inc": {d: r for d, r in inc.items() if not axis_full(d, r)},
                  "excl": [], "pose_in": [], "pose_out": []}
            legs_extra = [cells[k]["leg"] for k in key if cells[k]["leg"]]
            if legs_extra:   # 交互腿多数票并入(管线层3: 一板/换手交互, 最多两层)
                leg, _ = Counter(legs_extra).most_common(1)[0]
                for part in leg:
                    if part[0] == "in":
                        br["inc"][part[1]] = part[2]
                    else:
                        br["excl"].append(tuple(part[1]))
                print("    [交互腿并入分支: "
                      + "×".join(("+" + part[1] + rng_txt(part[2])) if part[0] == "in"
                                 else ("-剔" + "×".join(f"{d}{rng_txt(r)}" for d, r in part[1]))
                                 for part in leg) + "]")
            if anchor_dim not in br["inc"]:
                br["inc"][anchor_dim] = aw
            branches.append(br)
    # 5 按人工纪律收口: 救活→边界收口→交互腿(已过的分支不动=胜率>60%即收)
    print("[5] 分支收口(胜≥60%剔3>0即收; 未过→过滤腿拯救+边界收口; 过→可选交互腿):")
    masks, saved_all = [], True
    for bi, br in enumerate(branches):
        if pose_pre and not (br["pose_in"] or br["pose_out"]):
            br["pose_in"] = ["站线上", "骑线"]
        s0 = ctx.st(branch_mask(ctx, br))
        if discipline(s0):
            note = "直接收口"
        else:
            ok = rescue_legs(ctx, br) or trim_to_pass(ctx, br)
            note = "救活/收口" if ok else "未救活(最接近格)"
            saved_all = saved_all and ok
        interact_leg(ctx, br)
        m_b = branch_mask(ctx, br)
        masks.append(m_b)
        print(f"    分支{bi + 1}({note}): {leg_txt(br)}")
        print(f"                {fmt(ctx.st(m_b))}")
    # 6 并集纪律终检
    m_un = np.zeros(len(ctx.e3), bool)
    for m_b in masks:
        m_un |= m_b
    s_un = ctx.st(m_un)
    okd = s_un["n"] >= 10 and s_un["win"] >= 0.6 and s_un["t3"] > 0
    print(f"[6] 分支组并集: {len(branches)}分支 {fmt(s_un)}")
    print(f"    纪律终检(n≥10胜≥60%剔3>0): {'✓通过' if okd else '✗未过'}")
    # 7 对照人工
    col = "w_no" if weak else "s_no"
    sub_col = "w_sub" if weak else "s_sub"
    man = (ctx.df[col] == no).to_numpy()
    s_man = ctx.st(man)
    inter = int((man & m_un).sum())
    union = int((man | m_un).sum())
    jac = inter / union if union else 0.0
    recall = inter / int(man.sum()) if man.sum() else 0.0
    prec = inter / s_un["n"] if s_un["n"] else 0.0
    print(f"[7] 人工对照: 人工{fmt(s_man)} | 机器∩人工{inter}"
          f" J={jac:.2f} 召回={recall:.2f}(人工被机器覆盖) 精确={prec:.2f}(机器命中人工)")
    for s in (C.WEAK_SCHEMES if weak else C.SCHEMES):
        if s["no"] != no:
            continue
        sub = s.get("sub", "")
        mrow = man & (ctx.df[sub_col] == sub).to_numpy()
        overlap = int((mrow & m_un).sum())
        print(f"    人工分支{sub or '—'} {int(mrow.sum())}笔 ↔ 机器并集覆盖{overlap}")
    if not okd:
        print("    (纪律未过=样本不足, 上格为最接近格)")
    return dict(no=no, n=s_un["n"], win=s_un["win"], avg=s_un["avg"],
                t3=s_un["t3"], n_man=int(man.sum()), jac=jac, recall=recall,
                ok=okd)


TASKS = [
    # 强市组(定型段2023-01起)
    dict(no="A1", pools=("二接三阳",), anchor_dim="b2开盘%", anchor_nm="贴零",
         era=("2023-01", None)),
    dict(no="A2", pools=("二接三阳",), anchor_dim="b2开盘%", anchor_nm="一字",
         era=("2023-01", None)),
    dict(no="B1", pools=("二接三阴",), anchor_dim="b2开盘%", anchor_nm="强开",
         era=("2023-01", None)),
    dict(no="B2", pools=("二接三阴",), anchor_dim="b1开盘%", anchor_nm="低开",
         era=("2023-01", None)),
    dict(no="B3", pools=("三接四阴",), anchor_dim="b2开盘%", anchor_nm="贴零",
         era=("2023-01", None)),
    dict(no="C1", pools=("二接三阳", "二接三阴"), anchor_dim="b2开盘%", anchor_nm="温开",
         era=("2023-01", None)),
    dict(no="C2", pools=("三接四阳", "三接四阴"), anchor_dim="b3换手%", anchor_nm="10~15",
         era=("2023-01", None)),
    dict(no="C3", pools=("三接四阳", "三接四阴"), anchor_dim="b3换手%", anchor_nm="<5",
         era=("2023-01", None)),
    # 弱市组(定型段2020-08~2023-08)
    dict(no="K2", pools=("三接四阴",), anchor_dim="b3换手%", anchor_nm="10~15",
         era=("2020-08", "2023-08")),
    dict(no="K4", pools=("三接四阳",), anchor_dim="b3换手%", anchor_nm="10~15",
         era=("2020-08", "2023-08")),
    dict(no="K5", pools=("三接四阴",), anchor_dim="b2开盘%", anchor_nm="贴零",
         era=("2020-08", "2023-08")),
    dict(no="K9", pools=("二接三阴",), anchor_dim="b2开盘%", anchor_nm="低开",
         era=("2020-08", "2023-08")),
    dict(no="K3", pools=("二接三阳",), anchor_dim="b2开盘%", anchor_nm="低开",
         era=("2020-08", "2023-08")),
]


def main() -> None:
    E = pd.read_csv(CSV, dtype={"代码": str})
    E = E[E["E3%"].notna()]
    E = E[E["四组"].isin(LIVE_POOLS)].copy()
    E["月"] = E["买入日"].astype(str).str[:7]
    tags = E.apply(tag_row, axis=1, result_type="expand")
    E["s_no"], E["s_sub"], E["w_no"], E["w_sub"] = tags[0], tags[1], tags[2], tags[3]
    rows = []
    for t in TASKS:
        try:
            r = derive(E, **t)
        except Exception as exc:  # noqa: BLE001 - 单条失败不挡全量
            print(f"\n{'=' * 20} {t['no']} 重演异常: {exc!r} {'=' * 20}")
            r = None
        if r:
            rows.append(r)
    print(f"\n{'=' * 20} 13条全量重演总表 {'=' * 20}")
    print(f"{'口诀':<4}{'机器n':>6}{'胜率':>7}{'均值':>7}{'剔3':>7}{'人工n':>7}"
          f"{'J':>6}{'召回':>6}  纪律")
    for r in rows:
        print(f"{r['no']:<4}{r['n']:>6}{r['win']:>7.0%}{r['avg']:>7.1f}"
              f"{(r['t3'] or 0):>7.1f}{r['n_man']:>7}{r['jac']:>6.2f}{r['recall']:>6.2f}"
              f"  {'✓' if r['ok'] else '✗样本不足'}")
    ok_n = sum(1 for r in rows if r["ok"])
    j_avg = sum(r["jac"] for r in rows) / max(len(rows), 1)
    r_avg = sum(r["recall"] for r in rows) / max(len(rows), 1)
    print(f"\n纪律通过 {ok_n}/{len(rows)} | 平均J={j_avg:.2f} 平均召回={r_avg:.2f}"
          f"(召回=人工笔被机器格覆盖比例; J低主因=机器格是人工超集)")


main()
