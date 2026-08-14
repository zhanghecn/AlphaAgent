"""涨停股主题材分配: 东财概念板块按特异性分组(2026-08-14 定稿).

对标 lianban.net 的概念级题材分类(光模块/液冷/稀土永磁), 替代
复盘页旧口径的东财二级行业分组(通信设备 6 只混着数条主线)。

算法(2026-08-14 模拟验证, 与 lianban 当日 49 题材对齐):
1. 涨停名单 → concept memberships, 过滤伪概念(动态判定, 见 _is_fake_concept);
2. 概念分层: 成员 <= _WIDE_CONCEPT_MEMBERS(300) 为专概念(tier 0),
   其上为泛概念(tier 1, 如人工智能 712/华为 751——聚集再多也只是沾边);
3. 主题材 = 候选中 (tier, -同行业聚集数, -聚集数, -聚集纯度, 概念名)
   最小者——专概念优先 → 同行业聚集更多(真实产业链) → 聚集更多 →
   聚集更纯; 每股独立取最优, 概念组允许单只(对齐 lianban: 其 49 组
   中 28 组为单只);
4. 无「聚集 >=2」候选的股票: 挂有专概念(规模 <=300)则取其最优概念为
   单只题材标签(全部涨停票尽量有题材); 否则回落行业分组(调用方兜底)。

纯 memberships 无法复现 lianban 的新闻驱动打标(其 rs 文案来自财联社
报道), 但头部组(液冷/光通信模块/算力/稀土永磁)实测高度对齐。
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from sqlalchemy import func, select

from alphaagent.server.db import schema

# 成员超过此数的概念视为泛概念(仅兜底层): 阈值取 300——液冷 153/光通信
# 模块 97/CPO 66/稀土永磁 46/算力 212 全部放行, 人工智能 712/通信技术
# 382/新材料 394 全部降权(2026-08-14 实测分布)。
_WIDE_CONCEPT_MEMBERS = 300

# 伪概念动态判定(模式级, 非词表——新出现的同类命名自动被挡):
# - 时间性状态: 昨日涨停/最近多板/近期新高/2026中报预增/次新股/ST/摘帽
# - 风格类语法: 以「股」结尾(大盘股/微盘股/题材股/黑马股/AB股/亏损股…)
# - 资金通道/持仓: 沪股通/融资融券/保证金/机构重仓/证金持股/股权激励
# - 榜单热度: 东方财富热股/同花顺概念/人气/龙虎
# - 估值风格: 高市净率/低价股/破净/破发/高送转/高股息
# - 地域政策: 深圳特区/滨海新区/东北振兴/长三角/一带一路/西部大开发
# - 指数成分: 上证50/中证500/沪深300/创业板综/MSCI/富时/标普(数字结尾)
# - 事件杂项: 参股银行/举牌/PPP/专精特新(政策认定标签, 非当日炒作题材)
# 2026-08-14 实测 14 个归档日普查出的全部伪概念均可被这些模式覆盖,
# 且未来「XX热股」「20XX年报预增」等新命名无需维护词表自动生效。
_FAKE_NAME_RE = re.compile(
    r"昨日|最近|近期|今年|中报|年报|半年报|季报|"
    r"预盈|预增|预亏|预减|扭亏|高送转|ST|次新|摘帽|新高|新低|"
    r"股$|成长$|价值$|"
    r"股通|融资|融券|保证金|重仓|持股|证金|股权|"
    r"热股|人气|热度|龙虎|同花顺|东方财富|通达信|"
    r"高市|低市|破净|破发|破增|高价|低价|高股息|"
    r"特区|新区|振兴|长三角|珠三角|粤港澳|自贸|大开发|一带|"
    r"MSCI|富时|标普|罗素|板综|板指|"
    r"专精特新|PPP|举牌|参股|"
    r"(?:50|100|300|500|800|1000)$"
)


def _is_fake_name(name: str) -> bool:
    return _FAKE_NAME_RE.search(name) is not None


def assign_theme_concepts(
    session,
    vt_symbols: list[str],
    industry_groups: dict[str, set[str]] | None = None,
    news_concepts: dict[str, set[str]] | None = None,
) -> dict[str, str]:
    """给涨停股分配主题材概念。

    industry_groups: {vt_symbol: 行业板块名集合}; 缺省自动查 industry
    板块成员关系(个股同时挂一/二/三级行业板块, 如金田股份{工业金属,
    有色金属,铜})。「同行业」= 两股行业集合有交集(跨二级行业的同产业链
    自然成族, 2026-08-14 金田股份案例: 工业金属/能源金属/环保设备在二
    级行业下互不同行, 但共享「有色金属」一级行业板块 → 稀土永磁聚集
    同族 2 家 > 液冷聚集 1 家 → 归稀土, 对齐 lianban)。

    news_concepts: {vt_symbol: 新闻命中概念全名集合}(news_driver 归档
    抓取)——memberships 之外的股票-概念连接(如天洋新材未挂光通信板块,
    但 8/14 新闻「CPO 概念卷土重来」命中 CPO)。新闻概念按 memberships
    相同的聚集/分层规则参与竞争, 娱乐性噪音(生肖等)被聚集数自然压制。

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
        size_rows = session.execute(
            select(
                schema.sector_memberships.c.sector_id,
                schema.sectors.c.name,
                func.count(),
            )
            .join(schema.sectors, schema.sectors.c.id == schema.sector_memberships.c.sector_id)
            .where(schema.sectors.c.type == "concept")
            .group_by(schema.sector_memberships.c.sector_id, schema.sectors.c.name)
        ).all()
        sizes = {str(sid): int(n) for sid, _name, n in size_rows}
        concept_sid_of = {str(name): str(sid) for sid, name, _n in size_rows}
        # 数据信号兜底: 超大(>800)且行业超分散(top1 行业占比 <6%)的概念
        # 是全市场标签类(融资融券 3849/专精特新 3759/央国企改革——实测
        # top1 占比 2.3~7.8%, 而真题材即使跨行业也有 >8% 主行业), 未来
        # 新增同类标签无需人工维护。行业取 industry 板块成员关系。
        sector_ids = {str(sid) for _, _, sid in rows}
        wide_ids = {sid for sid, size in sizes.items() if size > 800}
        dispersed = _dispersed_concept_ids(session, wide_ids & sector_ids)
    except Exception:
        return {}

    def _is_fake(sid: str, name: str) -> bool:
        if _is_fake_name(name):
            return True
        return sid in dispersed

    by_concept: dict[tuple[str, str], set[str]] = defaultdict(set)
    for vsym, cname, sid in rows:
        name = str(cname)
        if _is_fake(str(sid), name):
            continue
        by_concept[(str(sid), name)].add(str(vsym))
    # 新闻命中概念(memberships 之外的连接)不进全局聚集——主线新闻会
    # 批量命中(「以CPO、PCB为代表的AI主线集体发力」提及的每只股都命中),
    # 叠加进聚集会让概念膨胀并抢走其他股的 memberships 主业归属(实测
    # CPO 聚集被新闻撑到 7 抢走光通信模块的亨通/剑桥)。改为每股独立
    # 视角: 仅本股把该概念作为额外候选, 聚集数 = memberships 聚集 + 1。
    news_map: dict[str, set[str]] = {}
    if news_concepts:
        wanted = set(vt_symbols)
        for vsym, names in news_concepts.items():
            valid = {
                name for name in names
                if concept_sid_of.get(name) and not _is_fake_name(name)
            }
            if vsym in wanted and valid:
                news_map[str(vsym)] = valid

    # 每股候选: (tier, -同行业聚集数, -聚集数, -聚集纯度, 概念名);
    # 排序取最小 = 专概念 → 同行业聚集更多 → 聚集更多 → 聚集更纯。
    # 同行业聚集分 = 聚集各成员与该股的共享行业板块数之和(二级+一级双
    # 共享=2 分 > 仅一级行业共享=1 分, 保持聚落间区分度; 布尔交集曾让
    # 「通信」一级行业把液冷里的数据港与亨通连成同族而错抢), 聚集纯度 =
    # 同行业分/聚集数——同行业集体涨停更可能是该股的真实驱动产业链。
    # 聚集数是主信号(大聚落优先, 纯度只做聚集数后的决胜, 放前面会打散
    # 大聚落)。成员规模只用于 tier 分层不进决胜链(54 vs 97 无产业意义,
    # 实测让毫米波错抢亨通); 全平局交概念名字典序(稳定可复现)。
    # (2026-08-14 亨通光电案例: 液冷聚集 7 同「通信设备」仅 2 → 不归液
    # 冷沾边; 毫米波/光通信模块同行业聚集均 3 聚集均 5 纯度均 60%, 字典
    # 序光通信胜 → 归光通信主业, 对齐 lianban 光纤概念的光通信口径。)
    if industry_groups is None:
        industry_groups = _industry_groups(session, vt_symbols)
    candidates: dict[str, list[tuple[int, int, int, float, str]]] = defaultdict(list)
    for (_sid, cname), syms in by_concept.items():
        size = sizes.get(_sid, 99999)
        tier = 0 if size <= _WIDE_CONCEPT_MEMBERS else 1
        if len(syms) >= 2:
            for vsym in syms:
                groups = industry_groups.get(vsym)
                if not groups:
                    same_industry = len(syms)
                else:
                    same_industry = sum(
                        len(industry_groups.get(other, set()) & groups)
                        for other in syms
                    )
                purity = same_industry / len(syms)
                candidates[vsym].append(
                    (tier, -same_industry, -len(syms), -purity, cname)
                )
        elif size <= _WIDE_CONCEPT_MEMBERS:
            # 单股兜底: 当日仅本股挂此专概念 → 弱候选(tier+2 排最后),
            # 股票没有任何聚集>=2 概念时才被用到(题材覆盖全部涨停票)。
            for vsym in syms:
                candidates[vsym].append((tier + 2, -1, -1, -1.0, cname))

    # 新闻命中候选: 仅本股视角, 聚集数 = 该概念 memberships 聚集 + 1;
    # 同行业分与 memberships 候选同口径——含自身贡献(曾因漏算自身 3 分
    # 而系统性输给 memberships 候选)。且只救「memberships 弱归属」的股:
    # 该股最优 memberships 候选的聚集中除自身外无同族(如天洋在网红经济
    # 聚集里全是食品/IT 股, 无塑料化工同行)时才允许 news 候选竞争——
    # 强归属(聚落里有同行, 如亨通之于光通信模块)不受 news 扰动。
    membership_best: dict[str, tuple] = {}
    for vsym, opts in candidates.items():
        if opts:
            membership_best[vsym] = min(opts)
    for vsym, names in news_map.items():
        groups = industry_groups.get(vsym) or set()
        best = membership_best.get(vsym)
        if best is not None and groups:
            # best = (tier, -same, -cluster, -purity, name): same 含自身
            # len(groups), 除自身同族 = same - len(groups)。
            if -best[1] - len(groups) > 0:
                continue  # 强归属, news 不竞争
        for name in names:
            sid = concept_sid_of[name]
            members = by_concept.get((sid, name), set())
            cluster = len(members) + 1
            if groups:
                same = len(groups) + sum(
                    len(industry_groups.get(other, set()) & groups)
                    for other in members
                )
            else:
                same = cluster
            candidates[vsym].append(
                (0 if sizes.get(sid, 99999) <= _WIDE_CONCEPT_MEMBERS else 1,
                 -same, -cluster, -(same / cluster), name)
            )

    # 每股独立取自己的最优概念——同伴归哪组不影响本股(2026-08-14 金时
    # 科技案例: 超级电容聚集=金时+康盛, 康盛按聚集优先归液冷(主业液冷
    # 管路, 正确), 金时仍归超级电容单只组——lianban 同日正是「液冷(1)
    # 康盛 + 超级电容(1) 金时」并存, 其 49 组中 28 组为单只, 每股独立
    # 按驱动打标是常态)。
    ranked = {
        vsym: sorted(options) for vsym, options in candidates.items()
    }
    return {
        vsym: opts[0][4].removesuffix("概念")
        for vsym, opts in ranked.items()
    }


def _industry_groups(session, vt_symbols: list[str]) -> dict[str, set[str]]:
    """{vt_symbol: 其挂的 industry 板块名集合}(含一/二/三级, 层级天然提供
    跨二级行业的产业链族信号)。查询失败 → {}(同行业信号退化为聚集数)。"""
    try:
        rows = session.execute(
            select(
                schema.sector_memberships.c.vt_symbol,
                schema.sectors.c.name,
            )
            .join(schema.sectors, schema.sectors.c.id == schema.sector_memberships.c.sector_id)
            .where(
                schema.sector_memberships.c.vt_symbol.in_(vt_symbols),
                schema.sectors.c.type == "industry",
            )
        ).all()
    except Exception:
        return {}
    groups: dict[str, set[str]] = defaultdict(set)
    for vsym, iname in rows:
        groups[str(vsym)].add(str(iname))
    return groups


def _dispersed_concept_ids(
    session, sector_ids: set[str], *, top1_threshold: float = 0.06
) -> set[str]:
    """返回行业超分散(top1 行业占比 < 阈值)的概念 id(全市场标签类)。

    行业口径 = industry 板块成员关系(stocks.industry 列为空, 不可用)。
    仅对涨停股挂到的超大概念计算, 无关概念不浪费聚合。
    """
    if not sector_ids:
        return set()
    rows = session.execute(
        select(
            schema.sector_memberships.c.sector_id,
            schema.sector_memberships.c.vt_symbol,
        )
        .join(schema.sectors, schema.sectors.c.id == schema.sector_memberships.c.sector_id)
        .where(
            schema.sectors.c.type == "concept",
            schema.sector_memberships.c.sector_id.in_(sector_ids),
        )
    ).all()
    member_symbols = list({str(vsym) for _, vsym in rows})
    industry_rows = session.execute(
        select(
            schema.sector_memberships.c.vt_symbol,
            schema.sectors.c.name,
        )
        .join(schema.sectors, schema.sectors.c.id == schema.sector_memberships.c.sector_id)
        .where(
            schema.sectors.c.type == "industry",
            schema.sector_memberships.c.vt_symbol.in_(member_symbols),
        )
    ).all()
    industry_of = {}
    for vsym, iname in industry_rows:
        industry_of.setdefault(str(vsym), str(iname))

    industry_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    totals: dict[str, int] = defaultdict(int)
    for sid, vsym in rows:
        industry = industry_of.get(str(vsym))
        if industry is None:
            continue
        industry_counts[str(sid)][industry] += 1
        totals[str(sid)] += 1

    return {
        sid
        for sid, total in totals.items()
        if total > 0
        and max(industry_counts[sid].values()) / total < top1_threshold
    }
