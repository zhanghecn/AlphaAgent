"""个股龙头身份识别服务。

在个股详情页展示「它是哪个行业的龙 N」。核心思路：只看**行业(industry)
概念**（题材/风格/指数/地域概念会引入冷门题材刷分和噪音），在行业概念内
按 市值 + 成交额 + 20日涨幅 三因子 min-max 归一化后加权打分。

为什么只看 industry：
    - ``industry`` 概念代表主业身份（面板、通信设备、通信线缆及配套…），
      排名稳定且符合「它是做什么的龙」直觉。
    - ``theme`` 概念混入了风格/指数（大盘股、富时罗素、MSCI）、地域、事件、
      冷门题材，会让大市值股靠市值碾压在小概念里刷成龙一，误导身份判断。

数据全部来自本地 ``sector_memberships`` / ``stock_sector_memberships`` 表，
不调用外部行情接口，不调用 LLM，零新增数据源。A股 100% 覆盖 industry 概念，
平均每只股 3 个行业概念。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from alphaagent.server.db import schema
from alphaagent.server.db.session import is_database_configured, session_scope

# ── 综合分权重（三因子之和为 1.0）──────────────────────────────────────
# 市值权重最大：贴合「行业地位 / 规模龙头」直觉，且最稳定。
WEIGHT_MARKET_CAP = 0.4
WEIGHT_TURNOVER = 0.3   # 成交额：反映资金活跃度 / 市场关注度
WEIGHT_RETURN_20D = 0.3  # 20日涨幅：反映中期趋势，下跌统一截零（不奖励「跌得少」）

# 进入身份卡展示的概念数安全上限（industry 概念平均 3 个，最多留 6 个）
DEFAULT_LEADER_LIMIT = 6
# 概念成分股少于此数时跳过——样本太小排名无意义
DEFAULT_MIN_MEMBERS = 5
# rank <= 此值视为「真龙头」（龙一/龙二/龙三），前端用奖牌标识
LEADER_RANK_THRESHOLD = 3
# 只看行业概念，过滤题材(theme)/风格/指数/地域噪音
DEFAULT_SECTOR_TYPES: tuple[str, ...] = ("industry",)


def compute_leader_identity(
    vt_symbol: str,
    limit: int = DEFAULT_LEADER_LIMIT,
    min_members: int = DEFAULT_MIN_MEMBERS,
    sector_types: tuple[str, ...] = DEFAULT_SECTOR_TYPES,
) -> dict[str, Any]:
    """计算个股的行业龙头身份。

    返回结构::

        {
            "vt_symbol": "000725.SZSE",
            "has_leader_identity": True,
            "leader_concepts": [
                {"sector_id": ..., "concept": "面板", "rank": 1, "total": 42,
                 "score": 0.70, "is_leader": True, "stock_change_pct": 2.1, ...},
                ...
            ],
            "data_quality": {"scanned_concepts": 3, "skipped_small": 0},
        }

    边界处理：
        - 数据库未配置 / 个股无行业归属 → ``has_leader_identity=False``
        - 行业成分股 < ``min_members`` → 跳过该行业（计入 ``skipped_small``）
        - 任一因子缺失 → 该因子按 0 计（保守）
    """

    if not is_database_configured():
        return _empty_identity(vt_symbol, reason="database_unavailable")

    scanned = 0
    skipped_small = 0
    leader_concepts: list[dict[str, Any]] = []

    with session_scope() as session:
        # 1. 查个股所属的行业概念（过滤题材/风格/指数/地域噪音）
        concept_rows = session.execute(
            select(
                schema.stock_sector_memberships.c.sector_id,
                schema.stock_sector_memberships.c.sector_name,
                schema.stock_sector_memberships.c.sector_type,
            ).where(
                schema.stock_sector_memberships.c.vt_symbol == vt_symbol,
                schema.stock_sector_memberships.c.sector_type.in_(sector_types),
            )
        ).mappings().all()

        if not concept_rows:
            return _empty_identity(vt_symbol, reason="no_industry_membership")

        # 2. 对每个行业：取成分股、概念内打分、找该股名次
        for concept in concept_rows:
            sector_id = concept["sector_id"]
            member_rows = session.execute(
                select(
                    schema.sector_memberships.c.vt_symbol,
                    schema.sector_memberships.c.name,
                    schema.sector_memberships.c.change_pct,
                    schema.sector_memberships.c.market_cap,
                    schema.sector_memberships.c.turnover,
                    schema.sector_memberships.c.return_20d,
                ).where(schema.sector_memberships.c.sector_id == sector_id)
            ).mappings().all()

            members = [dict(row) for row in member_rows]
            if len(members) < min_members:
                skipped_small += 1
                continue
            scanned += 1

            ranked = _rank_members_in_concept(members)
            for rank, item in enumerate(ranked, start=1):
                if item["vt_symbol"] != vt_symbol:
                    continue
                leader_concepts.append(
                    {
                        "sector_id": sector_id,
                        "concept": concept["sector_name"],
                        "concept_type": concept["sector_type"],
                        "rank": rank,
                        "total": len(members),
                        "score": round(item["score"], 4),
                        "is_leader": rank <= LEADER_RANK_THRESHOLD,
                        "stock_change_pct": _safe_float(item.get("change_pct")),
                    }
                )
                break  # 该行业里已找到该股，无需继续

    # 按名次升序、分数降序排（同名次时分数高的在前）
    leader_concepts.sort(key=lambda x: (x["rank"], -x["score"]))
    return {
        "vt_symbol": vt_symbol,
        "has_leader_identity": bool(leader_concepts),
        "leader_concepts": leader_concepts[:limit],
        "data_quality": {
            "scanned_concepts": scanned,
            "skipped_small": skipped_small,
        },
    }


def _rank_members_in_concept(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """概念内三因子 min-max 归一化 + 加权打分，返回按综合分降序的成分股列表。

    归一化细节：
        - 市值、成交额：标准 min-max，缺失按 0 计。
        - 20日涨幅：负值截零（下跌不奖励），仅在 ``[0, ret_max]`` 区间归一化；
          若整个概念都在跌（ret_max<=0），趋势因子失效，该概念只看市值+成交额。
    """

    caps = [_safe_float(m.get("market_cap")) for m in members]
    turns = [_safe_float(m.get("turnover")) for m in members]
    rets = [_safe_float(m.get("return_20d")) for m in members]

    cap_min, cap_max = min(caps), max(caps)
    turn_min, turn_max = min(turns), max(turns)
    # 趋势因子只看上涨区间：用 max(ret_min, 0) 作为基准，ret_max 作为满分
    ret_floor = max(min(rets), 0.0)
    ret_ceiling = max(rets)
    ret_range = ret_ceiling - ret_floor

    cap_range = cap_max - cap_min
    turn_range = turn_max - turn_min

    for m in members:
        cap = _safe_float(m.get("market_cap"))
        turn = _safe_float(m.get("turnover"))
        ret = _safe_float(m.get("return_20d"))

        norm_cap = (cap - cap_min) / cap_range if cap_range > 0 else 0.0
        norm_turn = (turn - turn_min) / turn_range if turn_range > 0 else 0.0
        if ret <= 0 or ret_range <= 0:
            norm_ret = 0.0
        else:
            norm_ret = (ret - ret_floor) / ret_range

        m["score"] = (
            WEIGHT_MARKET_CAP * norm_cap
            + WEIGHT_TURNOVER * norm_turn
            + WEIGHT_RETURN_20D * norm_ret
        )

    members.sort(key=lambda x: x["score"], reverse=True)
    return members


def _safe_float(value: Any) -> float:
    """容错转 float，None / 非数字返回 0.0。"""

    if value is None:
        return 0.0
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    if f != f:  # NaN
        return 0.0
    return f


def _empty_identity(vt_symbol: str, reason: str) -> dict[str, Any]:
    return {
        "vt_symbol": vt_symbol,
        "has_leader_identity": False,
        "leader_concepts": [],
        "data_quality": {"scanned_concepts": 0, "skipped_small": 0, "reason": reason},
    }
