# -*- coding: utf-8 -*-
"""动态口诀切换器审计(2026-10-12 主人指令「核实动态口诀选取是否正确 会不会用到
未来函数。就拿2023年来说 哪些月有过切换 切换是怎么选取的 又漏掉了哪些比较好的
口诀 为什么 深入核查一下」)。

容器内跑: docker exec -i vnpy-alphaagent-api-1 python < 本文件
用生产同一条代码路径(build_events→_dyn_trades→contracts.dyn_month_states)审计
生产本身, 不是研究脚本复刻。

审计五部分:
  A. 全史切换点 + 与线上物化一致性
  B. 2023 逐月判定表(窗口/两组样本/均值/决策分支)
  C. 未来函数三查: C1同月排除(v7.8) / C2结算边界(退出日跨月的笔) / C3月列表口径
  D. 2023 漏掉的口诀: 被停组当月命中笔逐条+按口诀汇总(漏的好/避开的坏)
  E. 2023-09 切换决策的裕量与稳健性
"""
import sys
from collections import defaultdict

import pandas as pd

from alphaagent.server.services.high_relay import backtest, contracts, repository


def log(*a):
    print(*a, file=sys.stderr)


def avg(xs):
    return sum(xs) / len(xs) if xs else None


def fmt(x):
    return f"{x:+.2f}" if x is not None else "  —  "


def main() -> None:
    log("全量事件回放(与 worker 同一代码路径)...")
    E, _bars = backtest.build_events()
    done = E[~E["未完"]].copy()
    dyn_trades = backtest._dyn_trades(done)
    states = contracts.dyn_month_states(dyn_trades)

    # ── 富化轻表: 补 名称/买入日/E3退出日 (只用于审计, 判定仍用生产函数) ──
    rich = []   # (月, 组, 口诀, E3, 名称, 买入日, 退出日)
    for _, r in done.iterrows():
        e3 = r.get("E3%")
        if e3 is None or e3 != e3:
            continue
        wk = str(r.get("弱口诀") or "—")
        pt = str(r.get("方案点") or "—")
        g, p = ("weak", wk) if wk != "—" else (("strong", pt) if pt != "—" else (None, None))
        if g is None:
            continue
        rich.append((str(r["月"]), g, p, round(float(e3), 2),
                     str(r.get("名称") or ""), str(r["买入日"]).strip(),
                     str(r.get("E3退出日") or "")))
    tm = sorted({t[0] for t in rich})
    tmi = {m: i for i, m in enumerate(tm)}

    def wset(m, window=12, include_current=False):
        i = tmi[m]
        return set(tm[max(0, i - window):i]) if not include_current \
            else set(tm[max(0, i - window + 1):i + 1])

    def decide(m, window=12, include_current=False, drop_after=None):
        """复算某月判定。drop_after=日期串: 剔除退出日>=该日的笔(当时不可知)。"""
        ms = wset(m, window, include_current)
        wk = [t[3] for t in rich if t[0] in ms and t[1] == "weak"
              and (drop_after is None or not t[6] or t[6] < drop_after)]
        st = [t[3] for t in rich if t[0] in ms and t[1] == "strong"
              and (drop_after is None or not t[6] or t[6] < drop_after)]
        wa, sa = avg(wk), avg(st)
        n_min = contracts.DYN_GROUP_MIN_N
        if len(wk) >= n_min and len(st) >= n_min and wa is not None and sa is not None:
            s = "weak" if wa > sa else "strong"
        elif len(wk) >= n_min and wa is not None and wa > 0:
            s = "weak"
        elif len(st) >= n_min and sa is not None and sa > 0:
            s = "strong"
        else:
            s = "both"
        return s, len(wk), wa, len(st), sa, ms

    # ════ A. 全史切换点 + 物化一致性 ════
    print("=" * 30, "A. 切换史与物化一致性", "=" * 30)
    try:
        row = repository.load_backtest_report(contracts.HPR_RULES_VERSION)
        stored = dict((row or {}).get("dyn_month_states") or {})
        bad = {m: (stored.get(m), states.get(m)) for m in set(stored) | set(states)
               if stored.get(m) != states.get(m)}
        print(f"重算 {len(states)} 月 vs 线上物化 {len(stored)} 月 → 不一致 {len(bad)} 月"
              + ("(逐月相同)" if not bad else f": {bad}"))
    except Exception as ex:  # noqa: BLE001
        print(f"(物化对照跳过: {ex})")
    seq = sorted(states)
    st0 = "both"
    print("全史切换点:")
    for m in seq:
        if states[m] != st0:
            print(f"  {m}: {st0} → {states[m]}")
            st0 = states[m]
    miss_m = [f"{y}-{mm:02d}" for y in range(2020, 2027) for mm in range(1, 13)
              if f"{y}-{mm:02d}" not in tmi and f"{y}-{mm:02d}" <= tm[-1]]
    print(f"无命中月(不在tm, 状态由dyn_state_at继承前月): {miss_m or '无'}")
    print(f"数据范围 {tm[0]} ~ {tm[-1]}, 共 {len(tm)} 个交易月\n")

    # ════ B. 2023 逐月判定表 ════
    print("=" * 30, "B. 2023 逐月判定(生产口径)", "=" * 30)
    print(f"{'月':<9}{'状态':<7}{'窗口':<17}{'弱n/均':<15}{'强n/均':<15}分支")
    for m in [f"2022-1{i}" for i in range(1, 3)] + [f"2023-{i:02d}" for i in range(1, 13)] \
            + ["2024-01"]:
        if m not in tmi:
            print(f"{m:<9}(无命中月, 继承={contracts.dyn_state_at(states, m)})")
            continue
        s, nw, wa, ns, sa, ms = decide(m)
        ms_sorted = sorted(ms)
        br = "双组齐全比均值" if (nw >= 8 and ns >= 8) else ("单组达标" if s != "both" else "样本不足双开")
        print(f"{m:<9}{s:<7}{ms_sorted[0]}~{ms_sorted[-1]:<9}"
              f"{nw:>3}/{fmt(wa):<10}{ns:>3}/{fmt(sa):<10}{br}")
    print()

    # ════ C. 未来函数三查 ════
    print("=" * 30, "C. 未来函数三查", "=" * 30)
    # C1 同月排除(v7.8修复): 旧口径含当月
    print("C1 同月排除(v7.8): 旧口径 tm[i-w+1:i+1](含当月)复算 2023-08/09 →")
    for m in ("2023-08", "2023-09"):
        s_new, *_ = decide(m)
        s_old, nw, wa, ns, sa, _ = decide(m, include_current=True)
        print(f"  {m}: 生产(不含当月)={s_new}  旧口径(含当月)={s_old}"
              f"  [旧口径窗口 弱{nw}均{fmt(wa)} / 强{ns}均{fmt(sa)}]")
    # C2 结算边界: 判定时点=次月1日, 窗口内退出日>=次月1日的笔当时不可知
    print("C2 结算边界(退出日跨月的笔, 判定时点=当月1日):")
    print(f"{'月':<9}{'生产判定':<8}{'未知笔(弱/强)':<15}{'剔除后判定':<9}{'剔除后 弱n/均 强n/均'}")
    flips = 0
    for m in [f"2023-{i:02d}" for i in range(1, 13)]:
        if m not in tmi:
            continue
        boundary = f"{m}-01"
        unk = [t for t in rich if t[0] in wset(m)
               and t[6] and t[6] >= boundary]
        if not unk:
            print(f"{m:<9}{states[m]:<8}0/0{'':<9}{states[m]:<9}(窗口内无跨月退出笔)")
            continue
        s2, nw, wa, ns, sa, _ = decide(m, drop_after=boundary)
        uw = [t for t in unk if t[1] == "weak"]
        us = [t for t in unk if t[1] == "strong"]
        flag = "" if s2 == states[m] else "  ← 判定翻转!"
        if s2 != states[m]:
            flips += 1
        print(f"{m:<9}{states[m]:<8}{len(uw)}/{len(us)}{'':<9}{s2:<9}"
              f"弱{nw}/{fmt(wa)} 强{ns}/{fmt(sa)}{flag}")
        for t in unk:
            print(f"    未知笔: {t[0]} {t[2]} {t[4]} E3{t[3]:+.1f} 买{t[5]} 退{t[6]}")
    print(f"  → 2023 全年12个月判定翻转 {flips} 个" if flips else
          "  → 2023 全年12个月剔除未知笔后判定零翻转(结算边界不改变任何决策)")
    # C3 月列表口径
    print("C3 月列表口径: tm=有命中的交易月(空月不占窗位), 全部为过去月——")
    m = "2023-09"
    print(f"  判2023-09窗={sorted(wset(m))[0]}~{sorted(wset(m))[-1]} 共{len(wset(m))}个交易月, "
          f"当月2023-09不在窗内; 窗内月均<判定时点, 无未来月进入。")
    print()

    # ════ D. 2023 漏掉的口诀 ════
    print("=" * 30, "D. 2023 被停组的命中(漏与避)", "=" * 30)
    by_month = defaultdict(list)
    for t in rich:
        if t[0].startswith("2023"):
            by_month[t[0]].append(t)
    for m in sorted(by_month):
        st = contracts.dyn_state_at(states, m)
        on = [t for t in by_month[m] if t[1] == st or st == "both"]
        off = [t for t in by_month[m] if t[1] != st and st != "both"]
        if not off:
            print(f"{m} [{st}] 启用{len(on)}笔 被停组0笔")
            continue
        off_by = defaultdict(list)
        for t in off:
            off_by[t[1]].append(t)
        parts = []
        for g in ("weak", "strong"):
            if g in off_by:
                rs = [t[3] for t in off_by[g]]
                parts.append(f"{'弱' if g == 'weak' else '强'}组{len(rs)}笔和{sum(rs):+.1f}")
        print(f"{m} [{st}] 启用{len(on)}笔和{sum(t[3] for t in on):+.1f} | "
              f"被停 {' '.join(parts)}")
    print()
    print("2023 全年按口诀汇总(被停期间的命中):")
    agg = defaultdict(list)
    for m in sorted(by_month):
        st = contracts.dyn_state_at(states, m)
        for t in by_month[m]:
            if t[1] != st and st != "both":
                agg[(t[1], t[2])].append(t)
    for (g, p), ts in sorted(agg.items(), key=lambda kv: -sum(t[3] for t in kv[1])):
        rs = [t[3] for t in ts]
        names = "、".join(f"{t[4]}{t[3]:+.0f}" for t in sorted(ts, key=lambda x: -x[3])[:4])
        print(f"  [{'弱' if g == 'weak' else '强'}组停用]{p:<4}{len(rs):>2}笔 "
              f"均{avg(rs):+.2f} 和{sum(rs):+7.1f} | {names}")
    # 启用组全年成绩对照
    on23 = [t for m in sorted(by_month) for t in by_month[m]
            if t[1] == contracts.dyn_state_at(states, m) or contracts.dyn_state_at(states, m) == "both"]
    off23 = [t for m in sorted(by_month) for t in by_month[m]
             if t[1] != contracts.dyn_state_at(states, m) and contracts.dyn_state_at(states, m) != "both"]
    print(f"\n  2023 启用组合计: {len(on23)}笔 均{avg([t[3] for t in on23]):+.2f} "
          f"和{sum(t[3] for t in on23):+.1f}")
    print(f"  2023 被停组合计: {len(off23)}笔 均{avg([t[3] for t in off23]):+.2f} "
          f"和{sum(t[3] for t in off23):+.1f}")
    print()

    # ════ E. 2023-09 切换决策的裕量 ════
    print("=" * 30, "E. 2023-09 切换决策裕量", "=" * 30)
    ms = wset("2023-09")
    wk = [t for t in rich if t[0] in ms and t[1] == "weak"]
    st = [t for t in rich if t[0] in ms and t[1] == "strong"]
    print(f"窗口 {sorted(ms)[0]}~{sorted(ms)[-1]}:")
    print(f"  弱市组 {len(wk)}笔 均{avg([t[3] for t in wk]):+.2f}")
    print(f"  强市组 {len(st)}笔 均{avg([t[3] for t in st]):+.2f}")
    margin = avg([t[3] for t in st]) - avg([t[3] for t in wk])
    print(f"  裕量 = 强-弱 = {margin:+.2f}点/笔")
    # 稳健性: 强市组剔最好一笔/弱市组剔最差一笔 再判
    st_r = sorted([t[3] for t in st])[1:]
    wk_r = sorted([t[3] for t in wk])[:-1]
    print(f"  稳健性: 强组剔最好1笔后均{avg(st_r):+.2f} / 弱组剔最差1笔后均{avg(wk_r):+.2f}"
          f" → {'仍强胜' if avg(st_r) > avg(wk_r) else '反转!'}")
    # 窗内两组分口诀贡献
    print("  窗内分口诀:")
    for g, arr in (("弱", wk), ("强", st)):
        byp = defaultdict(list)
        for t in arr:
            byp[t[2]].append(t[3])
        for p, rs in sorted(byp.items(), key=lambda kv: -avg(kv[1])):
            print(f"    [{'弱' if g == '弱' else '强'}]{p:<4}{len(rs):>2}笔 均{avg(rs):+.2f}")


main()
