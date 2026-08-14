"""涨停股主题材分配: 东财概念板块按特异性分组(2026-08-14 定稿).

对标 lianban.net 的概念级题材分类(光模块/液冷/稀土永磁), 替代
复盘页旧口径的东财二级行业分组(通信设备 6 只混着数条主线)。

算法(2026-08-14 模拟验证, 与 lianban 当日 49 题材对齐):
1. 涨停名单 → concept memberships, 过滤风格/状态类伪概念;
2. 概念分层: 成员 <= _WIDE_CONCEPT_MEMBERS(300) 为专概念(tier 0),
   其上为泛概念(tier 1, 如人工智能 712/华为 751——聚集再多也只是沾边);
3. 主题材 = 候选中 (tier, -同行业聚集数, -聚集数, -聚集纯度, 概念名)
   最小者——专概念优先 → 同行业聚集更多(真实产业链) → 聚集更多 →
   聚集更纯; 每股独立取最优, 概念组允许单只(对齐 lianban: 其 49 组
   中 28 组为单只);
4. 未入概念组的股票回落行业分组(调用方兜底)。

纯 memberships 无法复现 lianban 的新闻驱动打标(其 rs 文案来自财联社
报道), 但头部组(液冷/光通信模块/算力/稀土永磁)实测高度对齐。
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import func, select

from alphaagent.server.db import schema

# 成员超过此数的概念视为泛概念(仅兜底层): 阈值取 300——液冷 153/光通信
# 模块 97/CPO 66/稀土永磁 46/算力 212 全部放行, 人工智能 712/通信技术
# 382/新材料 394 全部降权(2026-08-14 实测分布)。
_WIDE_CONCEPT_MEMBERS = 300

# 名称含这些子串的概念视为状态类伪概念(事件/榜单/风格/热度/地域), 直接排除。
_FAKE_PATTERNS = (
    "昨日", "最近", "近期", "中报", "预增", "预亏", "ST", "次新", "同花顺",
    "热度", "热股", "人气", "振兴", "新区", "特区", "长三角", "珠三角",
    "参股", "摘帽", "破净",
)

# 精确匹配的风格/指数/资金/地域类伪概念名(mainline_replay 风格词的
# 连板侧子集 + 2026-08-14 实测噪音: 央国企改革/股权分散/高市净率等)。
_FAKE_CONCEPTS = frozenset(
    """
    融资融券 沪股通 深股通 陆股通 机构重仓 基金重仓 QFII重仓 社保证金 证金持股
    养老金 MSCI 富时罗素 标准普尔 昨日涨停 昨日触板 昨日连板 昨日高振幅 昨日首板
    最近多板 近期新高 百日新高 次新股 新股 高送转 预盈预增 预亏预减 亏损股 扭亏
    破净股 破发股 破增发价股 百元股 高价股 低价股 大盘股 中盘股 小盘股 微盘股
    中证500 上证50 深证100 沪深300 央视50 AH股 AB股 茅指数 宁组合 股权激励
    专精特新 创业板综 科创板综 创业板指 科创板指 国企改革 央企改革 央国企改革
    深圳特区 长江三角 珠三角 西部大开发 一带一路 雄安新区 PPP模式 转债标的
    高股息 参股银行 参股保险 参股券商 举牌 中盘成长 大盘成长 小盘成长
    股权分散 高市净率 低市净率 高市盈率 低市盈率 东方财富热股 题材股
    趋势股 强势股 绩优股 黑马股 白马股 蓝筹股 反转股 长期破净
    """.split()
)


def _is_fake_concept(name: str) -> bool:
    if name in _FAKE_CONCEPTS:
        return True
    return any(p in name for p in _FAKE_PATTERNS)


def assign_theme_concepts(
    session,
    vt_symbols: list[str],
    industry_of: dict[str, str] | None = None,
) -> dict[str, str]:
    """给涨停股分配主题材概念; 只返回能入组(概念内 >=2 只)的股票。

    industry_of: {vt_symbol: 东财行业}; 提供时启用「同行业聚集数」信号
    (候选排序第二键), 缺省退化为纯聚集数排序。

    Returns: {vt_symbol: 概念名(已去"概念"后缀)}, 未返回的股票由调用方
    走行业兜底。查询失败/无 memberships → {}(整体降级行业分组)。
    """
    if not vt_symbols:
        return {}
    try:
        rows = session.execute(
            select(
                schema.sector_memberships.c.vt_symbol,
                schema.sectors.c.name,
                schema.sectors.c.id,
            )
            .join(schema.sectors, schema.sectors.c.id == schema.sector_memberships.c.sector_id)
            .where(
                schema.sector_memberships.c.vt_symbol.in_(vt_symbols),
                schema.sectors.c.type == "concept",
            )
        ).all()
        if not rows:
            return {}
        sizes = dict(
            session.execute(
                select(schema.sector_memberships.c.sector_id, func.count())
                .join(schema.sectors, schema.sectors.c.id == schema.sector_memberships.c.sector_id)
                .where(schema.sectors.c.type == "concept")
                .group_by(schema.sector_memberships.c.sector_id)
            ).all()
        )
    except Exception:
        return {}

    by_concept: dict[tuple[str, str], set[str]] = defaultdict(set)
    for vsym, cname, sid in rows:
        name = str(cname)
        if _is_fake_concept(name):
            continue
        by_concept[(str(sid), name)].add(str(vsym))

    # 每股候选: (tier, -同行业聚集数, -聚集数, -聚集纯度, 概念名);
    # 排序取最小 = 专概念 → 同行业聚集更多 → 聚集更多 → 聚集更纯。
    # 同行业聚集数 = 概念当日聚集中与该股同东财行业的家数, 聚集纯度 =
    # 同行业数/聚集数——同行业集体涨停更可能是该股的真实驱动产业链。
    # 聚集数是主信号(大聚落优先, 纯度只做聚集数后的决胜, 放前面会打散
    # 大聚落)。成员规模只用于 tier 分层不进决胜链(54 vs 97 无产业意义,
    # 实测让毫米波错抢亨通); 全平局交概念名字典序(稳定可复现)。
    # (2026-08-14 亨通光电案例: 液冷聚集 7 同「通信设备」仅 2 → 不归液
    # 冷沾边; 毫米波/光通信模块同行业聚集均 3 聚集均 5 纯度均 60%, 字典
    # 序光通信胜 → 归光通信主业, 对齐 lianban 光纤概念的光通信口径。)
    industry_map = industry_of or {}
    candidates: dict[str, list[tuple[int, int, int, float, str]]] = defaultdict(list)
    for (_sid, cname), syms in by_concept.items():
        if len(syms) < 2:
            continue
        size = sizes.get(_sid, 99999)
        tier = 0 if size <= _WIDE_CONCEPT_MEMBERS else 1
        for vsym in syms:
            industry = industry_map.get(vsym)
            if industry is None:
                same_industry = len(syms)
            else:
                same_industry = sum(
                    1 for other in syms if industry_map.get(other) == industry
                )
            purity = same_industry / len(syms)
            candidates[vsym].append(
                (tier, -same_industry, -len(syms), -purity, cname)
            )

    # 每股独立取自己的最优概念——同伴归哪组不影响本股(2026-08-14 金时
    # 科技案例: 超级电容聚集=金时+康盛, 康盛按聚集优先归液冷(主业液冷
    # 管路, 正确), 金时仍归超级电容单只组——lianban 同日正是「液冷(1)
    # 康盛 + 超级电容(1) 金时」并存, 其 49 组中 28 组为单只, 每股独立
    # 按驱动打标是常态)。组员被抢走即解散的「孤儿回收」曾把这类股踢回
    # 行业兜底, 与参照行为相反, 已删; 早期迭代式互相改投版本还有实测
    # 死循环问题(快照孤儿集与轮内状态错位恒定震荡), 一并成为历史。
    ranked = {
        vsym: sorted(options) for vsym, options in candidates.items()
    }
    return {
        vsym: opts[0][4].removesuffix("概念")
        for vsym, opts in ranked.items()
    }
