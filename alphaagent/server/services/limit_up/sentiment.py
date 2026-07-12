"""Historical sentiment and board-promotion snapshots for limit-up research."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import text


def load_sentiment_points(session: Any, start: date, end: date) -> list[dict[str, object]]:
    """Aggregate full-market emotion and main-board promotion ladders by date."""

    warmup_start = start - timedelta(days=45)
    rows = session.execute(
        text(
            """
            WITH base AS (
                SELECT
                    b.vt_symbol,
                    COALESCE(s.name, '') AS stock_name,
                    b.trade_date,
                    b.close_price,
                    b.high_price,
                    b.change_pct,
                    LAG(b.close_price) OVER (
                        PARTITION BY b.vt_symbol ORDER BY b.trade_date
                    ) AS previous_close
                FROM stock_daily_bars b
                LEFT JOIN stocks s ON s.vt_symbol = b.vt_symbol
                WHERE b.trade_date BETWEEN :warmup_start AND :end_date
            ),
            calc AS (
                SELECT
                    *,
                    CASE
                        WHEN change_pct IS NOT NULL THEN change_pct
                        WHEN previous_close IS NOT NULL AND previous_close <> 0
                            THEN (close_price / previous_close - 1) * 100
                        ELSE NULL
                    END AS change_calc,
                    CASE
                        WHEN previous_close IS NOT NULL AND previous_close <> 0
                            THEN (high_price / previous_close - 1) * 100
                        ELSE NULL
                    END AS high_change,
                    CASE
                        WHEN UPPER(stock_name) LIKE '%ST%' THEN 4.5
                        WHEN vt_symbol LIKE '8%' OR vt_symbol LIKE '4%'
                            OR vt_symbol LIKE '920%' OR vt_symbol LIKE '%.BSE'
                            OR vt_symbol LIKE '%.BJSE' THEN 29.0
                        WHEN vt_symbol LIKE '30%' OR vt_symbol LIKE '68%' THEN 19.0
                        ELSE 9.5
                    END AS limit_threshold,
                    CASE
                        WHEN split_part(vt_symbol, '.', 1) ~ '^(600|601|603|605|000|001|002|003)'
                            AND UPPER(stock_name) NOT LIKE '%ST%'
                            AND stock_name NOT LIKE '%退%'
                            AND UPPER(stock_name) !~ '^[SNC]'
                        THEN 1 ELSE 0
                    END AS is_main_board
                FROM base
                WHERE close_price IS NOT NULL
            ),
            flags AS (
                SELECT
                    *,
                    CASE WHEN change_calc >= limit_threshold THEN 1 ELSE 0 END AS is_limit_up,
                    CASE WHEN change_calc <= -limit_threshold THEN 1 ELSE 0 END AS is_limit_down,
                    CASE WHEN high_change >= limit_threshold THEN 1 ELSE 0 END AS touched_limit_up
                FROM calc
                WHERE change_calc IS NOT NULL
            ),
            grouped AS (
                SELECT
                    *,
                    LAG(is_limit_up, 1, 0) OVER (
                        PARTITION BY vt_symbol ORDER BY trade_date
                    ) AS previous_is_limit_up,
                    SUM(CASE WHEN is_limit_up = 1 THEN 0 ELSE 1 END) OVER (
                        PARTITION BY vt_symbol ORDER BY trade_date ROWS UNBOUNDED PRECEDING
                    ) AS streak_group
                FROM flags
            ),
            streaks AS (
                SELECT
                    *,
                    CASE
                        WHEN is_limit_up = 1 THEN
                            SUM(is_limit_up) OVER (
                                PARTITION BY vt_symbol, streak_group
                                ORDER BY trade_date ROWS UNBOUNDED PRECEDING
                            )
                        ELSE 0
                    END AS limit_up_streak
                FROM grouped
            ),
            lagged AS (
                SELECT
                    *,
                    LAG(limit_up_streak, 1, 0) OVER (
                        PARTITION BY vt_symbol ORDER BY trade_date
                    ) AS previous_limit_up_streak
                FROM streaks
            )
            SELECT
                trade_date,
                COUNT(*)::int AS total_stocks,
                SUM(CASE WHEN change_calc > 0 THEN 1 ELSE 0 END)::int AS rise_count,
                SUM(CASE WHEN change_calc < 0 THEN 1 ELSE 0 END)::int AS fall_count,
                SUM(CASE WHEN change_calc = 0 THEN 1 ELSE 0 END)::int AS flat_count,
                SUM(is_limit_up)::int AS limit_up_count,
                SUM(is_limit_down)::int AS limit_down_count,
                SUM(CASE WHEN touched_limit_up = 1 AND is_limit_up = 0 THEN 1 ELSE 0 END)::int AS failed_limit_up_count,
                SUM(previous_is_limit_up)::int AS previous_limit_up_count,
                SUM(CASE WHEN previous_is_limit_up = 1 AND is_limit_up = 1 THEN 1 ELSE 0 END)::int AS promoted_limit_up_count,
                MAX(limit_up_streak)::int AS max_limit_up_streak,
                SUM(CASE WHEN is_main_board = 1 AND is_limit_up = 1 THEN 1 ELSE 0 END)::int AS mainboard_limit_up_count,
                SUM(CASE WHEN is_main_board = 1 AND touched_limit_up = 1 AND is_limit_up = 0 THEN 1 ELSE 0 END)::int AS mainboard_failed_limit_up_count,
                MAX(CASE WHEN is_main_board = 1 THEN limit_up_streak ELSE 0 END)::int AS mainboard_max_limit_up_streak,
                SUM(CASE WHEN is_main_board = 1 AND previous_limit_up_streak = 0 AND touched_limit_up = 1 THEN 1 ELSE 0 END)::int AS first_board_base,
                SUM(CASE WHEN is_main_board = 1 AND previous_limit_up_streak = 0 AND is_limit_up = 1 THEN 1 ELSE 0 END)::int AS first_board_promoted,
                SUM(CASE WHEN is_main_board = 1 AND previous_limit_up_streak = 1 THEN 1 ELSE 0 END)::int AS one_to_two_base,
                SUM(CASE WHEN is_main_board = 1 AND previous_limit_up_streak = 1 AND is_limit_up = 1 THEN 1 ELSE 0 END)::int AS one_to_two_promoted,
                SUM(CASE WHEN is_main_board = 1 AND previous_limit_up_streak = 2 THEN 1 ELSE 0 END)::int AS two_to_three_base,
                SUM(CASE WHEN is_main_board = 1 AND previous_limit_up_streak = 2 AND is_limit_up = 1 THEN 1 ELSE 0 END)::int AS two_to_three_promoted,
                SUM(CASE WHEN is_main_board = 1 AND previous_limit_up_streak >= 3 THEN 1 ELSE 0 END)::int AS three_plus_base,
                SUM(CASE WHEN is_main_board = 1 AND previous_limit_up_streak >= 3 AND is_limit_up = 1 THEN 1 ELSE 0 END)::int AS three_plus_promoted
            FROM lagged
            WHERE trade_date BETWEEN :start_date AND :end_date
            GROUP BY trade_date
            ORDER BY trade_date
            """
        ),
        {
            "warmup_start": warmup_start,
            "start_date": start,
            "end_date": end,
        },
    ).mappings().all()
    points = [_point_from_row(dict(row)) for row in rows]
    previous_score: float | None = None
    previous_point: dict[str, object] | None = None
    for point in points:
        score = _number(point.get("score"))
        point["score_change"] = (
            round(score - previous_score, 1)
            if score is not None and previous_score is not None
            else None
        )
        point["phase"] = classify_sentiment_phase(point, previous_point)
        point["phase_label"] = _phase_label(str(point["phase"]))
        point["phase_reason"] = _phase_reason(point)
        previous_score = score
        previous_point = point
    return points


def _point_from_row(row: dict[str, object]) -> dict[str, object]:
    total = int(row.get("total_stocks") or 0)
    rise = int(row.get("rise_count") or 0)
    fall = int(row.get("fall_count") or 0)
    limit_up = int(row.get("limit_up_count") or 0)
    limit_down = int(row.get("limit_down_count") or 0)
    failed = int(row.get("failed_limit_up_count") or 0)
    previous_limit = int(row.get("previous_limit_up_count") or 0)
    promoted = int(row.get("promoted_limit_up_count") or 0)
    max_streak = int(row.get("max_limit_up_streak") or 0)
    up_ratio = rise / total if total else None
    down_ratio = fall / total if total else None
    failed_rate = failed / (failed + limit_up) if failed + limit_up else None
    promotion_rate = promoted / previous_limit if previous_limit else None
    score = _sentiment_score(
        up_ratio=up_ratio,
        down_ratio=down_ratio,
        limit_up_count=limit_up,
        limit_down_count=limit_down,
        max_streak=max_streak,
        failed_rate=failed_rate,
        promotion_rate=promotion_rate,
    )
    phase = _sentiment_phase(
        score=score,
        up_ratio=up_ratio,
        down_ratio=down_ratio,
        limit_up_count=limit_up,
        limit_down_count=limit_down,
        max_streak=max_streak,
        failed_rate=failed_rate,
        promotion_rate=promotion_rate,
    )
    main_sealed = int(row.get("mainboard_limit_up_count") or 0)
    main_failed = int(row.get("mainboard_failed_limit_up_count") or 0)
    return {
        "date": _date_text(row.get("trade_date")),
        "score": round(score, 1),
        "score_change": None,
        "phase": phase,
        "phase_label": _phase_label(phase),
        "total_stocks": total,
        "rise_count": rise,
        "fall_count": fall,
        "flat_count": int(row.get("flat_count") or 0),
        "up_ratio": _round4(up_ratio),
        "down_ratio": _round4(down_ratio),
        "limit_up_count": limit_up,
        "limit_down_count": limit_down,
        "failed_limit_up_count": failed,
        "failed_limit_up_rate": _round4(failed_rate),
        "previous_limit_up_count": previous_limit,
        "promoted_limit_up_count": promoted,
        "promotion_rate": _round4(promotion_rate),
        "max_limit_up_streak": max_streak,
        "mainboard_limit_up_count": main_sealed,
        "mainboard_failed_limit_up_count": main_failed,
        "mainboard_failed_limit_up_rate": _round4(
            main_failed / (main_sealed + main_failed)
            if main_sealed + main_failed
            else None
        ),
        "mainboard_max_limit_up_streak": int(row.get("mainboard_max_limit_up_streak") or 0),
        "promotion_ladder": {
            "first_board": _promotion_row(row, "first_board"),
            "one_to_two": _promotion_row(row, "one_to_two"),
            "two_to_three": _promotion_row(row, "two_to_three"),
            "three_plus": _promotion_row(row, "three_plus"),
        },
        "source": "stock_daily_bars",
        "data_cutoff": "D_CLOSE",
    }


def _promotion_row(row: dict[str, object], prefix: str) -> dict[str, object]:
    base = int(row.get(f"{prefix}_base") or 0)
    promoted = int(row.get(f"{prefix}_promoted") or 0)
    return {
        "base_count": base,
        "promoted_count": promoted,
        "rate": _round4(promoted / base if base else None),
    }


def _sentiment_score(
    *,
    up_ratio: float | None,
    down_ratio: float | None,
    limit_up_count: int,
    limit_down_count: int,
    max_streak: int,
    failed_rate: float | None,
    promotion_rate: float | None,
) -> float:
    if up_ratio is None:
        return 0.0
    failed_quality = 1 - min(max(failed_rate if failed_rate is not None else 0.25, 0.0), 1.0)
    risk_quality = 1 - min(limit_down_count / 50, 1.0)
    score = 100 * (
        0.28 * up_ratio
        + 0.22 * min(limit_up_count / 100, 1.0)
        + 0.18 * min(max_streak / 7, 1.0)
        + 0.14 * min(max(promotion_rate if promotion_rate is not None else 0.35, 0.0), 1.0)
        + 0.10 * failed_quality
        + 0.08 * risk_quality
    )
    score -= min(limit_down_count / 80, 1.0) * 12
    if down_ratio is not None:
        score -= max(0.0, down_ratio - up_ratio) * 12
    return max(0.0, min(100.0, score))


def classify_sentiment_phase(
    current: dict[str, object],
    previous: dict[str, object] | None = None,
) -> str:
    """Classify the short-cycle state from level, breadth, and direction."""

    score = _number(current.get("score")) or 0.0
    previous_score = _number((previous or {}).get("score"))
    score_change = _number(current.get("score_change"))
    if score_change is None and previous_score is not None:
        score_change = score - previous_score
    up_ratio = _number(current.get("up_ratio"))
    down_ratio = _number(current.get("down_ratio"))
    limit_up_count = int(current.get("limit_up_count") or 0)
    limit_down_count = int(current.get("limit_down_count") or 0)
    max_streak = int(current.get("max_limit_up_streak") or 0)
    failed_rate = _number(current.get("failed_limit_up_rate"))
    promotion_rate = _number(current.get("promotion_rate"))

    if (
        limit_down_count >= 80
        or (down_ratio is not None and down_ratio >= 0.72)
        or (score <= 22 and limit_down_count >= 40)
    ):
        return "ice"
    if down_ratio is not None and down_ratio >= 0.64 and limit_down_count >= 30:
        return "ebb"
    if (
        score >= 72
        and limit_up_count >= 50
        and max_streak >= 3
        and (failed_rate is None or failed_rate <= 0.42)
        and limit_down_count < 30
    ):
        return "climax"
    if (
        score >= 55
        and (score_change is None or score_change >= -3)
        and (promotion_rate is None or promotion_rate >= 0.20)
        and (failed_rate is None or failed_rate <= 0.38)
        and limit_down_count < 20
    ):
        return "mainrise"
    if (
        score_change is not None
        and score_change >= 6
        and limit_down_count < 35
        and (up_ratio is None or up_ratio >= 0.40)
    ):
        return "repair"
    if (
        (score_change is not None and score_change <= -8)
        or limit_down_count >= 30
        or (failed_rate is not None and failed_rate >= 0.45)
        or (
            promotion_rate is not None
            and promotion_rate < 0.18
            and limit_up_count >= 30
        )
    ):
        return "divergence"
    if score >= 38:
        return "repair"
    return "ebb"


def _phase_reason(point: dict[str, object]) -> str:
    phase = str(point.get("phase") or "")
    score_change = _number(point.get("score_change"))
    limit_down = int(point.get("limit_down_count") or 0)
    failed_rate = _number(point.get("failed_limit_up_rate"))
    details = [f"情绪分{_number(point.get('score')) or 0:.1f}"]
    if score_change is not None:
        details.append(f"变化{score_change:+.1f}")
    details.append(f"跌停{limit_down}家")
    if failed_rate is not None:
        details.append(f"炸板率{failed_rate * 100:.1f}%")
    return f"{_phase_label(phase)}：" + "，".join(details)


def _sentiment_phase(
    *,
    score: float,
    up_ratio: float | None,
    down_ratio: float | None,
    limit_up_count: int,
    limit_down_count: int,
    max_streak: int,
    failed_rate: float | None,
    promotion_rate: float | None,
) -> str:
    failed = failed_rate if failed_rate is not None else 0.0
    if limit_down_count >= 80 or (down_ratio is not None and down_ratio >= 0.70 and score < 45):
        return "ice"
    if score >= 72 and limit_up_count >= 50 and max_streak >= 3 and failed <= 0.42 and limit_down_count < 30:
        return "climax"
    if limit_down_count >= 30:
        return "divergence"
    if failed >= 0.45 and (limit_up_count >= 20 or score >= 50):
        return "divergence"
    if promotion_rate is not None and promotion_rate < 0.18 and limit_up_count >= 30:
        return "divergence"
    if score >= 38:
        return "repair"
    return "ebb"


def _phase_label(phase: str) -> str:
    return {
        "ice": "冰点",
        "repair": "修复",
        "mainrise": "主升",
        "uptrend": "主升",
        "divergence": "分歧",
        "climax": "高潮",
        "ebb": "退潮",
    }.get(phase, "未知")


def _date_text(value: object) -> str | None:
    if isinstance(value, date):
        return value.isoformat()
    text_value = str(value or "").strip()
    return text_value[:10] if len(text_value) >= 10 else None


def _round4(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def _number(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None
