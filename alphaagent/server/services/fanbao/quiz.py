"""断板反包答题训练题库构建:回测事件 → 逐题K线窗口 + 答案 + 讲解。

题库口径说明:
- 事件范围 = done(未完剔除:没有退出结果无法判分) × 主格(2/4/5+板断1~3天,与回测
  ledger 同口径;3板与断4~5天是参考行不出题)。
- 观察级 O1/O2(5+阴断1、4板阴断3)主人拍板删除(2026-09-28:「这些是永远不会看的」;
  v2.3 起产品全线不打标):整格不进题库——不出题、不当陷阱、不进综合卷。
- 收益 = 持有到断板%(产品卖出纪律单一口径,T+1合规对齐 hpr):反包日炸板→次日
  收盘走(一字跌停顺延首个开板日);封住→持有到首次断板日收盘,15日兜底;
  与交割单同口径。
- K线 = 未复权日线(与回测同口径,除权日可见跳空,题卡页脚注明)。
- 决策面板全部 T-1 字段 + 今开(决策时可见,无未来函数);反包事件定义已剔除一字
  全天(买不到),T字回封可买是真实可买,故无需 hpr 式顶格剔除。

版本纪律:讲解文案/题库结构变更必升 QUIZ_CONTENT_VERSION;版本串进表/进API/进前端
localStorage key——版本一变旧进度自动作废(容器版本漂移教训)。
"""
from __future__ import annotations

import pandas as pd

from alphaagent.server.services.fanbao import contracts, pool as pool_mod

QUIZ_CONTENT_VERSION = 3   # q3:O1/O2 删除连带题库口径改格子剔除(v2.3 方案点收窄为三条)
                             # q2:display 加 day_high_pct(盘中最高=触板时刻锚点,主人:「>8%就该准备打板了」)
                             # q1:首发(出手级S1/S2/S3+死格/形态接近/不沾边三分类)
BARS_BEFORE = 60           # 反包日前窗口上限(覆盖前波连板+断板期;前端默认只显末~30根)

# 出手级口诀 = 综合挑战卷好票来源
HIT_POINTS = ("S1", "S2", "S3")

# ── 综合挑战卷组卷规则(对齐 hpr,主人定 2026-09-28) ──
# 好票:三条口诀每条随机≥2道(固定2保证每套覆盖全部口诀);差票:好票的1.5倍,
# 取21道三等分(死格/形态接近/不沾边)——认熟「看着像但不能打」的票。
MIX_PER_POINT = 2
MIX_TRAP_TOTAL = 21
MIX_TRAP_KINDS = ("dead", "near", "plain")

_MISS_LINE = "主格未命中对照 1338 笔平均 -0.31——不挑就买是亏的"


def quiz_rules_version() -> str:
    return f"{contracts.FANBAO_RULES_VERSION}·q{QUIZ_CONTENT_VERSION}"


def build_questions(E: pd.DataFrame, bars: pd.DataFrame) -> list[dict[str, object]]:
    """主入口:E=事件表(build_events 产物,含 _bar_i/_exit_i 行号),bars=同进程全量日线。

    返回可持久化行:[{decision_date, vt_symbol, year, month, seq, name, group6,
                     point, ret_pct, payload}];月内 seq 按(买入日,代码)编定。
    构建期自检:全部事件 tag_point 重算必须等于 E 行 point,不等即 raise。
    """
    # O1/O2 观察级整格剔除(主人拍板:永远不看;v2.3 起不再打标,按格子剔):
    # 5+阴断1(O1 格)与 4板阴断3(O2 格)的票不出题、不当陷阱;未完剔除(无法判分)
    o_zone = (((E["N"] >= 5) & (E["阴阳"] == "阴") & (E["断板天数"] == 1))
              | ((E["N"] == 4) & (E["阴阳"] == "阴") & (E["断板天数"] == 3)))
    done = E[~E["未完"] & E["主格"] & ~o_zone].copy()
    done.sort_values(["月", "买入日", "代码"], inplace=True)
    done["seq"] = done.groupby("月").cumcount() + 1

    case_map = {(str(c["name"]), str(c["date"])): str(c["note"])
                for c in contracts.CASE_GATES}

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

    rows: list[dict[str, object]] = []
    for _, r in done.iterrows():
        i = int(r["_bar_i"])
        first = i - int(b_pos[i])               # 该票首行 iloc(防跨票切窗)
        before = [_bar(j) for j in range(max(first, i - BARS_BEFORE), i)]
        sealed = bool(r["封住"])
        # 揭示K线窗与持有天数按产品卖出纪律:炸板=次日收盘(一字跌停顺延),封住=到断板日
        exit_off = int(r["_exit_i"]) - i
        after = [_bar(j) for j in range(i, i + exit_off + 1)]

        point = str(r["方案点"])
        should_buy = point != "—"
        group6 = str(r["六组"])
        n_board = int(r["N"])
        gap = int(r["断板天数"])
        drop = _f(r["断板累计%"])
        yin_cnt = int(r["断板阴线数"])
        last_open = _f(r["末日开盘%"])
        last_entity = str(r["末日实体"]) if r["末日实体"] == r["末日实体"] else None
        ret = _f(r["持有到断板%"])
        d_date = pd.Timestamp(r["买入日"]).date()

        # 命中自检:E 是当次回放产物,point 必须与当前 tag_point 一致(防 contracts 漂移)
        recalc = contracts.tag_point(n_board, gap, str(r["阴阳"]), drop or 0.0,
                                     yin_cnt, last_entity=last_entity,
                                     last_open_pct=last_open)
        if recalc != point:
            raise RuntimeError(
                f"题库构建自检失败:{r['名称']} {d_date} E标={point} 重算={recalc}")

        if should_buy:
            explain: dict[str, object] = {
                "kind": "hit",
                "scheme_no": point,
                "scheme_name": contracts.POINT_LABELS.get(point, point),
                "scheme_desc": contracts.POINT_DESC.get(point, ""),
                "matched_line": _matched_line(n_board, gap, drop, yin_cnt,
                                              last_open, last_entity),
                "case_note": case_map.get((str(r["名称"]), d_date.isoformat())),
                "high_var": bool(point == "S2"
                                 and contracts.is_high_var_open(last_open)),
            }
        else:
            reasons, trap_kind = explain_miss(
                n_board=n_board, gap=gap, yin_yang=str(r["阴阳"]),
                drop_pct=drop, yin_count=yin_cnt,
                last_open=last_open, last_entity=last_entity)
            explain = {"kind": "miss", "trap_kind": trap_kind, "reasons": reasons}

        payload = {
            "seq": int(r["seq"]),
            "vt_symbol": str(r["代码"]),
            "name": str(r["名称"]),
            "decision_date": d_date.isoformat(),
            "n_board": n_board,
            "group6": group6,
            "display": {
                "board_label": f"{n_board}板→断{gap}天",
                "group6_label": contracts.GROUP6_LABELS.get(
                    group6, f"{n_board}板反包·{r['阴阳']}"),
                "break_drop_pct": drop,
                "break_yin_count": yin_cnt,
                "last_open_pct": last_open,
                "last_entity": last_entity,
                # 今开(决策时可见):反包日开盘%——盘中触板前能看到今天开在哪
                "today_open_pct": round(
                    (float(b_open[i]) / float(b_close[i - 1]) - 1) * 100, 2),
                # 盘中最高%(决策时刻锚点,主人定 2026-09-29:「一般用户会在>8%的时候准备打板」
                # ——事件=当日触板,最高恒=涨停价,这格的语义是「现在就是触板瞬间,你打不打」)
                "day_high_pct": round(
                    (float(b_high[i]) / float(b_close[i - 1]) - 1) * 100, 2),
                "prev_close": round(float(b_close[i - 1]), 2),
                "limit_price": _f(r["买价"]),
                "decision_open": round(float(b_open[i]), 2),
            },
            "bars_before": before,
            "bars_after": after,
            "answer": {
                "point": point,
                "should_buy": should_buy,
                "ret_pct": ret,
                "buy_price": _f(r["买价"]),
                "sealed": sealed,
                "hold_days": int(r["持有天数"]),
                "exit_date": r["退出日"],
                "exit_price": _f(r["退出价"]),
                "exit_reason": r["退出原因"],
            },
            "explain": explain,
        }
        rows.append({
            "decision_date": d_date,
            "vt_symbol": str(r["代码"]),
            "year": str(r["年"]),
            "month": str(r["月"]),
            "seq": int(r["seq"]),
            "name": str(r["名称"]),
            "group6": group6,
            "point": point,
            "ret_pct": ret,
            "payload": payload,
        })
    return rows


def explain_miss(*, n_board: int, gap: int, yin_yang: str, drop_pct,
                 yin_count: int, last_open, last_entity) -> tuple[list[str], str]:
    """未命中题的「为什么不该买」:按优先级产 1~2 条人话理由(全部正常中文)。
    返回 (reasons, trap_kind):dead=死格规则命中/near=形态接近(差口诀一条)/
    plain=结构不沾边。"""
    # 1. 死格优先:dead_cell_reason 现成文案(4板阳全系/5+阳断3/4+断2~3/2板三毒)
    dead = contracts.dead_cell_reason(n_board, gap, yin_yang, yin_count,
                                      drop_pct if drop_pct is not None else 0.0)
    if dead:
        return ([dead], "dead")
    # 2. 形态接近:差口诀一条(教学标签最鲜明——看着像但差关键一脚)
    near = _near_scheme_line(n_board, gap, yin_yang, drop_pct, yin_count,
                             last_open, last_entity)
    if near:
        return [near, _MISS_LINE], "near"
    # 3. 兜底:结构不沾边——报六组归属+该段口诀清单
    seg = contracts.seg_of(n_board) or f"{n_board}板"
    names = [contracts.POINT_LABELS[p] for p in HIT_POINTS
             if seg in contracts.POINT_GROUPS[p]]
    return [f"结构不沾边:这题是{seg}{yin_yang}断{gap}天(累计跌{_pct(drop_pct)},"
            f"{yin_count}根阴线,末日{_entity_label(last_open, last_entity)}),"
            f"能对照的口诀:{'/'.join(names) if names else seg + '段无口诀'},都不沾",
            _MISS_LINE], "plain"


def _near_scheme_line(n_board: int, gap: int, yin_yang: str, drop_pct,
                      yin_count: int, last_open, last_entity) -> str | None:
    """「差口诀一条」的讲解(near 判定,只讲解不打标)。
    S1(2板断1~3):跌幅8~15 / 恰1阴 / 末日低开平开 三条,至少满足两条才算接近;
    S2(4板阴断1):末日实体阴 / 末日高开>2 两条,至少满足一条才算接近。"""
    if n_board == 2:
        drop_ok = drop_pct is not None and contracts.S1_DROP_LO < drop_pct <= contracts.S1_DROP_HI
        yin_ok = yin_count == contracts.S1_YIN_EXACT
        open_ok = last_open is not None and last_open <= contracts.S1_LAST_OPEN_MAX
        hits = sum([drop_ok, yin_ok, open_ok])
        if hits < 2:
            return None
        if drop_ok and yin_ok and not open_ok:
            return (f"S1 只差末日低/平开:断板期累计跌{_pct(drop_pct)}、恰{yin_count}根阴线"
                    f"都对,但末日开{_pct(last_open)}是高开——高开=磨不是杀,"
                    "洗得不够干脆(v2.1 剔除的28笔同类,去最好3笔后为负),不能打")
        if drop_ok and open_ok and not yin_ok:
            return (f"S1 只差阴线数:累计跌{_pct(drop_pct)}、末日开{_pct(last_open)}都对,"
                    f"但断板期有{yin_count}根实体阴——口诀要恰好1根一次洗透,"
                    f"{yin_count}根是反复磨,不能打")
        if yin_ok and open_ok and not drop_ok:
            what = "没跌够8%没洗到位" if (drop_pct or 0) > contracts.S1_DROP_HI else "跌超15%起不来"
            return (f"S1 只差跌幅:恰1根阴、末日开{_pct(last_open)}都对,但累计跌"
                    f"{_pct(drop_pct)}——{what},不能打")
        return None  # 三条全对=与 tag_point 结论矛盾(不该发生)
    if n_board == 4 and yin_yang == "阴" and gap == 1:
        ent_ok = last_entity == "阴"
        open_ok = last_open is not None and last_open > contracts.S2_OPEN_LO
        if ent_ok and not open_ok:
            return (f"S2 只差高开:末日收了实体阴,但末日开{_pct(last_open)}没高过+2——"
                    "平开低走=没人借热度出货,洗不透(同类27笔平均-2.62四年全亏),不能打")
        if open_ok and not ent_ok:
            return (f"S2 只差收阴:末日开{_pct(last_open)}高开够,但收盘不是实体阴——"
                    "高开没收阴=货没出干净,不是洗透,不能打")
        return None
    return None


def _matched_line(n_board: int, gap: int, drop, yin_count: int,
                  last_open, last_entity) -> str:
    """命中题的数据对照行:5板→断1天 · 末日开+3.2 走低收阴 / 2板→断2天 · 跌-10.2%(1阴) 末日低开。"""
    if n_board == 2:
        return (f"2板→断{gap}天 · 累计跌{_pct(drop)}(恰{yin_count}根阴) · "
                f"末日开{_pct(last_open)}{_low_open_label(last_open)}")
    if n_board == 4:
        return (f"4板→断{gap}天 · 末日开{_pct(last_open)}"
                f"{'高开' if (last_open or 0) > contracts.S2_TOPGAP_TH else ''}走低收阴")
    return f"{n_board}板→断{gap}天 · 末日{_entity_label(last_open, last_entity)}(扛住没跌)"


def _low_open_label(last_open) -> str:
    return "低/平开直接砸" if (last_open or 0) <= 0 else ""


def _entity_label(last_open, last_entity) -> str:
    ent = "收阴" if last_entity == "阴" else "收阳"
    return f"开{_pct(last_open)}{ent}" if last_open is not None else ent


def _pct(v) -> str:
    return f"{float(v):+.1f}" if v is not None and v == v else "--"


def _f(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def mix_question_keys(rows, per_point: int = MIX_PER_POINT,
                      trap_total: int = MIX_TRAP_TOTAL,
                      rng=None) -> list[tuple[str, str]]:
    """综合挑战卷抽题(纯函数,可注入种子复现)。

    rows = 题库轻量投影 [{decision_date, vt_symbol, point, trap_kind}]
    (point=标量列,trap_kind 从 payload 抽取,命中题为 None)。
    规则(对齐 hpr):好票=S1/S2/S3 每条随机 per_point 道;差票=MIX_TRAP_KINDS
    均分 trap_total,某类不够由后面的类补,总量落在好票的 1~3 倍区间。
    返回 [(decision_date, vt_symbol)]——洗牌在 service 层拉全量后统一做。"""
    import random
    rnd = random.Random(rng)
    by_point: dict[str, list[tuple[str, str]]] = {}
    by_trap: dict[str, list[tuple[str, str]]] = {k: [] for k in MIX_TRAP_KINDS}
    for r in rows:
        key = (str(r["decision_date"]), str(r["vt_symbol"]))
        point = r["point"]
        if point and point != "—":
            by_point.setdefault(str(point), []).append(key)
        elif r["trap_kind"] in by_trap:
            by_trap[str(r["trap_kind"])].append(key)
    picked: list[tuple[str, str]] = []
    for p in HIT_POINTS:
        pool_keys = by_point.get(p) or []
        picked.extend(rnd.sample(pool_keys, min(per_point, len(pool_keys))))
    quota = max(1, trap_total // len(MIX_TRAP_KINDS))
    deficit = 0
    for kind in MIX_TRAP_KINDS:
        want = quota + deficit
        got = rnd.sample(by_trap[kind], min(want, len(by_trap[kind])))
        picked.extend(got)
        deficit = want - len(got)
    return picked
