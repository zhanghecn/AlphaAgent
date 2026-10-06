"""高位接力打板 API 门面:实时推荐 / 回测报告 / 交割单 / 规则契约。"""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from alphaagent.server.services.high_relay import (
    backtest as backtest_mod,
    contracts,
    quiz as quiz_mod,
    repository,
)

logger = logging.getLogger(__name__)
SHANGHAI = ZoneInfo("Asia/Shanghai")
_rebuild_lock = threading.Lock()
_rebuild_running = False


class BacktestAlreadyRunningError(RuntimeError):
    """高位接力回测重算已有任务在执行。"""


# ── 实时推荐 ──

def get_live(trade_date: date | None = None) -> dict[str, object]:
    """今日池 × 触发状态;指定日期可回看。盘前/盘后均可读(盘后为定版)。

    收盘后(stage=closed)若盘后主链已算出更新的池(次日盘前池),自动切备战视图
    ——主人 2026-09-30 拍板:收盘就能看到下一天的结果,不等 0 点日期翻篇;
    盘中不切(操作今日池);今日终态/持仓回看走日期下拉。"""
    now = datetime.now(SHANGHAI)
    target = trade_date or now.date()
    pool = repository.load_pool(target)
    stale = False
    stage = _session_stage(now)
    if trade_date is None:
        latest = repository.latest_pool_date()
        if latest is not None and latest > target and stage == "closed":
            pool = repository.load_pool(latest)
            target = latest
        elif not pool and latest is not None:
            pool = repository.load_pool(latest)
            target = latest
            stale = True
    signals = repository.load_signal_map(target)
    entries = []
    pool_vts = {str(e["vt_symbol"]) for e in pool}
    for entry in pool:
        entries.append(_live_row(entry, signals.get(str(entry["vt_symbol"]))))
    for vt, sig in signals.items():
        if vt not in pool_vts:
            entries.append(_live_row(None, sig))
    entries.sort(key=_live_sort_key)

    # 动态口诀组(v7.1):按当前启用组标注出手资格——强市组命中/弱市组命中,
    # 只有启用组的命中才是「出手」;另一组的候选保留展示但灰显(未启用)。
    dyn = current_dyn_group()
    grp = str(dyn["group"])
    active_count = 0
    for e in entries:
        strong_hit = bool(e.get("actionable"))
        weak_hit = str(e.get("weak_point") or "—") != "—"
        e["strong_active"] = strong_hit and grp in ("strong", "both")
        e["weak_active"] = weak_hit and grp in ("weak", "both")
        e["active"] = bool(e["strong_active"] or e["weak_active"])
        if e["active"]:
            active_count += 1
            # 展示口径:出手票的点位徽章优先弱市组(双命中归 K 系,与 dyn_trades 一致)
            if e["weak_active"]:
                e["point"] = e.get("weak_point")
                e["level"] = "A"
        elif strong_hit and not e["strong_active"]:
            e["paused_label"] = "强市组未启用"
        elif weak_hit:
            e["paused_label"] = "弱市组未启用"

    status_counts: dict[str, int] = {}
    group_counts: dict[str, int] = {}
    point_counts: dict[str, int] = {}
    weak_point_counts: dict[str, int] = {}
    actionable_count = 0
    for e in entries:
        sk = str(e["status"])
        status_counts[sk] = status_counts.get(sk, 0) + 1
    for e in pool:
        gk = str(e["group4"])
        group_counts[gk] = group_counts.get(gk, 0) + 1
        pk = str(e.get("point") or "—")
        if pk != "—":
            point_counts[pk] = point_counts.get(pk, 0) + 1
        wk = str(e.get("weak_point") or "—")
        if wk != "—":
            weak_point_counts[wk] = weak_point_counts.get(wk, 0) + 1
        actionable_count += int(bool(e.get("actionable")))
    mkt_lim_tm1 = next((e.get("mkt_lim_tm1") for e in pool
                        if e.get("mkt_lim_tm1") is not None), None)
    last_scan = repository.latest_scan_run(target)
    return {
        "status": "ok",
        "trade_date": target.isoformat(),
        "stale": stale,
        "session_stage": stage,
        "rules_version": contracts.HPR_RULES_VERSION,
        "dyn_group": {
            "group": grp,
            "asof": dyn.get("asof"),
            "label": {"weak": "弱市组", "strong": "强市组", "both": "双开(样本不足)"}[grp],
        },
        "counts": {
            "pool": len(pool),
            "actionable": actionable_count,
            "active": active_count,
            "signals": len(signals),
            "by_group": group_counts,
            "by_point": point_counts,
            "by_weak_point": weak_point_counts,
            "by_status": status_counts,
        },
        "mkt_lim_tm1": mkt_lim_tm1,
        "group4_labels": contracts.GROUP4_LABELS,
        "point_labels": contracts.POINT_LABELS,
        "point_levels": contracts.POINT_LEVELS,
        "last_scan": {
            "finished_at": _iso(last_scan.get("finished_at")),
            "status": last_scan.get("status"),
            "message": last_scan.get("message"),
        } if last_scan else None,
        "entries": entries,
    }


def get_live_dates() -> list[str]:
    return repository.list_pool_dates()


def _live_row(entry: dict[str, object] | None,
              sig: dict[str, object] | None) -> dict[str, object]:
    row: dict[str, object] = {}
    if entry is not None:
        row.update({
            "vt_symbol": entry["vt_symbol"], "name": entry.get("name"),
            "group4": entry.get("group4"),
            "n_board": entry.get("n_board"),
            "point": entry.get("point"),
            "level": entry.get("level"),
            "actionable": bool(entry.get("actionable")),
            "avoid_static": entry.get("avoid_static"),
            "auction_gate": entry.get("auction_gate"),
            "action_hint": entry.get("action_hint"),
            "today_window": _parse_gate(entry.get("auction_gate")),
            "weak_point": entry.get("weak_point"),
            "weak_label": entry.get("weak_label"),
            "weak_hint": entry.get("weak_hint"),
            "weak_windows": _parse_gate(entry.get("weak_gate")),
            "b3_turn": entry.get("b3_turn"),
            "prev_close": entry.get("prev_close"),
            "limit_price": entry.get("limit_price"),
            "foundation_yang": entry.get("foundation_yang"),
            "foundation_chg": entry.get("foundation_chg"),
            "dist_h60": entry.get("dist_h60"),
            "ma_state": entry.get("ma_state"),
            "dist_ma10": entry.get("dist_ma10"),
            "prior_height": entry.get("prior_height"),
            "prev_wave60": entry.get("prev_wave60"),
            "prev_wave120": entry.get("prev_wave120"),
            "chain": entry.get("chain"),
            "b1_open": entry.get("b1_open"),
            "b2_open": entry.get("b2_open"),
            "b1_turn": entry.get("b1_turn"),
            "b2_turn": entry.get("b2_turn"),
            "turn_grad": entry.get("turn_grad"),
        })
    if sig:
        row.update({
            "vt_symbol": sig["vt_symbol"],
            "group4": sig.get("group4") or row.get("group4"),
            "point": sig.get("point") or row.get("point"),
            "level": sig.get("level") or row.get("level"),
            "name": row.get("name") or sig.get("name"),
            "prev_close": row.get("prev_close") or sig.get("prev_close"),
            "limit_price": row.get("limit_price") or sig.get("limit_price"),
            "status": sig.get("status"),
            "auction_pct": sig.get("auction_pct"),
            "opened": sig.get("opened"),
            "touched_at": _iso(sig.get("touched_at")),
            "entry_price": sig.get("entry_price"),
            "entry_time": _iso(sig.get("entry_time")),
            "last_price": sig.get("last_price"),
            "change_pct": sig.get("change_pct"),
            "sealed": sig.get("sealed"),
            "streak_h": sig.get("streak_h"),
            "exit_date": _date_iso(sig.get("exit_date")),
            "exit_price": sig.get("exit_price"),
            "exit_reason": sig.get("exit_reason"),
            "ret_pct": sig.get("ret_pct"),
        })
    row.setdefault("status", "watching")
    row.setdefault("actionable", False)
    row.setdefault("point", "—")
    row.setdefault("level", "—")
    return row


def _parse_gate(gate: object) -> list[list[float]]:
    """auction_gate 多窗字符串(today_{lo}_{hi}[,...])解析成今开窗列表;
    无门→空列表(多分支/链重叠票有多个候选窗,与 action_hint 条件表对应)。"""
    if not gate:
        return []
    out: list[list[float]] = []
    for part in str(gate).split(","):
        seg = part.split("_")
        if len(seg) != 3 or seg[0] != "today":
            continue
        try:
            out.append([float(seg[1]), float(seg[2])])
        except ValueError:
            continue
    return out


def _live_sort_key(row: dict[str, object]) -> tuple:
    order = {"holding": 0, "entered": 0, "sealed_watch": 1, "watching": 2,
             "pending_exit": 3, "closed": 4, "late_touch": 5, "no_trigger": 5,
             "skipped_auction": 6, "skipped_gap": 7}
    point_order = {pk: i for i, pk in enumerate(contracts.POINT_KEYS)}
    return (0 if row.get("actionable") else 1,
            order.get(str(row.get("status")), 8),
            point_order.get(str(row.get("point")), 9),
            str(row.get("vt_symbol")))


def _session_stage(now: datetime) -> str:
    current = now.timetz().replace(tzinfo=None)
    if current < time(9, 25):
        return "preopen"
    if current < time(9, 30):
        return "auction"
    if current < time(9, 46):
        return "first_window"
    if current <= time(11, 30):
        return "morning"
    if current < time(13, 0):
        return "lunch"
    if current <= time(15, 0):
        return "afternoon"
    return "closed"


# ── 回测 ──

def get_backtest_report() -> dict[str, object] | None:
    return repository.load_backtest_report(contracts.HPR_RULES_VERSION)


def get_rebuild_status() -> dict[str, object]:
    run = repository.latest_rebuild_run()
    if run is None:
        return {"status": "idle", "rules_version": contracts.HPR_RULES_VERSION}
    return {
        "status": run.get("status"),
        "stage": run.get("stage"),
        "source": run.get("source"),
        "rules_version": run.get("rules_version"),
        "requested_at": _iso(run.get("requested_at")),
        "started_at": _iso(run.get("started_at")),
        "finished_at": _iso(run.get("finished_at")),
        "message": run.get("message"),
        "error": run.get("error"),
        "metrics": run.get("metrics") or {},
    }


def start_backtest_rebuild(source: str = "manual") -> dict[str, object]:
    """409 去重:已有 queued/running 任务则拒绝。"""
    global _rebuild_running
    with _rebuild_lock:
        if _rebuild_running:
            return {"already_running": True}
        _rebuild_running = True
    run_id = repository.create_rebuild_run(source, contracts.HPR_RULES_VERSION)
    thread = threading.Thread(
        target=_background_rebuild, args=(run_id,), daemon=True,
        name="hpr-backtest-rebuild",
    )
    thread.start()
    return {"run_id": run_id, "status": "queued"}


def run_backtest_sync(source: str = "scheduler") -> dict[str, object]:
    """调度链同步执行(内部也走重建轨道,供批次读取状态)。"""
    global _rebuild_running
    with _rebuild_lock:
        if _rebuild_running:
            raise BacktestAlreadyRunningError
        _rebuild_running = True
    run_id = repository.create_rebuild_run(source, contracts.HPR_RULES_VERSION)
    try:
        return _execute_rebuild(run_id)
    finally:
        with _rebuild_lock:
            _rebuild_running = False


def _background_rebuild(run_id: int) -> None:
    global _rebuild_running
    try:
        _execute_rebuild(run_id)
    finally:
        with _rebuild_lock:
            _rebuild_running = False


def _execute_rebuild(run_id: int) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    repository.update_rebuild_run(run_id, status="running", stage="全量回放", started_at=now)
    try:
        E, bars = backtest_mod.build_events()
        payload = backtest_mod.assemble_report(E, bars)
        repository.update_rebuild_run(run_id, status="running", stage="题库构建")
        # v7.3 题库注入同一份物化月状态(单一事实源:回测/交割单/koujue 共用)
        questions = quiz_mod.build_questions(
            E, bars, payload.get("dyn_month_states") or None)
    except Exception as exc:  # noqa: BLE001
        logger.warning("hpr backtest rebuild failed: %s", exc, exc_info=True)
        repository.update_rebuild_run(
            run_id, status="failed", stage="失败",
            finished_at=datetime.now(timezone.utc), error=f"{exc.__class__.__name__}: {exc}")
        raise
    repository.update_rebuild_run(run_id, status="running", stage="写库")
    repository.save_backtest_report(contracts.HPR_RULES_VERSION, payload)
    quiz_count = repository.save_quiz_questions(quiz_mod.quiz_rules_version(), questions)
    summary = payload.get("summary") or {}
    repository.update_rebuild_run(
        run_id, status="done", stage="完成",
        finished_at=datetime.now(timezone.utc),
        message="; ".join(f"{pk}: n={(summary.get(pk) or {}).get('n')}"
                          for pk in contracts.POINT_KEYS),
        metrics={"summary": summary,
                 "anchor_check": payload.get("anchor_check") or {},
                 "quiz": {"count": quiz_count}},
    )
    return payload


# ── 交割单 ──

def get_ledger(month: str | None = None) -> dict[str, object]:
    """回测模拟交割单(全历史物化;month=YYYY-MM 切片,默认最新月)。
    v7.3 起数据源=动态组口径(dyn_ledger_days:当月启用组才成交——2023-01~06
    八条命中按纪律不成交/2020 暖期双开两组都出手),旧物化兜底 ledger_days。"""
    payload = get_backtest_report()
    if payload is None:
        return {"status": "unavailable", "ledger_days": [], "months": []}
    days = list(payload.get("dyn_ledger_days") or payload.get("ledger_days") or [])
    months = _month_summaries(days)
    selected = month or (months[0]["month"] if months else None)
    if selected:
        days = [d for d in days if str(d.get("trade_date") or "").startswith(selected)]
    return {
        "status": "ok",
        "is_backtest": True,
        "coverage": payload.get("coverage"),
        "caliber": payload.get("caliber"),
        "month": selected,
        "months": months,
        "ledger_days": days,
    }


def _month_summaries(days: list[dict[str, object]]) -> list[dict[str, object]]:
    """按月汇总交割单(笔数/胜率/平均每笔/累计等权),最新在前。
    收益汇总=可执行口径(v6.1):同票持仓重叠笔(未加仓)不计入,笔数含全部展示行。"""
    acc: dict[str, dict[str, float]] = {}
    for day in days:
        key = str(day.get("trade_date") or "")[:7]
        if not key:
            continue
        bucket = acc.setdefault(key, {"count": 0, "win": 0, "sum_ret": 0.0, "exe": 0})
        for t in day.get("trades") or []:
            ret = t.get("ret_pct")
            if ret is None:
                continue
            bucket["count"] += 1
            if t.get("overlap"):
                continue  # 同票持仓中未成交,不进收益汇总
            bucket["exe"] += 1
            bucket["sum_ret"] += float(ret)
            if float(ret) > 0:
                bucket["win"] += 1
    return [
        {"month": m, "count": int(v["count"]),
         "win_rate": round(v["win"] / v["exe"] * 100, 1) if v["exe"] else None,
         "avg_ret_pct": round(v["sum_ret"] / v["exe"], 2) if v["exe"] else None,
         "total_ret_pct": round(v["sum_ret"], 2)}
        for m, v in sorted(acc.items(), reverse=True)
    ]


def get_forward_ledger(trade_date: date) -> dict[str, object]:
    """前推交割单(产品上线后的实时模拟成交)。"""
    entered = repository.load_entered_signals(trade_date)
    for row in entered:
        row["point_label"] = contracts.POINT_LABELS.get(str(row.get("point")), "")
    return {"status": "ok", "is_backtest": False,
            "trade_date": trade_date.isoformat(), "trades": entered}


# ── 答题训练题库 ──

def get_quiz_overview() -> dict[str, object]:
    """题库年→月分布(前端年份选择/月份格子);版本不符或空表 → unavailable。"""
    data = repository.load_quiz_overview()
    months = data.get("months") or []
    versions = data.get("rules_versions") or []
    expect = quiz_mod.quiz_rules_version()
    if not months or versions != [expect]:
        return {"status": "unavailable", "rules_version": expect,
                "stored_versions": versions}
    years: dict[str, list[dict[str, object]]] = {}
    year_states: dict[str, set[str]] = {}   # v7.3 年→出现过的月组状态(切组年标渐变)
    total = 0
    for row in months:
        y = str(row["year"])
        years.setdefault(y, []).append({
            "month": str(row["month"]),
            "total": int(row["total"]),
            "buy_count": int(row["buy_count"]),
            "reject_count": int(row["reject_count"]),
        })
        if row.get("dyn_state"):
            year_states.setdefault(y, set()).add(str(row["dyn_state"]))
        total += int(row["total"])
    return {
        "status": "ok",
        "rules_version": expect,
        "total": total,
        "years": [{"year": y, "months": ms,
                   "dyn_states": sorted(year_states.get(y, set()))}
                  for y, ms in sorted(years.items())],
    }


def get_quiz_questions(month: str) -> dict[str, object]:
    """该月全部题目(含K线窗口/答案/讲解,一次下发;前端本地判分)。"""
    questions = repository.load_quiz_questions(month)
    status = repository.quiz_bank_status()
    expect = quiz_mod.quiz_rules_version()
    if status.get("rules_versions") != [expect]:
        return {"status": "unavailable", "rules_version": expect}
    return {"status": "ok", "month": month, "rules_version": expect,
            "count": len(questions), "questions": questions}


def get_quiz_mixed(year: str | None = None,
                   era: str | None = None) -> dict[str, object]:
    """综合挑战卷(主人定 2026-09-28):六条口诀每条随机≥2道好票 + 陷阱差票
    (阴阳反串/形态接近/毒段三等分,差:好=1:1~3:1),每次调用重抽、全卷乱序。
    year 非空=只在该年抽(单年池不足的口诀有多少抽多少,不硬凑);
    era 优先于 year(v7.2 时代抽题):weak=2020-22 弱市组段,strong=2023 起强市段。"""
    import random
    expect = quiz_mod.quiz_rules_version()
    status = repository.quiz_bank_status()
    if status.get("rules_versions") != [expect]:
        return {"status": "unavailable", "rules_version": expect}
    projection = repository.load_quiz_mix_projection(year, era)
    keys = quiz_mod.mix_question_keys(projection)
    questions = repository.load_quiz_questions_by_keys(keys)
    random.shuffle(questions)
    return {"status": "ok", "rules_version": expect, "year": year, "era": era,
            "count": len(questions), "questions": questions}


# ── 规则契约 ──

_dyn_group_cache: dict[str, object] = {"ts": 0.0, "data": None}
_DYN_GROUP_TTL = 3600.0  # 进程内缓存(盘中扫描每分钟读,不能每跳打库)


def _load_dyn_states() -> tuple[dict[str, str], str | None]:
    """读最新物化的月→组状态(v7.3 单一事实源=payload["dyn_month_states"],
    assemble_report 用 contracts.dyn_month_states 统一构建);无物化=空。
    返回 (states, asof月)。"""
    try:
        row = repository.load_backtest_report(contracts.HPR_RULES_VERSION)
    except Exception:  # noqa: BLE001
        return {}, None
    states = dict((row or {}).get("dyn_month_states") or {})
    months = sorted(states)
    return states, (months[-1] if months else None)


def current_dyn_group() -> dict[str, object]:
    """当前启用口诀组(v7.1 实时推荐/盘中扫描联动):物化月状态取最后一月;
    无物化/无数据 → both(双开兜底=两组都可出手,行为同机制上线前)。
    缓存 1h(组只在月末切换,读旧一档无风险)。"""
    import time as _time
    now = _time.time()
    cached = _dyn_group_cache["data"]
    if cached is not None and now - float(_dyn_group_cache["ts"]) < _DYN_GROUP_TTL:
        return dict(cached)  # type: ignore[arg-type]
    states, asof = _load_dyn_states()
    group = str(states[asof]) if asof and asof in states else "both"
    out = {"group": group, "asof": asof}
    _dyn_group_cache.update(ts=now, data=out)
    return dict(out)


def get_current_koujue() -> dict[str, object]:
    """获取最新口诀(v7.0 动态口诀组:近一年哪组口诀赚得多就用哪组)。

    从最新物化报告的 dyn_trades 逐笔表滚动汇总近 DYN_GROUP_WINDOW 个月两组成绩,
    数字全部动态计算不写死;当前组=近窗每笔平均E3高的一组(样本不足时双开)。
    同时下发当前组的速查表行(静态研究锚定+近12月动态成绩双列)与切换历史。"""
    row = repository.load_backtest_report(contracts.HPR_RULES_VERSION)
    trades = list((row or {}).get("dyn_trades") or [])
    # v7.3 单一事实源:月状态读物化 dyn_month_states(与题库/回测/交割单同一份)
    states = dict((row or {}).get("dyn_month_states") or {})
    if not trades or not states:
        return {"status": "unavailable", "rules_version": contracts.HPR_RULES_VERSION,
                "reason": "回测物化未生成动态口诀组数据,请等待 rebuild 完成"}
    win = contracts.DYN_GROUP_WINDOW
    months = sorted({str(t["m"]) for t in trades})
    recent = set(months[-win:])

    def agg(g: str, ms: set[str] | None = None) -> dict[str, object]:
        scope = recent if ms is None else ms
        rs = [float(t["r"]) for t in trades if str(t["m"]) in scope and t["g"] == g]
        return {"n": len(rs),
                "avg": round(sum(rs) / len(rs), 2) if rs else None,
                "win": round(sum(1 for x in rs if x > 0) / len(rs), 3) if rs else None}

    wk, st = agg("weak"), agg("strong")
    # v7.3 当前组=物化月状态最后一月(单一事实源,与题库/交割单同口径)
    current = str(states.get(months[-1], "both"))

    # 组内口诀逐条近12月动态成绩
    def point_dyn(prefix_keys: list[str]) -> dict[str, dict[str, object]]:
        out: dict[str, dict[str, object]] = {}
        for no in prefix_keys:
            rs = [float(t["r"]) for t in trades
                  if str(t["m"]) in recent and t["p"] == no]
            out[no] = {"n": len(rs),
                       "avg": round(sum(rs) / len(rs), 2) if rs else None,
                       "win": round(sum(1 for x in rs if x > 0) / len(rs), 3) if rs else None}
        return out

    def rows_with_dyn(rows: list[dict[str, str]]) -> list[dict[str, object]]:
        dyn = point_dyn([str(r["no"]) for r in rows])
        out = []
        seen: set[str] = set()
        for r in rows:
            no = str(r["no"])
            # 多分支口诀(A1/B1/B2/C3)按编号汇总,动态数只填首行——分支行重复显示会误读为双倍笔数
            if no in seen:
                out.append({**r, "dyn_stat": ""})
                continue
            seen.add(no)
            d = dyn.get(no) or {"n": 0}
            ds = (f"近{win}月 {d['n']}笔"
                  + (f"·胜{round(d['win'] * 100)}%·均{d['avg']:+.1f}" if d["n"] else "无出手"))
            out.append({**r, "dyn_stat": ds})
        return out

    weak_rows = rows_with_dyn(contracts.WEAK_CHEAT_ROWS)
    strong_rows = rows_with_dyn(contracts.CHEAT_ROWS)

    # 切换历史(v7.3):直接读物化月状态序列的变化点——每年真实判定口径
    # (从 2020-01 起步数据滚动:暖机期 both→2020-07 weak→2023-07 strong)
    history: list[dict[str, str]] = []
    state = "both"
    for m in sorted(states):
        s = str(states[m])
        if s != state:
            history.append({"month": m, "from": state, "to": s})
            state = s

    return {
        "status": "ok",
        "rules_version": contracts.HPR_RULES_VERSION,
        "window_months": win,
        "asof": months[-1],
        "current_group": current,
        "groups": {"weak": {**wk, "label": "弱市组", "rows": weak_rows},
                   "strong": {**st, "label": "强市组", "rows": strong_rows}},
        "current_rows": weak_rows if current == "weak" else
                        strong_rows if current == "strong" else weak_rows + strong_rows,
        "switch_history": history,
        "caliber": ("近12个月两组各自命中的每笔平均收益(E3,产品卖出纪律),"
                    "高的一组整组启用;月末滚动,样本不足时双开;数字动态计算"),
    }


def get_rules() -> dict[str, object]:
    # 姿态案例K线窗随物化 payload 出(v6.10 规则页四宫格图解;旧物化无此键→空表)
    pose_cases: list[dict[str, object]] = []
    try:
        row = repository.load_backtest_report(contracts.HPR_RULES_VERSION)
        if row:
            pose_cases = list(row.get("pose_cases") or [])
    except Exception:
        pose_cases = []
    return {
        "rules_version": contracts.HPR_RULES_VERSION,
        "group4_labels": contracts.GROUP4_LABELS,
        "point_labels": contracts.POINT_LABELS,
        "point_levels": contracts.POINT_LEVELS,
        "point_desc": contracts.POINT_DESC,
        "point_names": {s["no"]: s["name"] for s in contracts.SCHEMES},
        "point_psycho": contracts.POINT_PSYCHO,
        "point_stats": contracts.POINT_STATS,     # 成绩速览(16笔·胜69%·均+12.0)
        "point_boards": contracts.POINT_BOARDS,   # 板位归属(打3板/打4板)
        "rules": contracts.RULES,
        "cheat_rows": contracts.CHEAT_ROWS,   # 速查表(规则页主表;单一事实源,前端不维护副本)
        "weak_cheat_rows": contracts.WEAK_CHEAT_ROWS,  # 弱市组速查表(v7.0动态口诀组)
        "weak_point_boards": contracts.WEAK_POINT_BOARDS,
        "dyn_group_window": contracts.DYN_GROUP_WINDOW,
        "falsified_rules": contracts.FALSIFIED_RULES,
        "risk_notes": contracts.RISK_NOTES,
        "ths_pool_conditions": contracts.THS_POOL_CONDITIONS,
        "ths_pool_note": contracts.THS_POOL_NOTE,
        "intraday_playbook": contracts.INTRADAY_PLAYBOOK,
        "anchors": contracts.BACKTEST_ANCHORS,
        "anchor_tolerances": contracts.ANCHOR_TOLERANCES,
        "case_gates": contracts.CASE_GATES,
        "pose_cases": pose_cases,
    }


def _iso(value: object) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else (
        str(value) if value else None)


def _date_iso(value: object) -> str | None:
    return value.isoformat() if isinstance(value, date) else (
        str(value) if value else None)
