"""N型补涨打板(w2s)答题训练题库构建:触发池事件 → 逐题K线窗口 + 答案 + 讲解。

题库口径(照 hpr 模式,w2s 语义):
- 题库范围 = 触发池事件(T,信号日 T-1 收盘特征全可知) × 次日触板(touch,决策时刻
  =盘中触涨停价) × 非一字(one_word 剔除:一字排队买不到,「买」选项不存在,
  主人拍板口径 q4 起同样适用) × 有退出结果(20日窗内断板或兜底)。
- 应买 = actionable(四组白名单命中);不应买 = 白名单外雷达票(触板也不打)。
- 收益 = 板留断走(与回测同款:买入次日起首个未涨停日收盘,20交易日兜底;
  买价=涨停价,无滑点,未复权)。
- K线 = 未复权日线(与回测同口径,除权日可见跳空,题卡页脚注明)。

版本纪律:讲解文案/题库结构变更必升 QUIZ_CONTENT_VERSION;版本串进表/进API/进前端
localStorage key——版本一变旧进度自动作废。
"""
from __future__ import annotations

import pandas as pd

from alphaagent.server.services.weak_to_strong import u_shape

QUIZ_CONTENT_VERSION = 1  # q1:初版(2026-10-02,五组白名单对照讲解)
BARS_BEFORE = 60          # 决策日前窗口上限(前端默认只显末~30根)

# 综合挑战卷:好票=五组每组随机2道;差票=白名单外雷达票随机(好:差≈1:1.5~2)
MIX_PER_GROUP = 2
MIX_TRAP_MIN = 10
MIX_TRAP_MAX = 15

_MISS_WIN_LINE = "白名单外雷达票整体胜率不足六成——不在四组甜点里的板,不打"

# 每组白名单条件的(字段,文案,判定函数)三元组——讲解对照行的唯一事实源。
# 判定函数签名 f(dict)->bool,与 u_shape.actionable_of 同口径(手抄展开,便于
# 生成「✓/✗ + 数据」对照;构建自检会校验与 actionable_of 结论一致)。
_GROUP_RULES: dict[str, list[tuple[str, object, object]]] = {
    "yin2": [
        ("base", "蹲类地基(坑底/下探,非DN深坑)", lambda f: f["base"] in u_shape.SQUAT_BASES),
        ("topped", "未收顶上(不曾爬回顶)", lambda f: not f["topped"]),
        ("reb", "弹回≤16%(没弹太多)", lambda f: f["reb"] <= 0.16),
        ("gap_d0", "坑宽6~15天(歇够没散)", lambda f: 6 <= f["gap_d0"] <= 15),
    ],
    "yang2a": [
        ("base", "DN深坑地基(坑底首阳)", lambda f: f["base"] == "DN"),
        ("topped", "未收顶上(首阳命脉)", lambda f: not f["topped"]),
    ],
    "yang2b": [
        ("base", "蹲类地基", lambda f: f["base"] in u_shape.SQUAT_BASES),
        ("ma_st", "均线纠缠(5/10/20/30交错)", lambda f: f["ma_st"] in u_shape.TANGLE_MA),
        ("d23ok", "下探中(前日低于3日前且3日前未涨停)", lambda f: bool(f["d23ok"])),
    ],
    "yin4": [
        ("seg_h", "大波≥4板(妖股回马枪)", lambda f: f["seg_h"] >= 4),
        ("n_lim_mid", "孤立板1~2个(断板期零散涨停)", lambda f: 1 <= f["n_lim_mid"] <= 2),
        ("ma_st", "全多头+++(5>10>20>30)", lambda f: f["ma_st"] == "+++"),
        ("low_dd", "洗盘坑存在(距顶跌超4%)", lambda f: f["low_dd"] <= -0.04),
        ("pull", "剔中坑回顶(坑8~15%却已爬回顶4%内)", lambda f: not (f["pull"] > -0.04 and -0.15 < f["low_dd"] <= -0.08)),
    ],
    "yang4": [
        ("seg_h", "2板小波穿插(夹层结构)", lambda f: f["seg_h"] == 2),
        ("pull", "剔骑顶±4%(信号日收距大波顶±4%内)", lambda f: not (-0.04 < f["pull"] <= 0.04)),
    ],
}


def quiz_rules_version() -> str:
    from alphaagent.server.services.weak_to_strong import contracts
    return f"{contracts.W2S_RULES_VERSION}·q{QUIZ_CONTENT_VERSION}"


def build_questions(T: pd.DataFrame, bars: pd.DataFrame) -> list[dict[str, object]]:
    """主入口:T=触发池帧(_build_events 产物,行=bars 行号),bars=同进程全量日线。"""
    from alphaagent.server.services.weak_to_strong import contracts

    e = T[T["touch"] & ~T["one_word"]].copy()
    # 退出结果:买入次日起(n2)首个未涨停日收盘,20日兜底(与 _trades_for 同款)
    MAX_K = 20
    import numpy as np
    done_px = pd.Series(np.nan, index=e.index, dtype=float)
    done_dt = pd.Series(pd.NaT, index=e.index, dtype="datetime64[ns]")
    done_k = pd.Series(0, index=e.index, dtype=int)
    pending = pd.Series(True, index=e.index)
    for k in range(2, MAX_K + 1):
        lim = e[f"n{k}_is_lim"].fillna(False).astype(bool)
        avail = e[f"n{k}_close"].notna() & e[f"n{k}_date"].notna()
        hit = pending & (~lim) & avail
        done_px[hit] = e.loc[hit, f"n{k}_close"]
        done_dt[hit] = e.loc[hit, f"n{k}_date"]
        done_k[hit] = k
        pending = pending & ~hit
    still = pending & e[f"n{MAX_K}_close"].notna() & e[f"n{MAX_K}_date"].notna()
    done_px[still] = e.loc[still, f"n{MAX_K}_close"]
    done_dt[still] = e.loc[still, f"n{MAX_K}_date"]
    done_k[still] = MAX_K
    e["sim_exit_px"] = done_px
    e["sim_exit_dt"] = done_dt
    e["sim_hold"] = done_k
    e = e[e["sim_exit_px"].notna()].copy()          # 无退出结果不出题
    e["ret_sim%"] = (e["sim_exit_px"] / e["lim_px"] - 1) * 100

    e["entry_date"] = e["n1_date"]                # 入场日=信号次日(_trades_for 同款)
    e["月"] = e["entry_date"].dt.strftime("%Y-%m")
    e["年"] = e["entry_date"].dt.strftime("%Y")
    e = e.sort_values(["月", "entry_date", "vt_symbol"])
    e["seq"] = e.groupby("月").cumcount() + 1

    b_open = bars["open_price"].to_numpy()
    b_high = bars["high_price"].to_numpy()
    b_low = bars["low_price"].to_numpy()
    b_close = bars["close_price"].to_numpy()
    b_vol = bars["volume"].to_numpy()
    b_date = bars["trade_date"].to_numpy()
    b_pos = bars["pos"].to_numpy()

    def _bar(i: int) -> dict[str, object]:
        v = b_vol[i]
        return {"d": pd.Timestamp(b_date[i]).date().isoformat(),
                "o": round(float(b_open[i]), 2), "h": round(float(b_high[i]), 2),
                "l": round(float(b_low[i]), 2), "c": round(float(b_close[i]), 2),
                "v": int(v) if v == v else 0}

    # 组特征字典(对照 _GROUP_RULES 逐条判定用;列名=u_features 键)
    def _feat(row) -> dict[str, object]:
        return {"base": row["u_base"], "topped": bool(row["topped"]),
                "reb": float(row["reb"]), "gap_d0": int(row["gap_d0"]),
                "ma_st": row["ma_st"], "d23ok": bool(row["d23ok"]),
                "seg_h": int(row["seg_h"]), "n_lim_mid": int(row["n_lim_mid"]),
                "low_dd": float(row["low_dd"]), "pull": float(row["pull"])}

    rows: list[dict[str, object]] = []
    for _, r in e.iterrows():
        # 决策日=入场日(T+1 行=信号日行+1);K线窗以入场日为锚
        i = int(r.name) + 1
        if i >= len(bars) or str(bars["vt_symbol"].iat[i]) != str(r["vt_symbol"]):
            continue
        first = i - int(b_pos[i])
        before = [_bar(j) for j in range(max(first, i - BARS_BEFORE), i)]
        hold = int(r["sim_hold"]) - 1        # 相对入场日的持有天数
        after = [_bar(j) for j in range(i, i + hold + 1)]

        gk = str(r["group_key"])
        f = _feat(r)
        should_buy = bool(r["actionable"])
        glabel = contracts.GROUP_LABELS.get(gk, gk)

        # 白名单对照行(唯一事实源=_GROUP_RULES,与 actionable_of 自检)
        checks = []
        for key, text, fn in _GROUP_RULES.get(gk, []):
            ok = bool(fn(f))
            val = _fmt_val(key, f)
            checks.append(f"{'✓' if ok else '✗'} {text}({val})")
        audit_ok = u_shape.actionable_of(gk, f)
        if audit_ok != should_buy:
            raise RuntimeError(f"题库构建自检失败:{r['vt_symbol']} {r['entry_date']} "
                               f"白名单={audit_ok} T行actionable={should_buy}")

        if should_buy:
            explain = {
                "kind": "hit", "group_key": gk, "group_label": glabel,
                "matched_line": f"{glabel} 白名单全过:" + " × ".join(checks),
            }
        else:
            fails = [c for c in checks if c.startswith("✗")]
            fails_fmt = [c[2:] for c in fails] or ["白名单外(本组条件未全部满足)"]
            explain = {
                "kind": "miss", "group_key": gk, "group_label": glabel,
                "trap_kind": "near" if len(fails) <= 2 else "plain",
                "reasons": [f"差在:{';'.join(fails_fmt)}", _MISS_WIN_LINE],
            }

        d_date = pd.Timestamp(r["entry_date"]).date()
        payload = {
            "seq": int(r["seq"]),
            "vt_symbol": str(r["vt_symbol"]),
            "name": str(r["name"]),
            "decision_date": d_date.isoformat(),
            "group_key": gk,
            "display": {
                "group_label": glabel,
                "gap_d0": int(r["gap_d0"]),
                "low_dd_pct": round(float(r["low_dd"]) * 100, 1),
                "reb_pct": round(float(r["reb"]) * 100, 1),
                "pull_pct": round(float(r["pull"]) * 100, 1),
                "u_base": str(r["u_base"]),
                "ma_st": str(r["ma_st"]),
                "seg_h": int(r["seg_h"]),
                "n_lim_mid": int(r["n_lim_mid"]),
                "prev_close": round(float(b_close[i - 1]), 2),
                "limit_price": round(float(r["lim_px"]), 2),
                "decision_open": round(float(b_open[i]), 2),
                "day_high_pct": round((float(b_high[i]) / float(b_close[i - 1]) - 1) * 100, 2),
            },
            "bars_before": before,
            "bars_after": after,
            "answer": {
                "should_buy": should_buy,
                "group_key": gk,
                "ret_pct": round(float(r["ret_sim%"]), 2),
                "buy_price": round(float(r["lim_px"]), 2),
                "sealed": bool(r["seal"]),
                "hold_days": hold,
                "exit_date": pd.Timestamp(r["sim_exit_dt"]).date().isoformat(),
                "exit_price": round(float(r["sim_exit_px"]), 3),
                "exit_reason": "next_close_fail" if hold == 1 else
                               ("max_hold_close" if hold >= 19 else "break_close"),
            },
            "explain": explain,
        }
        rows.append({
            "decision_date": d_date,
            "vt_symbol": str(r["vt_symbol"]),
            "year": str(r["年"]),
            "month": str(r["月"]),
            "seq": int(r["seq"]),
            "name": str(r["name"]),
            "group_key": gk,
            "point": gk if should_buy else "—",
            "ret_pct": round(float(r["ret_sim%"]), 2),
            "payload": payload,
        })
    return rows


def _fmt_val(key: str, f: dict[str, object]) -> str:
    if key in ("reb", "pull", "low_dd"):
        return f"{float(f[key]) * 100:.1f}%"
    if key == "topped":
        return "曾收顶上" if f[key] else "未收顶"
    if key == "d23ok":
        return "是" if f[key] else "否"
    return str(f[key])


def mix_question_keys(rows, per_group: int = MIX_PER_GROUP,
                      trap_total: int | None = None, rng=None) -> list[tuple[str, str]]:
    """综合挑战卷抽题(好票=五组各随机2道;差票=雷达票 trap_total 道)。"""
    import random
    rnd = random.Random(rng)
    if trap_total is None:
        trap_total = rnd.randint(MIX_TRAP_MIN, MIX_TRAP_MAX)
    by_group: dict[str, list[tuple[str, str]]] = {}
    traps: list[tuple[str, str]] = []
    for r in rows:
        key = (str(r["decision_date"]), str(r["vt_symbol"]))
        if r["point"] and r["point"] != "—":
            by_group.setdefault(str(r["point"]), []).append(key)
        else:
            traps.append(key)
    picked: list[tuple[str, str]] = []
    for keys in by_group.values():
        picked.extend(rnd.sample(keys, min(per_group, len(keys))))
    picked.extend(rnd.sample(traps, min(trap_total, len(traps))))
    return picked
