"""高位接力答题训练题库构建:回测事件 → 逐题K线窗口 + 答案 + 讲解。

题库口径说明:
- 事件范围 = done(未完剔除:没有E3结果无法判分) × 正常开盘(今开<9.5),与回测报告
  miss 口径一致。q4 起顶格票(今开≥9.5)不再出题:一字开盘排队也买不到,「买」这个
  选项现实中不存在,上千道送分废题只会稀释训练(主人2026-09-28拍板:「一字不是选
  不了么」);「开盘≥9.5一律不打」作为硬规则留在规则页,不占用题目。
- 收益 = E3%(产品卖出纪律,T+1合规:炸板→次日走,封住→断板日,15日兜底;
  退出价=退出日收盘价(尾盘只有收盘价;收盘跌停仅一字死封顺延,其余按跌停价
  卖出——v6.7),与交割单同口径;A3/B2 低吸类回测统一按触板价买入计
  (实盘低开买成本更低)。
- K线 = 未复权日线(与回测同口径,除权日可见跳空,题卡页脚注明)。

版本纪律:讲解文案/题库结构变更必升 QUIZ_CONTENT_VERSION;版本串进表/进API/进前端
localStorage key——版本一变旧进度自动作废(容器版本漂移教训)。
"""
from __future__ import annotations

import pandas as pd

from alphaagent.server.services.high_relay import contracts, pool as pool_mod

QUIZ_CONTENT_VERSION = 36  # v36:逐月动态组切换(主人2026-10-06拍板「按照当前题所属月自动切换口诀集」,起因=主人审计「做2025年的题拿的是2024年还是未来函数2025年本身」——查实题库原用年切(2023-01硬编码分界)与动态组月滚切换史(2023-07才weak→strong)有7个月错位:2023-01~06题库标强市题但当时真实启用弱市组(八条命中10笔被标该买,按当时纪律不该出手);2020-01~06暖机双开段仅八条命中10笔(厦门信达C3/日出东方B1等)被标不该买,双开纪律下是该买——合计18题标签与「当时真实启用组」不一致;v36改法=_dyn_month_states逐月复现动态组(判据与service._dyn_group_state同源:该月末为止近DYN_GROUP_WINDOW个交易月两组各自命中笔E3均值高者启用,样本不足8笔/均非正=双开;每月只用当月及之前数据,无未来函数;实测2020-01~06 both/2020-07~2023-06 weak/2023-08起strong,2023-07无出手月继承weak),题目该买=当月启用组命中(weak月=K系·八条命中只是雷达;strong月=八条;both月=两组任一,双命中取强市编号),miss讲解按月状态选组(weak/both月=弱市最近邻,both月reasons注明双开;strong月=强市最近邻),弱市判定格(一板换手/前波60/距新高)下发条件从「2023前」改为「当月弱市组启用」(weak/both月),payload新增dyn_state字段(题所属月组状态)供前端chip/徽章渲染,repository overview按年聚合dyn_states(2023年=切组年,前端年份chip蓝紫渐变标注);无未来函数:判某月状态只用该月及之前11个交易月;# v35:题库扩弱市组(主人2026-10-06拍板动态组全链路联动):事件回放起点2023-01→2020-01(弱市组K系定型样本入题库),2020-22段题目该买=K系命中(tag_weak判定;弱市时代强市八条不启用——命中也只是雷达,与动态组纪律一致),2023+段照旧强市组;命中讲解=弱市速查表行(WEAK_CHEAT_ROWS)+K系子项全名;miss讲解=弱市版两阶段最近邻(_nearest_weak_line:链全符差腿→形态接近/链形不沾边),阴阳反串题=tag_weak对面组完整命中(K5/K7/K9只打阴·K3只打阳);题面新增弱市组判定格:一板换手(K4/K7腿)/前波60日(K5命根)/距60日新高(K3贴顶),题面可判原则;综合挑战卷好票池自动含K系六条(by_point 泛化);弱市miss对照行=同期全池1934笔35%/-1.34;# v34:miss题讲解配「错误口诀」表格+红列(主人2026-10-05「错误的口诀也应该给出表格,把错误的某一列标记红色提示哪里没有匹配上」):explain_miss 四元组加 scheme_row(毒段/形态接近题=最接近口诀的速查表行,链形不沾边=None),下发 row_fails 列键(题面格子标签映射:换手归板位列/地基日各腿归地基日列/半山腰无列丢弃);阴阳反串题表格=对面口诀行,红列只标「组」(对面全符唯一错阴阳,原组腿标签不进对面行防误导);hit 题对称下发 row_fails=[];# v33:hpr-v6.11 C2一拆二——四板便捷退役:实体板归C2四板换手/一字锁仓归C3一字换手(主人「这明显不是一个口诀,口诀分界线没弄明白」),判定集合零漂移纯编号手术,题库重打标C2 66→56+C3 10;讲解口诀名同步(【C2·四板换手】【C3·一字换手】);# v32:C2口诀直白化+判分红格(主人2026-10-05「读不懂/前后矛盾/哪里不符合标红」):C2两条腿弃研究黑话(先手小阳/锚点)改直白句式,「首板前日」统一叫「地基日」与题面格子同名;速查表「附加」列改「地基日」列(腿全部进主列正常字号);miss讲解加fail_fields(题面格子标签,前端判分后红格标出不符合的腿);题面地基日涨幅数字单源(display.foundation_chg下发,修前端拿K线c/o重算与判定字段两口径+1.7/+1.8裂开);判定零漂移;# v31:命中讲解卡与规则页速查表统一(主人2026-10-05「答题这里没有统一」):scheme_name 改子项全名(A1 双平贴零·低开等强开式,tag_scheme 定位分支),讲解改表格行(scheme_row=速查表命中行:地基/一板/二板/三板/今天开/附加/成绩),删话术字段(scheme_desc/psycho/hold_note/case_note/half_mountain/today_window——「不需要其他多余的话术」);判定零漂移(tag_scheme=tag_point 原逻辑拆壳);# v30:hpr-v6.10——弱票地基腿换K线姿态尺(站线上/骑线=接,贴线/掉线下=不接),题面「地基距20日线」数值格改「地基姿态」标签,B2 7→11笔/B3 5→7笔(信隆+51/东百+31.8回归,神雾-25.9/新乡-18.3挡外);# v29:A1口诀文案人话化(主人反馈「低开→6~9.5/平开→3~6」箭头式读不懂,改「一板低开(<0)的,等今天强开6~9.5」句式,判定零漂移仅文案);# v28:hpr-v6.9——A1交叉反转双分支(一板低开<0等强开6~9.5/一板平开0~3等温开3~6,题库重打标:长白山归miss/津药·滨海·国创等10笔入A1);# v27:hpr-v6.8——C2锚点腿(前期涨停高点贴着没过/超5%不碰)+A3退役(题库重打标,利君/京能/万安归miss)+题面补「距前涨停高」格;# v26:题面补「地基距20日线」格(v6.6弱票腿判定字段上题面,做题可判,主人2026-10-04做题撞出)+修讲解「不能打,不能打」重复;# v25:跌停口径修正(hpr-v6.7):仅一字死封顺延,其余按跌停价卖出;# v24:弱票三口诀加地基腿(hpr-v6.6):A3/B2/B3地基距MA20<5%不命中;# v23:退出价口径升级(hpr-v6.5):E3改纯收盘价+跌停顺延,去v4.3中间价美化(尾盘只有收盘价);收益列随v6.5重算
BARS_BEFORE = 60          # 决策日前窗口上限(含MA暖机;前端默认只显末~30根)

# v7.3 逐月动态组状态:单一事实源=contracts.dyn_month_states(报告物化
# payload["dyn_month_states"],assemble_report 统一构建)——题库/回测/交割单/
# koujue/实时全部读同一份,判据只改一处。无命中月继承前态用 contracts.dyn_state_at。

_MISS_WIN_LINE = "正常开盘未命中对照2180笔:胜率41% 均-1.4——不挑就买是亏的"
_WEAK_MISS_WIN_LINE = "弱市同期全池(乱买)1934笔:胜率35% 均-1.34——不挑就买是亏的"

# ── 综合挑战卷组卷规则(主人定 2026-09-28) ──
# 好票:七条口诀每条随机≥2道(无上限,固定2保证每套覆盖全部口诀);差票:好票=1:1~3:1,
# 取 1.5:1 偏挑战侧;差票=相似口诀票(形态接近+毒段)与阴阳反串票三等分混搭。
MIX_PER_POINT = 2
# 陷阱票数每卷随机(主人定 2026-09-29:陷阱:好票从固定1.5:1提到2:1~2.5:1随机,
# 负样本加密度+猜不出节奏防"后面全是陷阱"的先验;上限2.5防无脑全拒混分)
MIX_TRAP_MIN = 28
MIX_TRAP_MAX = 35
MIX_TRAP_KINDS = ("yin_yang", "near", "toxic")

# 阴阳反串判定:对面地基组完整命中某条口诀(链+换手+今开全判)。
# C1冒泡转弱/四板换手两组都含,天然不会误判(哪组判都命中的票不是 miss)。
_OPPOSITE_GROUP4 = {"二接三阳": "二接三阴", "二接三阴": "二接三阳",
                    "三接四阳": "三接四阴", "三接四阴": "三接四阳"}


def quiz_rules_version() -> str:
    return f"{contracts.HPR_RULES_VERSION}·q{QUIZ_CONTENT_VERSION}"


def build_questions(E: pd.DataFrame, bars: pd.DataFrame,
                    dyn_states: dict[str, str] | None = None) -> list[dict[str, object]]:
    """主入口:E=事件表(build_events 产物,含 _bar_i 行号),bars=同进程全量日线,
    dyn_states=月→组状态(单一事实源=报告物化 dyn_month_states,由 rebuild 注入;
    缺省/空=双开兜底)。

    返回可持久化行:[{decision_date, vt_symbol, year, month, seq, name, group4,
                     point, ret_pct, payload}];月内 seq 按(买入日,代码)编定。
    构建期自检:全部事件 tag_point 重算必须等于 E 行 point,不等即 raise。
    """
    # 顶格(今开≥9.5)剔除:一字开盘买不到,出题让选「买/不买」是废题(主人拍板)
    done = E[~E["未完"] & (E["买入开盘%"] < contracts.TODAY_CAP)].copy()
    # v7.3 逐月组状态(该买=当月启用组命中,无未来函数):物化结果由调用方注入;
    # 缺省/空=双开兜底(dyn_state_at 对未知月返回 both)
    month_states = dyn_states or {}
    done.sort_values(["月", "买入日", "代码"], inplace=True)
    done["seq"] = done.groupby("月").cumcount() + 1

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
        weak_no = str(r["弱口诀"]) if r["弱口诀"] == r["弱口诀"] else "—"
        # v7.3 按月动态组:该买=当月启用组命中——weak 月=K系(八条命中只是雷达)、
        # strong 月=八条、both 月(暖机双开)=两组任一(双命中取强市编号,讲解按强市行)
        mstate = contracts.dyn_state_at(month_states, str(r["月"]))
        if mstate == "weak":
            point = weak_no
        elif mstate == "both" and point == "—":
            point = weak_no
        should_buy = point != "—"
        group4 = str(r["四组"])
        n_board = int(r["N"])
        yang = str(r["阴阳"]) == "阳"
        buy_open = _f(r["买入开盘%"]) or 0.0
        b1_open, b2_open, b3_open = _f(r["b1开盘%"]), _f(r["b2开盘%"]), _f(r["b3开盘%"])
        b2_turn, b3_turn = _f(r["b2换手%"]), _f(r["b3换手%"])
        pre20 = _f(r["前20日涨幅%"])
        pre10 = _f(r["前10日涨幅%"])
        foundation_chg = _f(r["地基涨跌%"])
        ret = _f(r["E3%"])
        d_date = pd.Timestamp(r["买入日"]).date()

        # 命中自检:E 是当次回放产物,point 必须与当前 tag 重算一致(防 contracts 漂移);
        # v7.3 判据组按月状态:weak 月只算 tag_weak,strong 月只算 tag_scheme,
        # both 月两组都算;命中题的编号组必须与重算一致
        prev_wave60 = (int(r["前波60日最高板"])
                       if r["前波60日最高板"] == r["前波60日最高板"] else None)
        dist_h60 = _f(r["距60日新高%"])
        b1_turn = _f(r["b1换手%"])
        weak_group_on = mstate in ("weak", "both")
        strong_group_on = mstate in ("strong", "both")
        hit_weak = hit_scheme = None
        if weak_group_on:
            hit_weak = pool_mod.tag_weak(group4, b1_open, b2_open, b3_open,
                                         auction_pct=buy_open, b1_turn=b1_turn,
                                         b2_turn=b2_turn, b3_turn=b3_turn,
                                         foundation_chg=foundation_chg,
                                         prev_wave60=prev_wave60, dist_h60=dist_h60)
        if strong_group_on:
            hit_scheme = pool_mod.tag_scheme(group4, b1_open, b2_open, b3_open,
                                             auction_pct=buy_open,
                                             b2_turn=b2_turn, b3_turn=b3_turn,
                                             foundation_chg=foundation_chg,
                                             pre10_pct=pre10,
                                             foundation_pose=(r["地基姿态"] if r["地基姿态"] == r["地基姿态"] else None),
                                             anchor_pos=_f(r["锚位%"]),
                                             anchor_dist=(int(r["锚距"]) if r["锚距"] == r["锚距"] and r["锚距"] is not None else None))
        if should_buy:
            if point.startswith("K"):
                if not hit_weak or str(hit_weak["no"]) != point:
                    raise RuntimeError(
                        f"题库构建自检失败(弱市组):{r['名称']} {d_date} E标={point} "
                        f"重算={str(hit_weak['no']) if hit_weak else '—'}")
            elif not hit_scheme or str(hit_scheme["no"]) != point:
                raise RuntimeError(
                    f"题库构建自检失败:{r['名称']} {d_date} E标={point} "
                    f"重算={str(hit_scheme['no']) if hit_scheme else '—'}")
        elif mstate == "weak" and weak_no != "—":
            # weak 月 K系必命中(weak 月 point=weak_no≠—不可能走到这),防御性校验
            raise RuntimeError(
                f"题库构建自检失败(弱市月):{r['名称']} {d_date} weak标={weak_no} point={point}")

        if should_buy:
            # 讲解与规则页速查表统一(q31,主人2026-10-05):子项全名(A1 双平贴零·低开等强开)
            # + 速查表命中行表格化讲解,替代口诀全文/主力心理/持有纪律等话术;
            # v7.3 按命中编号选讲解组:K系=弱市速查表行(WEAK_CHEAT_ROWS),八条照旧
            if point.startswith("K"):
                sub = str(hit_weak.get("sub") or "")  # type: ignore[union-attr]
                explain: dict[str, object] = {
                    "kind": "hit",
                    "scheme_no": point,
                    "scheme_name": contracts.WEAK_POINT_LABELS.get(point, point)
                                   + (f"·{sub}" if sub else ""),
                    "scheme_row": _weak_cheat_row(point),
                    "matched_line": _matched_line(n_board, b1_open, b2_open, b3_open,
                                                  b2_turn, b3_turn, buy_open,
                                                  tuple(hit_weak["today"])),  # type: ignore[index]
                    "fail_fields": [],
                    "row_fails": [],
                }
            else:
                win = pool_mod.scheme_today_window(point, buy_open)  # v4.4多分支:返回今开实际命中的分支窗
                sub = str(hit_scheme.get("sub") or "")  # type: ignore[union-attr]
                explain = {
                    "kind": "hit",
                    "scheme_no": point,
                    "scheme_name": contracts.POINT_LABELS.get(point, point)
                                   + (f"·{sub}" if sub else ""),
                    "scheme_row": _cheat_row(point, sub),
                    "matched_line": _matched_line(n_board, b1_open, b2_open, b3_open,
                                                  b2_turn, b3_turn, buy_open, win),
                    "fail_fields": [],
                    "row_fails": [],
                }
        else:
            if mstate != "strong":
                # weak/both 月 miss 题:弱市组两阶段最近邻 + 阴阳反串(K5/K7/K9 只打
                # 阴·K3 只打阳,tag_weak 对面组完整命中=反串陷阱);
                # both 月(暖机双开)两组都不命中才到这,reasons 首行注明双开语境
                nearest, near_hit, fail_fields, miss_row = _nearest_weak_line(
                    group4, b1_open, b2_open, b3_open,
                    b1_turn, b2_turn, b3_turn, buy_open,
                    foundation_chg=foundation_chg, prev_wave60=prev_wave60,
                    dist_h60=dist_h60)
                reasons = [nearest] if near_hit else [nearest, _WEAK_MISS_WIN_LINE]
                if mstate == "both":
                    reasons = ["该月双开(暖机期,近12月样本不足):两组口诀都不命中——不挑就买是亏的",
                               *reasons]
                trap_kind = "near" if near_hit else "plain"
                opp_scheme = pool_mod.tag_weak(
                    _OPPOSITE_GROUP4[group4], b1_open, b2_open, b3_open,
                    auction_pct=buy_open, b1_turn=b1_turn,
                    b2_turn=b2_turn, b3_turn=b3_turn,
                    foundation_chg=foundation_chg,
                    prev_wave60=prev_wave60, dist_h60=dist_h60)
                opp_point = str(opp_scheme["no"]) if opp_scheme else "—"
                row_fails = _row_fails(fail_fields)
                if opp_point != "—":
                    trap_kind = "yin_yang"
                    opp_yang = "阳" if _OPPOSITE_GROUP4[group4].endswith("阳") else "阴"
                    my_yang = "阳" if yang else "阴"
                    reasons = [
                        f"链形是弱市口诀【{contracts.WEAK_POINT_LABELS.get(opp_point, opp_point)}】"
                        f"的形态,但那条只在{opp_yang}地基成立——这题是{my_yang}地基,"
                        "阴阳反了不能打(跨阴阳铁律)",
                        *reasons[:1],
                    ]
                    fail_fields = ["阴阳", *fail_fields]
                    # 反串题表格=对面口诀行,红列只标「组」(对面全符唯一错阴阳)
                    miss_row = _weak_cheat_row(opp_point)
                    row_fails = ["yang"]
                explain = {"kind": "miss", "trap_kind": trap_kind,
                           "reasons": reasons, "fail_fields": fail_fields,
                           "scheme_row": miss_row, "row_fails": row_fails}
            else:
                reasons, trap_kind, fail_fields, miss_row = explain_miss(
                    n_board=n_board, yang=yang, group4=group4,
                    b1_open=b1_open, b2_open=b2_open, b3_open=b3_open,
                    b2_turn=b2_turn, b3_turn=b3_turn,
                    buy_open=buy_open, pre20_pct=pre20,
                    foundation_chg=foundation_chg, pre10_pct=pre10,
                    foundation_pose=(r["地基姿态"] if r["地基姿态"] == r["地基姿态"] else None),
                                        anchor_pos=_f(r["锚位%"]),
                                        anchor_dist=(int(r["锚距"]) if r["锚距"] == r["锚距"] and r["锚距"] is not None else None))
                # 阴阳反串:链形完整命中对面地基组的某条口诀(跨阴阳铁律陷阱,
                # 教学标签最鲜明,覆盖 near/toxic/plain),讲解首位说明
                opp_scheme = pool_mod.tag_scheme(
                    _OPPOSITE_GROUP4[group4], b1_open, b2_open, b3_open,
                    auction_pct=buy_open, b2_turn=b2_turn, b3_turn=b3_turn,
                    foundation_chg=foundation_chg, pre10_pct=pre10,
                    foundation_pose=(r["地基姿态"] if r["地基姿态"] == r["地基姿态"] else None),
                                        anchor_pos=_f(r["锚位%"]),
                                        anchor_dist=(int(r["锚距"]) if r["锚距"] == r["锚距"] and r["锚距"] is not None else None))
                opp_point = str(opp_scheme["no"]) if opp_scheme else "—"
                row_fails = _row_fails(fail_fields)
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
                    fail_fields = ["阴阳", *fail_fields]
                    # 反串题表格=对面口诀行,红列只标「组」(对面口诀本身全符,
                    # 唯一错的是地基阴阳;原组视角的腿标签不进对面行,防误导)
                    miss_row = _cheat_row(opp_point, str(opp_scheme.get("sub") or ""))
                    row_fails = ["yang"]
                explain = {"kind": "miss", "trap_kind": trap_kind, "reasons": reasons,
                           "fail_fields": fail_fields, "scheme_row": miss_row,
                           "row_fails": row_fails}

        hold_days = exit_off  # E3 口径持有交易日数(炸板=1,顺延>1,封住=到断板)
        payload = {
            "seq": int(r["seq"]),
            "vt_symbol": str(r["代码"]),
            "name": str(r["名称"]),
            "decision_date": d_date.isoformat(),
            # v7.3 该题所属月的动态组状态(weak/strong/both):前端 era chip/启用徽章
            # 按月渲染,不再前端按日期硬切(2023 年 1~6 月=弱市组题)
            "dyn_state": mstate,
            "n_board": n_board,
            "group4": group4,
            "display": {
                "board_label": f"打{n_board + 1}板",
                "b1_open": b1_open, "b2_open": b2_open, "b3_open": b3_open,
                "b2_turn": b2_turn, "b3_turn": b3_turn,
                "pre20_pct": pre20, "pre10_pct": pre10,
                # v6.10 弱票腿判定字段(B2/B3 地基K线姿态):口诀第四行要求的数据
                # 必须上题面,否则做题人拿隐藏变量被毙(主人2026-10-04做题撞出);
                # v6.10 起显示姿态标签(站线上/骑线/贴线/掉线下),数值留参考
                "foundation_pose": (r["地基姿态"] if r["地基姿态"] == r["地基姿态"] else None),
                # 地基日涨幅(判定同源单源下发,q32:此前前端拿K线c/o-1重算=开盘基准,
                # 与判定字段(前收盘基准)两口径,边界票+1.7/+1.8对不上)
                "foundation_chg": foundation_chg,
                "foundation_ma20": _f(r["地基距MA20%"]),
                # v6.8 C2 锚点腿判定字段:地基收盘距前期涨停高点(题面可判原则)
                "anchor_pos": _f(r["锚位%"]),
                "auction_pct": buy_open,
                "prev_close": round(float(b_close[i - 1]), 2),
                "limit_price": _f(r["买价"]),
                "decision_open": round(float(b_open[i]), 2),
                # 决策日盘中最高涨幅(打板日冲到哪):主人要的第二决策信息——
                # 真实打板=看到冲到9%快触板才决定打不打,与回测「触板价买」口径自洽
                "day_high_pct": round((float(b_high[i]) / float(b_close[i - 1]) - 1) * 100, 2),
                "chain": str(r["链"]) if r["链"] == r["链"] else None,
                # v7.3 弱市组题判定格(题面可判原则):一板换手(K4/K7实体板腿)/
                # 前波60日(K5命根=0)/距60日新高(K3贴顶腿);当月弱市组启用(weak/both)即下发
                **({"b1_turn": b1_turn, "prev_wave60": prev_wave60,
                    "dist_h60": dist_h60} if weak_group_on else {}),
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
                 buy_open: float, pre20_pct, foundation_chg=None,
                 pre10_pct=None, foundation_pose=None,
                 anchor_pos=None, anchor_dist=None) -> tuple[list[str], str, list[str], dict | None]:
    """未命中题的「为什么不该买」:按优先级产 1~3 条人话理由(全部正常中文)。
    返回 (reasons, trap_kind, fail_fields, scheme_row):
    fail_fields=不符合的腿对应的题面格子标签(前端判分后红格标出,主人2026-10-05
    「哪里不符合标红色」);scheme_row=最接近口诀的速查表行(主人2026-10-05
    「错误的口诀也应该给出表格」——毒段/形态接近题=链全符差一腿的口诀行,
    链形不沾边题=None 无行)。trap_kind:
    toxic=毒段规则命中/near=形态接近(链全符差条件)/plain=链形不沾边;
    yin_yang(阴阳反串)由 build_questions 单独判定覆盖。"""
    # 1. 顶格:终结论,只报这条(q4 起题库已剔顶格,此为防御分支,正常不会触发)
    if buy_open >= contracts.TODAY_CAP:
        return ([f"今开{_pct(buy_open)}顶格:排队也买不到,口诀一律不打(硬规则)"],
                "plain", ["今开"], None)
    reasons: list[str] = []
    ffails: list[str] = []
    if n_board == 2 and yang:
        # 2. 三连加速毒格(阳组)
        if (b1_open is not None and b1_open >= 3
                and b2_open is not None and b2_open >= 7 and buy_open >= 6):
            reasons.append("三连加速:一板≥3→二板强开→今开强开=一口气把三天涨幅透支完,"
                           "研究7笔全灭;强开接力的一板必须低/平(洗过)")
            ffails.append("一板开")
        # 3. 半山腰毒档(阳组)
        if pre20_pct is not None and 5 <= pre20_pct <= 15:
            reasons.append(f"阳组半山腰:首板前20日已涨{_pct(pre20_pct)},5~15是最毒档"
                           "(获利盘蹲在半山腰,接二板=接别人的第二波出货)")
            ffails.append("首板前20日")
        # 3b. 前10日透支(v6.3 A2 腿):近10日急拉≥10%的高位一字=末段冲刺,
        # 阳组专属毒(阴组同形态反向肥——阴地基的近期涨幅是洗后启动初期)
        if pre10_pct is not None and pre10_pct >= 10 and 7 <= buy_open < 8.5:
            reasons.append(
                f"首板前10个交易日已涨{_pct(pre10_pct)}(≥10%):近端涨幅透支,"
                "这时的一字板是高位末段冲刺不是锁仓启动——一字转强不能打"
                "(此毒阳组专属:阴地基的近期涨幅是洗完刚启动,同形态反而肥)")
            ffails.append("首板前10日")
        # 4/5. 二板死段/剧强段(阳组研究结论)
        if b2_open is not None and 1 <= b2_open < 3:
            reasons.append(f"二板开{_pct(b2_open)}落在1~3死段:阳组换手大小都救不动,"
                           "九条口诀的链区间直接排除")
            ffails.append("二板开")
        if b2_open is not None and 8.5 <= b2_open < 9.5:
            reasons.append(f"二板开{_pct(b2_open)}落在8.5~9.5剧强段:仅次一字的毒档,"
                           "今开6~9.5仅25%/-8.1")
            ffails.append("二板开")
    if n_board == 2 and not yang:
        # 阴组二板一字开盘:主人易误判成冒泡转强(「>7%就是走强」)——一字开盘
        # 是锁仓没换手的另一形态,不是B4的「强开」(主人点名:走强上限必须讲清楚)
        if b2_open is not None and b2_open >= 9.5:
            reasons.append(
                f"口诀【B1·强开系·续强】「二板开7~8.5(一字开盘≥9.5不算)、"
                f"今天开6~9.5、一板不限」——这题二板开{_pct(b2_open)}是一字开盘,"
                "口诀明写不算:一字=获利盘锁在里面没换手,阴地基接三板只是抛硬币"
                "(58笔50%/+0.8,和不挑就买一样)")
            ffails.append("二板开")
        # 阴组二板温吞段:一板低开×今开低开看着像捡尸(三低),但二板平开/微红
        # 不算低开——10笔30%/-1.7比不挑就买还烂(数据口径:一板<0×今开<0的阴地基)
        if (b1_open is not None and b1_open < 0
                and b2_open is not None and 0 <= b2_open < 2
                and buy_open < 0):
            reasons.append(
                f"口诀【B2·捡尸】「二板开<0或2~3、今天开<0、一板开<0」"
                f"——这题二板开{_pct(b2_open)}是平开/微红,不在口诀窗:"
                "捡尸要三个开盘都严格低开(<0),缺一不可;二板0~2温吞段"
                "10笔仅30%/-1.7,比不挑就买还烂——平开的票没有恐慌割肉盘也没有"
                "承接资金,不上不下最毒")
            ffails.append("二板开")
    if n_board == 3:
        # 6. 三板换手毒(v4.4 分档:一字系(二板/三板一字)窗=3~5×今开6~9.5,非一字=10~20)
        is_yizi = ((b2_open is not None and b2_open >= 9.5)
                   or (b3_open is not None and b3_open >= 9.5))
        if b3_turn is not None and 5 <= buy_open < contracts.TODAY_CAP:
            if is_yizi:
                if not (3 <= b3_turn < 5):
                    reasons.append(f"口诀【C3·一字换手】「二板或三板一字"
                                   f"——三板换手3~5、今天开6~9.5」"
                                   f"——这题三板换手{b3_turn:.1f}不在3~5,不能打")
                    ffails.append("三板开")
                elif buy_open < 6:
                    reasons.append(f"口诀【C3·一字换手】「二板或三板一字"
                                   f"——三板换手3~5、今天开6~9.5」"
                                   f"——这题换手{b3_turn:.1f}虽在3~5,今开{_pct(buy_open)}<6"
                                   "温吞=让利没人接(5~6段全灭),不能打")
                    ffails.append("今开")
            elif b3_turn < 10:
                reasons.append(f"口诀【C2·四板换手】「三板换手10~20=有人真接力,今天开5~9.5,打」"
                               f"——这题三板换手{b3_turn:.1f}不在10~20:"
                               "换手不足=没人气的假强缩量板,不能打")
                ffails.append("三板开")
            elif b3_turn >= 20:
                reasons.append(f"口诀【C2·四板换手】「三板换手10~20=有人真接力,今天开5~9.5,打」"
                               f"——这题三板换手{b3_turn:.1f}不在10~20:主力对倒出货,不能打")
                ffails.append("三板开")
        # 7. 今开温吞毒段(换手合格但开得不冷不热)
        if (b3_turn is not None and 10 <= b3_turn < 20
                and 6 <= buy_open < 7):
            reasons.append(f"口诀【C2·四板换手】「三板换手10~20=有人真接力,今天开5~9.5,打」"
                           f"——这题今开{_pct(buy_open)}落在6~7温吞段:不冷不热,"
                           "口诀窗内也可以跳过的38%毒段(金核在7~8.5)")
            ffails.append("今开")
        # 8. 先手小阳×三板温开(v6.2):首板前一天有人先手拉过1~3个点,
        # 三板还温着(<7)没人接=半路残局;三板强开(≥7)是主力连续行为照打
        if (foundation_chg is not None and 1 <= foundation_chg < 3
                and b3_open is not None and b3_open < 7
                and 5 <= buy_open < contracts.TODAY_CAP):
            reasons.append(
                f"口诀【C2·四板换手】「地基日涨了1~3个点——三板要开到7以上才打,"
                f"温开不碰」——这题地基日涨{_pct(foundation_chg)}×"
                f"三板开{_pct(b3_open)}温着没人接=有人先手的半路残局,不能打")
            ffails.append("地基日")
        # 9. 锚点腿(v6.8):地基收盘贴断板高点不涨=没能量 / 超前期涨停高点5%=妖顶透支
        if (anchor_pos is not None and b3_turn is not None
                and (10 <= b3_turn < 20 or (b2_open is not None and b2_open >= 9.5)
                     or (b3_open is not None and b3_open >= 9.5))
                and 5 <= buy_open < contracts.TODAY_CAP):
            if -2.0 <= anchor_pos < 0.0 and anchor_dist is not None and anchor_dist <= 7:
                reasons.append(
                    f"口诀【C2·四板换手】「前面涨停过的——地基日贴着涨停价上不去,"
                    f"不碰」——这题地基日收盘距前期涨停高点{anchor_pos:+.1f}%"
                    f"(刚断{anchor_dist}日贴着不动)=断单板没能量,不能打")
                ffails.append("距前涨停高")
            elif anchor_pos >= 5.0:
                reasons.append(
                    f"口诀【C2·四板换手】「前面涨停过的——已高出涨停价5个点以上,"
                    f"不碰」——这题已超前期涨停高点{anchor_pos:+.1f}%"
                    "=连板妖顶透支接最后一棒,不能打")
                ffails.append("距前涨停高")
    if reasons:
        # 毒段题也配最接近口诀行(链全符差一腿,主人「错误的口诀也应该给出表格」);
        # 链形不沾边 → 行 None(无错误口诀可对照)
        *_, row = _nearest_scheme_line(
            group4, b1_open, b2_open, b3_open,
            b2_turn, b3_turn, buy_open,
            foundation_chg, pre10_pct,
            foundation_pose, anchor_pos, anchor_dist)
        return reasons[:3], "toxic", ffails[:4], row
    # 9. 兜底:形态接近(链全符差差条件) 或 链形不沾边(含本组口诀清单),恒非 None
    nearest, near_hit, near_ffails, row = _nearest_scheme_line(
        group4, b1_open, b2_open, b3_open,
        b2_turn, b3_turn, buy_open,
        foundation_chg, pre10_pct,
        foundation_pose, anchor_pos, anchor_dist)
    return [nearest, _MISS_WIN_LINE], ("near" if near_hit else "plain"), near_ffails, row


def _nearest_scheme_line(group4: str, b1_open, b2_open, b3_open,
                         b2_turn, b3_turn, buy_open: float,
                         foundation_chg=None, pre10_pct=None,
                         foundation_pose=None, anchor_pos=None,
                         anchor_dist=None) -> tuple[str, bool, list[str], dict | None]:
    """「为什么不买」的兜底讲解(复刻 tag_point 判定收集明细,只讲解不打标)。
    返回 (文案, 是否形态接近, fail格子标签, 最接近口诀的速查表行)。

    两阶段(主人定:链腿不符的方案不能叫「最接近」——核心形态都不对,推荐即误导;
    阴阳分组必须说清楚):
    1. 链三腿全部符合的方案(形态对,只是换手/今开差一点) →
       「形态接近【名字:口诀】——这题xx,口诀要求xx,不能打」+ 该口诀速查表行;
    2. 链全不符 → 「链形(一板开x × 二板开x)不在任何口诀区间——这题是X地基的
       二接三/三接四,能对照的口诀:名/名/名,都不沾」,行 None。
    """
    # 阶段1:链全符,只差换手/今开
    best: tuple[int, str, list[str], dict | None] | None = None
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
        tags: list[str] = []
        vol2 = s.get("vol2")
        if vol2 is not None and (b2_turn is None
                                 or not (vol2[0] <= b2_turn < vol2[1])):
            fails.append(f"二板换手{_num(b2_turn)},口诀要求{_fmt_range(vol2)}")
            tags.append("二板开")
        v2wl = s.get("vol2_when_b1_low")
        if v2wl is not None and b1_open is not None and b1_open < contracts.CHAIN_FLAT_HI:
            if b2_turn is None or not (v2wl[0] <= b2_turn < v2wl[1]):
                fails.append(f"一板弱(<{contracts.CHAIN_FLAT_HI:g})时二板换手{_num(b2_turn)},"
                             f"口诀要求{_fmt_range(v2wl)}")
                tags.append("二板开")
        vol3 = s.get("vol3")
        if vol3 is not None and (b3_turn is None
                                 or not (vol3[0] <= b3_turn < vol3[1])):
            fails.append(f"三板换手{_num(b3_turn)},口诀要求{_fmt_range(vol3)}")
            tags.append("三板开")
        blk = s.get("block_foundation_chg")
        if blk is not None:
            blo, bhi, bcap = blk
            if (foundation_chg is not None and b3_open is not None
                    and blo <= foundation_chg < bhi and b3_open < bcap):
                fails.append(f"地基日涨{_pct(foundation_chg)}×三板开"
                             f"{_pct(b3_open)}温着(<{bcap:g})"
                             "=有人先手的半路残局")
                tags.append("地基日")
        bp10 = s.get("block_pre10")
        if bp10 is not None and pre10_pct is not None and pre10_pct >= bp10:
            fails.append(f"首板前10日已涨{_pct(pre10_pct)}(≥{bp10:g}):近端透支,"
                         "高位一字是末段冲刺")
            tags.append("首板前10日")
        fpok = s.get("foundation_pose_ok")
        if fpok and foundation_pose not in ("站线上", "骑线", None):
            if foundation_pose == "贴线":
                fails.append("地基K线贴着20日线悬着(离线不到2%)=死水没人做,"
                             "弱票要接有人做过的")
            else:
                fails.append("地基K线整根掉在20日线下头=没人救了,"
                             "弱票要接有人做过的")
            tags.append("地基姿态")
        banch = s.get("block_anchor")
        if banch is not None and anchor_pos is not None:
            (alo, ahi), adist, aover = banch
            if alo <= anchor_pos < ahi and anchor_dist is not None and anchor_dist <= adist:
                fails.append(f"地基日收盘距前期涨停高点{anchor_pos:+.1f}%"
                             f"(刚断{anchor_dist}日贴着不动)=断单板没能量")
                tags.append("距前涨停高")
            elif anchor_pos >= aover:
                fails.append(f"已超前期涨停高点{anchor_pos:+.1f}%=妖顶透支接最后一棒")
                tags.append("距前涨停高")
        lo, hi = s["today"]  # type: ignore[misc]
        if not (lo <= buy_open < hi):
            fails.append(f"今开{_pct(buy_open)},口诀要求{_fmt_range((lo, hi))}")
            tags.append("今开")
        if not fails:
            continue  # 全过=与 tag_point 的 miss 结论矛盾(不该发生),不展示
        score = -len(fails)
        if best is None or score > best[0]:
            desc = s.get("desc") or contracts.POINT_DESC.get(str(s["no"]), "")
            best = (score, f"形态接近口诀【{s['no']}·{s['name']}:{desc}】——"
                           f"这题{';'.join(fails[:2])},不能打", tags,
                    _cheat_row(str(s["no"]), str(s.get("sub") or "")))
    if best is not None:
        return best[1], True, best[2], best[3]
    # 阶段2:链全不符——报链形 + 本组(阴阳分清)能对照的口诀清单(v4.4多分支共享名,去重)
    names = list(dict.fromkeys(
        str(s["name"]) for s in contracts.SCHEMES if group4 in s["group4"]))
    yang_label = "阳" if group4.endswith("阳") else "阴"
    pos_label = "二接三" if group4.startswith("二接三") else "三接四"
    chain_desc = f"一板开{_pct(b1_open)} × 二板开{_pct(b2_open)}"
    chain_tags = ["一板开", "二板开"] + (["三板开"] if pos_label == "三接四" else [])
    if pos_label == "三接四":
        chain_desc += f" × 三板开{_pct(b3_open)}"
    return (f"链形({chain_desc})不在任何口诀区间——这题是{yang_label}地基的{pos_label},"
            f"能对照的口诀:{'/'.join(names)},形态都不沾,不用买"), False, chain_tags, None


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


def _cheat_row(no: str, sub: str) -> dict | None:
    """(编号,子项) → 速查表行(C2 一拆二后单分支口诀 sub 传空串)。"""
    return next((rr for rr in contracts.CHEAT_ROWS
                 if rr["no"] == no and rr.get("sub", "") == sub), None)


def _weak_cheat_row(no: str) -> dict | None:
    """弱市组速查表行(v7.1;K4 双分支共用一行,按编号取)。"""
    return next((rr for rr in contracts.WEAK_CHEAT_ROWS if rr["no"] == no), None)


def _nearest_weak_line(group4: str, b1_open, b2_open, b3_open,
                       b1_turn, b2_turn, b3_turn, buy_open: float,
                       foundation_chg=None, prev_wave60=None,
                       dist_h60=None) -> tuple[str, bool, list[str], dict | None]:
    """弱市组 miss 题的「为什么不买」(v7.1,镜像 _nearest_scheme_line 两阶段;
    腿语义=WEAK_SCHEMES:vol3/b1_turn_min/foundation_chg_max/prev_wave_max/
    dist_h60_min/vol3_lt_vol2)。返回 (文案, 是否形态接近, fail格子标签, 弱市速查表行):
    1. 链三腿全符只差条件 → 「形态接近弱市口诀【K5·贴零强开:…】——这题xx,不能打」;
    2. 链全不符 → 链形+本组能对照的弱市口诀清单,行 None。"""
    best: tuple[int, str, list[str], dict | None] | None = None
    for s in contracts.WEAK_SCHEMES:
        if group4 not in s["group4"]:
            continue
        chain_miss = False
        for key, val in (("b1", b1_open), ("b2", b2_open), ("b3", b3_open)):
            rng = s.get(key)
            if rng is None:
                continue
            if val is None or not (rng[0] <= val < rng[1]):
                chain_miss = True
                break
        if chain_miss:
            continue
        fails: list[str] = []
        tags: list[str] = []
        vol3 = s.get("vol3")
        if vol3 is not None and (b3_turn is None
                                 or not (vol3[0] <= b3_turn < vol3[1])):
            fails.append(f"三板换手{_num(b3_turn)},口诀要求{_fmt_range(vol3)}")
            tags.append("三板开")
        tmin = s.get("b1_turn_min")
        if tmin is not None and (b1_turn is None or b1_turn < tmin):
            fails.append(f"一板换手{_num(b1_turn)}<{tmin:g}=一字缩量链,"
                         f"要放量实体板(换手≥{tmin:g})")
            tags.append("一板换手")
        fmax = s.get("foundation_chg_max")
        if fmax is not None and (foundation_chg is None or foundation_chg > fmax):
            fails.append(f"地基日涨{_pct(foundation_chg)}(>{fmax:g}%)"
                         "=有人先手半路拉过,起板不干净")
            tags.append("地基日")
        wmax = s.get("prev_wave_max")
        if wmax is not None and (prev_wave60 is None or prev_wave60 > wmax):
            fails.append(f"前波60日最高{prev_wave60}板"
                         "(要=0:没炒过的低位票首波最真,来过波的是二波残局)")
            tags.append("前波60日")
        dmin = s.get("dist_h60_min")
        if dmin is not None and (dist_h60 is None or dist_h60 < dmin):
            fails.append(f"距60日新高{_pct(dist_h60)}(<{dmin:g}=没贴顶,套牢盘没消化)")
            tags.append("距新高")
        if s.get("vol3_lt_vol2") and (b3_turn is None or b2_turn is None
                                      or b3_turn >= b2_turn):
            fails.append(f"三板换手{_num(b3_turn)}≥二板{_num(b2_turn)}"
                         "=放量没承接(要缩量承接:三换<二换)")
            tags.append("三板开")
        lo, hi = s["today"]  # type: ignore[misc]
        if not (lo <= buy_open < hi):
            fails.append(f"今开{_pct(buy_open)},口诀要求{_fmt_range((lo, hi))}")
            tags.append("今开")
        if not fails:
            continue  # 全过=与 tag_weak 的 miss 结论矛盾(不该发生),不展示
        score = -len(fails)
        if best is None or score > best[0]:
            desc = str(s.get("desc") or "")
            best = (score, f"形态接近弱市口诀【{s['no']}·{s['name']}:{desc}】——"
                           f"这题{';'.join(fails[:2])},不能打", tags,
                    _weak_cheat_row(str(s["no"])))
    if best is not None:
        return best[1], True, best[2], best[3]
    names = list(dict.fromkeys(
        str(s["name"]) for s in contracts.WEAK_SCHEMES if group4 in s["group4"]))
    yang_label = "阳" if group4.endswith("阳") else "阴"
    pos_label = "二接三" if group4.startswith("二接三") else "三接四"
    chain_desc = f"一板开{_pct(b1_open)} × 二板开{_pct(b2_open)}"
    chain_tags = ["一板开", "二板开"] + (["三板开"] if pos_label == "三接四" else [])
    if pos_label == "三接四":
        chain_desc += f" × 三板开{_pct(b3_open)}"
    return (f"链形({chain_desc})不在任何弱市口诀区间——这题是{yang_label}地基的{pos_label},"
            f"能对照的弱市口诀:{'/'.join(names)},形态都不沾,不用买", False, chain_tags, None)


# 题面格子标签 → 速查表列键(主人2026-10-05「错误的口诀也给出表格+错误列标红」):
# 换手并进对应板位列文案(b2/b3),地基日各腿(姿态/锚点/前10日)都归「地基日」列;
# 首板前20日=半山腰背景毒,表格无对应列,丢弃;
# v7.1 弱市组腿:一板换手归一板列,前波60日/距新高归「地基日」列
_FIELD_TO_COL = {"阴阳": "yang", "一板开": "b1", "二板开": "b2", "三板开": "b3",
                 "今开": "today", "地基日": "ground", "地基姿态": "ground",
                 "距前涨停高": "ground", "首板前10日": "ground",
                 "一板换手": "b1", "前波60日": "ground", "距新高": "ground"}


def _row_fails(fail_fields: list[str]) -> list[str]:
    return list(dict.fromkeys(
        _FIELD_TO_COL[f] for f in fail_fields if f in _FIELD_TO_COL))


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
                      trap_total: int | None = None,
                      rng=None) -> list[tuple[str, str]]:
    """综合挑战卷抽题(纯函数,可注入种子复现)。

    rows = 题库轻量投影 [{decision_date, vt_symbol, point, trap_kind}]
    (point=标量列,trap_kind 从 payload 抽取,命中题为 None)。
    规则(主人定 2026-09-29):好票=七条口诀每条随机 per_point 道(无上限,
    固定2即保证每套覆盖全部口诀);差票=MIX_TRAP_KINDS 均分 trap_total,
    某类不够由后面的类补。trap_total 缺省=每卷在 [MIX_TRAP_MIN, MIX_TRAP_MAX]
    随机(14好×2~2.5=28~35差,总量42~49题)。
    返回 [(decision_date, vt_symbol)]——洗牌在 service 层拉全量后统一做。"""
    import random
    rnd = random.Random(rng)
    if trap_total is None:
        trap_total = rnd.randint(MIX_TRAP_MIN, MIX_TRAP_MAX)
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
    quota, extra = divmod(trap_total, len(MIX_TRAP_KINDS))
    deficit = 0
    for i, kind in enumerate(MIX_TRAP_KINDS):
        want = quota + (1 if i < extra else 0) + deficit
        got = rnd.sample(by_trap[kind], min(want, len(by_trap[kind])))
        picked.extend(got)
        deficit = want - len(got)
    return picked
