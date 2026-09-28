"""高位接力答题训练题库构建:回测事件 → 逐题K线窗口 + 答案 + 讲解。

题库口径说明:
- 事件范围 = done(未完剔除:没有E3结果无法判分) × 正常开盘(今开<9.5),与回测报告
  miss 口径一致。q4 起顶格票(今开≥9.5)不再出题:一字开盘排队也买不到,「买」这个
  选项现实中不存在,上千道送分废题只会稀释训练(主人2026-09-28拍板:「一字不是选
  不了么」);「开盘≥9.5一律不打」作为硬规则留在规则页,不占用题目。
- 收益 = E3%(产品卖出纪律,T+1合规:炸板→次日走(一字跌停顺延),封住→断板日,15日兜底;
  退出价=max(退出日收盘,(高+低)/2)(v4.3,主人拍板:中间价保底,收盘更高按实际算),
  与交割单同口径;E2/B2 低吸类回测统一按触板价买入计(实盘低开买成本更低)。
- K线 = 未复权日线(与回测同口径,除权日可见跳空,题卡页脚注明)。

版本纪律:讲解文案/题库结构变更必升 QUIZ_CONTENT_VERSION;版本串进表/进API/进前端
localStorage key——版本一变旧进度自动作废(容器版本漂移教训)。
"""
from __future__ import annotations

import pandas as pd

from alphaagent.server.services.high_relay import contracts, pool as pool_mod

QUIZ_CONTENT_VERSION = 12  # v12:口诀换行结构化(一板/二板/今天开一行一条)+按阴阳×二板档排序
BARS_BEFORE = 60          # 决策日前窗口上限(含MA暖机;前端默认只显末~30根)

_MISS_WIN_LINE = "正常开盘未命中对照2180笔:胜率41% 均-1.4——不挑就买是亏的"

# ── 综合挑战卷组卷规则(主人定 2026-09-28) ──
# 好票:七条口诀每条随机≥2道(无上限,固定2保证每套覆盖全部口诀);差票:好票=1:1~3:1,
# 取 1.5:1 偏挑战侧;差票=相似口诀票(形态接近+毒段)与阴阳反串票三等分混搭。
MIX_PER_POINT = 2
MIX_TRAP_TOTAL = 21
MIX_TRAP_KINDS = ("yin_yang", "near", "toxic")

# 阴阳反串判定:对面地基组完整命中某条口诀(链+换手+今开全判)。
# 弱开系冒泡洗盘/四板便捷两组都含,天然不会误判(哪组判都命中的票不是 miss)。
_OPPOSITE_GROUP4 = {"二接三阳": "二接三阴", "二接三阴": "二接三阳",
                    "三接四阳": "三接四阴", "三接四阴": "三接四阳"}


def quiz_rules_version() -> str:
    return f"{contracts.HPR_RULES_VERSION}·q{QUIZ_CONTENT_VERSION}"


def build_questions(E: pd.DataFrame, bars: pd.DataFrame) -> list[dict[str, object]]:
    """主入口:E=事件表(build_events 产物,含 _bar_i 行号),bars=同进程全量日线。

    返回可持久化行:[{decision_date, vt_symbol, year, month, seq, name, group4,
                     point, ret_pct, payload}];月内 seq 按(买入日,代码)编定。
    构建期自检:全部事件 tag_point 重算必须等于 E 行 point,不等即 raise。
    """
    # 顶格(今开≥9.5)剔除:一字开盘买不到,出题让选「买/不买」是废题(主人拍板)
    done = E[~E["未完"] & (E["买入开盘%"] < contracts.TODAY_CAP)].copy()
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
        # 揭示K线窗与持有天数按 E3 口径(v4.2,T+1):炸板=次日(一字跌停顺延),
        # 封住=断板日;不再用 E0 持有天数(曾致「炸板当日卖」却显示持有2天的矛盾)
        e3i = r["_e3_exit_i"]
        exit_off = int(e3i) - i if e3i is not None and e3i == e3i else 0
        after = [_bar(j) for j in range(i, i + exit_off + 1)]

        point = str(r["方案点"])
        should_buy = point != "—"
        group4 = str(r["四组"])
        n_board = int(r["N"])
        yang = str(r["阴阳"]) == "阳"
        buy_open = _f(r["买入开盘%"]) or 0.0
        b1_open, b2_open, b3_open = _f(r["b1开盘%"]), _f(r["b2开盘%"]), _f(r["b3开盘%"])
        b2_turn, b3_turn = _f(r["b2换手%"]), _f(r["b3换手%"])
        pre20 = _f(r["前20日涨幅%"])
        ret = _f(r["E3%"])
        d_date = pd.Timestamp(r["买入日"]).date()

        # 命中自检:E 是当次回放产物,point 必须与当前 tag_point 一致(防 contracts 漂移)
        recalc = pool_mod.tag_point(group4, b1_open, b2_open, b3_open,
                                    auction_pct=buy_open,
                                    b2_turn=b2_turn, b3_turn=b3_turn)
        if recalc != point:
            raise RuntimeError(
                f"题库构建自检失败:{r['名称']} {d_date} E标={point} 重算={recalc}")

        if should_buy:
            win = pool_mod.scheme_today_window(point, buy_open)  # v4.4多分支:返回今开实际命中的分支窗
            explain: dict[str, object] = {
                "kind": "hit",
                "scheme_no": point,
                "scheme_name": contracts.POINT_LABELS.get(point, point),
                "scheme_desc": contracts.POINT_DESC.get(point, ""),
                "psycho": contracts.POINT_PSYCHO.get(point, ""),
                "today_window": [win[0], win[1]] if win else None,
                "matched_line": _matched_line(n_board, b1_open, b2_open, b3_open,
                                              b2_turn, b3_turn, buy_open, win),
                "case_note": case_map.get((str(r["名称"]), d_date.isoformat())),
                "half_mountain": bool(yang and n_board == 2
                                      and pre20 is not None and 5 <= pre20 <= 15),
            }
        else:
            reasons, trap_kind = explain_miss(
                n_board=n_board, yang=yang, group4=group4,
                b1_open=b1_open, b2_open=b2_open, b3_open=b3_open,
                b2_turn=b2_turn, b3_turn=b3_turn,
                buy_open=buy_open, pre20_pct=pre20)
            # 阴阳反串:链形完整命中对面地基组的某条口诀(跨阴阳铁律陷阱,
            # 教学标签最鲜明,覆盖 near/toxic/plain),讲解首位说明
            opp_point = pool_mod.tag_point(
                _OPPOSITE_GROUP4[group4], b1_open, b2_open, b3_open,
                auction_pct=buy_open, b2_turn=b2_turn, b3_turn=b3_turn)
            if opp_point != "—":
                trap_kind = "yin_yang"
                opp_yang = "阳" if _OPPOSITE_GROUP4[group4].endswith("阳") else "阴"
                my_yang = "阳" if yang else "阴"
                reasons = [
                    f"链形是口诀【{contracts.POINT_LABELS.get(opp_point, opp_point)}】"
                    f"的形态,但那条只在{opp_yang}地基成立——这题是{my_yang}地基,"
                    "阴阳反了不能打(跨阴阳铁律:同一条链换个地基就是陷阱)",
                    *reasons[:2],
                ]
            explain = {"kind": "miss", "trap_kind": trap_kind, "reasons": reasons}

        hold_days = exit_off  # E3 口径持有交易日数(炸板=1,顺延>1,封住=到断板)
        payload = {
            "seq": int(r["seq"]),
            "vt_symbol": str(r["代码"]),
            "name": str(r["名称"]),
            "decision_date": d_date.isoformat(),
            "n_board": n_board,
            "group4": group4,
            "display": {
                "board_label": f"打{n_board + 1}板",
                "b1_open": b1_open, "b2_open": b2_open, "b3_open": b3_open,
                "b2_turn": b2_turn, "b3_turn": b3_turn,
                "pre20_pct": pre20,
                "auction_pct": buy_open,
                "prev_close": round(float(b_close[i - 1]), 2),
                "limit_price": _f(r["买价"]),
                "decision_open": round(float(b_open[i]), 2),
                # 决策日盘中最高涨幅(打板日冲到哪):主人要的第二决策信息——
                # 真实打板=看到冲到9%快触板才决定打不打,与回测「触板价买」口径自洽
                "day_high_pct": round((float(b_high[i]) / float(b_close[i - 1]) - 1) * 100, 2),
                "chain": str(r["链"]) if r["链"] == r["链"] else None,
            },
            "bars_before": before,
            "bars_after": after,
            "answer": {
                "point": point,
                "should_buy": should_buy,
                "ret_pct": ret,
                "buy_price": _f(r["买价"]),
                "sealed": sealed,
                "hold_days": hold_days,
                "exit_date": r["E3退出日"],
                "exit_price": _f(r["E3退出价"]),
                "exit_reason": r["E3原因"],
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
            "group4": group4,
            "point": point,
            "ret_pct": ret,
            "payload": payload,
        })
    return rows


def explain_miss(*, n_board: int, yang: bool, group4: str,
                 b1_open, b2_open, b3_open, b2_turn, b3_turn,
                 buy_open: float, pre20_pct) -> tuple[list[str], str]:
    """未命中题的「为什么不该买」:按优先级产 1~3 条人话理由(全部正常中文)。
    返回 (reasons, trap_kind):toxic=毒段规则命中/near=形态接近(链全符差条件)/
    plain=链形不沾边;yin_yang(阴阳反串)由 build_questions 单独判定覆盖。"""
    # 1. 顶格:终结论,只报这条(q4 起题库已剔顶格,此为防御分支,正常不会触发)
    if buy_open >= contracts.TODAY_CAP:
        return ([f"今开{_pct(buy_open)}顶格:排队也买不到,口诀一律不打(硬规则)"],
                "plain")
    reasons: list[str] = []
    if n_board == 2 and yang:
        # 2. 三连加速毒格(阳组)
        if (b1_open is not None and b1_open >= 3
                and b2_open is not None and b2_open >= 7 and buy_open >= 6):
            reasons.append("三连加速:一板≥3→二板强开→今开强开=一口气把三天涨幅透支完,"
                           "研究7笔全灭;强开接力的一板必须低/平(洗过)")
        # 3. 半山腰毒档(阳组)
        if pre20_pct is not None and 5 <= pre20_pct <= 15:
            reasons.append(f"阳组半山腰:首板前20日已涨{_pct(pre20_pct)},5~15是最毒档"
                           "(获利盘蹲在半山腰,接二板=接别人的第二波出货)")
        # 4/5. 二板死段/剧强段(阳组研究结论)
        if b2_open is not None and 1 <= b2_open < 3:
            reasons.append(f"二板开{_pct(b2_open)}落在1~3死段:阳组换手大小都救不动,"
                           "九条口诀的链区间直接排除")
        if b2_open is not None and 8.5 <= b2_open < 9.5:
            reasons.append(f"二板开{_pct(b2_open)}落在8.5~9.5剧强段:仅次一字的毒档,"
                           "今开6~9.5仅25%/-8.1")
    if n_board == 2 and not yang:
        # 阴组二板一字开盘:主人易误判成冒泡转强(「>7%就是走强」)——一字开盘
        # 是锁仓没换手的另一形态,不是B4的「强开」(主人点名:走强上限必须讲清楚)
        if b2_open is not None and b2_open >= 9.5:
            reasons.append(
                f"二板开{_pct(b2_open)}是一字开盘,不是冒泡转强的「强开」:口诀的强开是7~8.5"
                "(强而换手充分,11笔82%/+12.3);一字开盘=获利盘锁在里面没换手,"
                "阴地基接三板只是抛硬币(58笔50%/+0.8,和不挑就买一样),"
                "8.5~9.5剧强段更毒(6笔33%/-1.6)")
        # 阴组二板温吞段:一板低开×今开低开看着像弱开系捡尸(三低),但二板平开/微红
        # 不算低开——10笔30%/-1.7比不挑就买还烂(数据口径:一板<0×今开<0的阴地基)
        if (b1_open is not None and b1_open < 0
                and b2_open is not None and 0 <= b2_open < 2
                and buy_open < 0):
            reasons.append(
                f"二板开{_pct(b2_open)}是平开/微红,不是低开:弱开系捡尸要一板、二板、"
                "今天三个开盘都严格低开(<0),缺一不可;数据上二板0~2温吞段"
                "10笔仅30%/-1.7,比不挑就买还烂——平开的票没有恐慌割肉盘也没有"
                "承接资金,不上不下最毒")
    if n_board == 3:
        # 6. 三板换手毒(v4.4 分档:一字系(二板/三板一字)窗=3~5×今开6~9.5,非一字=10~20)
        is_yizi = ((b2_open is not None and b2_open >= 9.5)
                   or (b3_open is not None and b3_open >= 9.5))
        if b3_turn is not None and 5 <= buy_open < contracts.TODAY_CAP:
            if is_yizi:
                if not (3 <= b3_turn < 5):
                    reasons.append(f"三板换手{b3_turn:.1f}:一字系(锁仓板)的换手窗是3~5,"
                                   "四板便捷版一字系档不能打")
                elif buy_open < 6:
                    reasons.append(f"一字系换手{b3_turn:.1f}在3~5但今开{_pct(buy_open)}<6:"
                                   "温吞=让利没人接(5~6段全灭),四板便捷版一字系档须今开6~9.5")
            elif b3_turn < 10:
                reasons.append(f"三板换手{b3_turn:.1f}不在10~20:换手不足=没人气的假强缩量板,"
                               "四板便捷版(三板换手10~20、今开5~9.5直接打)不能打")
            elif b3_turn >= 20:
                reasons.append(f"三板换手{b3_turn:.1f}≥20:主力对倒出货,"
                               "四板便捷版(三板换手10~20、今开5~9.5直接打)不能打")
        # 7. 今开温吞毒段(换手合格但开得不冷不热)
        if (b3_turn is not None and 10 <= b3_turn < 20
                and 6 <= buy_open < 7):
            reasons.append(f"今开{_pct(buy_open)}落在6~7温吞段:不冷不热,四板便捷版体系内"
                           "也可以跳过的38%毒段(金核在7~8.5)")
    if reasons:
        return reasons[:3], "toxic"
    # 8. 兜底:形态接近(链全符差条件) 或 链形不沾边(含本组口诀清单),恒非 None
    nearest, near_hit = _nearest_scheme_line(group4, b1_open, b2_open, b3_open,
                                             b2_turn, b3_turn, buy_open)
    return [nearest, _MISS_WIN_LINE], ("near" if near_hit else "plain")


def _nearest_scheme_line(group4: str, b1_open, b2_open, b3_open,
                         b2_turn, b3_turn, buy_open: float) -> tuple[str, bool]:
    """「为什么不买」的兜底讲解(复刻 tag_point 判定收集明细,只讲解不打标)。
    返回 (文案, 是否形态接近)。

    两阶段(主人定:链腿不符的方案不能叫「最接近」——核心形态都不对,推荐即误导;
    阴阳分组必须说清楚):
    1. 链三腿全部符合的方案(形态对,只是换手/今开差一点) →
       「形态接近【名字:口诀】——这题xx,口诀要求xx,不能打」;
    2. 链全不符 → 「链形(一板开x × 二板开x)不在任何口诀区间——这题是X地基的
       二接三/三接四,能对照的口诀:名/名/名,都不沾」。
    """
    leg_names = ("一板", "二板", "三板")
    # 阶段1:链全符,只差换手/今开
    best: tuple[int, str] | None = None
    for s in contracts.SCHEMES:
        if group4 not in s["group4"]:
            continue
        chain_miss = False
        for rng, val in zip(s["chain"], (b1_open, b2_open, b3_open), strict=False):
            if rng is None:
                continue
            if val is None or not (rng[0] <= val < rng[1]):
                chain_miss = True
                break
        if chain_miss:
            continue
        fails: list[str] = []
        vol2 = s.get("vol2")
        if vol2 is not None and (b2_turn is None
                                 or not (vol2[0] <= b2_turn < vol2[1])):
            fails.append(f"二板换手{_num(b2_turn)},口诀要求{_fmt_range(vol2)}")
        v2wl = s.get("vol2_when_b1_low")
        if v2wl is not None and b1_open is not None and b1_open < contracts.CHAIN_FLAT_HI:
            if b2_turn is None or not (v2wl[0] <= b2_turn < v2wl[1]):
                fails.append(f"一板弱(<{contracts.CHAIN_FLAT_HI:g})时二板换手{_num(b2_turn)},"
                             f"口诀要求{_fmt_range(v2wl)}")
        vol3 = s.get("vol3")
        if vol3 is not None and (b3_turn is None
                                 or not (vol3[0] <= b3_turn < vol3[1])):
            fails.append(f"三板换手{_num(b3_turn)},口诀要求{_fmt_range(vol3)}")
        lo, hi = s["today"]  # type: ignore[misc]
        if not (lo <= buy_open < hi):
            fails.append(f"今开{_pct(buy_open)},口诀要求{_fmt_range((lo, hi))}")
        if not fails:
            continue  # 全过=与 tag_point 的 miss 结论矛盾(不该发生),不展示
        score = -len(fails)
        if best is None or score > best[0]:
            best = (score, f"形态接近口诀【{s['name']}:{s['desc']}】——"
                           f"这题{';'.join(fails[:2])},不能打")
    if best is not None:
        return best[1], True
    # 阶段2:链全不符——报链形 + 本组(阴阳分清)能对照的口诀清单(v4.4多分支共享名,去重)
    names = list(dict.fromkeys(
        str(s["name"]) for s in contracts.SCHEMES if group4 in s["group4"]))
    yang_label = "阳" if group4.endswith("阳") else "阴"
    pos_label = "二接三" if group4.startswith("二接三") else "三接四"
    chain_desc = f"一板开{_pct(b1_open)} × 二板开{_pct(b2_open)}"
    if pos_label == "三接四":
        chain_desc += f" × 三板开{_pct(b3_open)}"
    return (f"链形({chain_desc})不在任何口诀区间——这题是{yang_label}地基的{pos_label},"
            f"能对照的口诀:{'/'.join(names)},形态都不沾,不用买"), False


def _matched_line(n_board: int, b1_open, b2_open, b3_open,
                  b2_turn, b3_turn, buy_open: float, win) -> str:
    """命中题的数据对照行:一板开+8.4 × 二板开+10.0(换手28.8) → 今开+4.2 落在窗3~5。"""
    parts = [f"一板开{_pct(b1_open)}", f"二板开{_pct(b2_open)}"]
    if b2_turn is not None:
        parts[-1] += f"(换手{b2_turn:.1f})"
    if n_board == 3:
        seg = f"三板开{_pct(b3_open)}"
        if b3_turn is not None:
            seg += f"(换手{b3_turn:.1f})"
        parts.append(seg)
    line = " × ".join(parts) + f" → 今开{_pct(buy_open)}"
    if win:
        line += f" 落在窗{_fmt_range(win)}"
    return line


def _pct(v) -> str:
    return f"{float(v):+.1f}" if v is not None and v == v else "--"


def _num(v) -> str:
    return f"{float(v):.1f}" if v is not None and v == v else "--"


def _fmt_range(rng) -> str:
    lo, hi = rng
    if lo <= -90:
        return f"<{hi:g}"
    if hi >= 90:
        return f"≥{lo:g}"
    return f"{lo:g}~{hi:g}"


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
    规则(主人定 2026-09-28):好票=七条口诀每条随机 per_point 道(无上限,
    固定2即保证每套覆盖全部口诀);差票=MIX_TRAP_KINDS 均分 trap_total,
    某类不够由后面的类补,总量落在好票的 1~3 倍区间(14好×1.5=21差)。
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
    for pool_keys in by_point.values():
        picked.extend(rnd.sample(pool_keys, min(per_point, len(pool_keys))))
    quota = max(1, trap_total // len(MIX_TRAP_KINDS))
    deficit = 0
    for kind in MIX_TRAP_KINDS:
        want = quota + deficit
        got = rnd.sample(by_trap[kind], min(want, len(by_trap[kind])))
        picked.extend(got)
        deficit = want - len(got)
    return picked
