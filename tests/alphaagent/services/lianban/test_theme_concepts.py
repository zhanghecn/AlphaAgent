"""theme_concepts 主题材分配算法测试(2026-08-14 规则定稿的固化).

场景取自 08-14 实测: 专概念(液冷 153/稀土永磁 46)优先于泛概念
(人工智能 712/通信技术 382), 风格类伪概念(融资融券/央国企改革)排除。
"""
from __future__ import annotations

import pytest
from sqlalchemy import insert

from alphaagent.server.db import schema
from alphaagent.server.services.lianban.theme_concepts import assign_theme_concepts


def _concept(session, sector_id: str, name: str, members: list[str], *, stype: str = "concept"):
    session.execute(
        insert(schema.sectors).values(
            id=sector_id, name=name, type=stype, source="test"
        )
    )
    for v in members:
        sym, _, ex = v.partition(".")
        session.execute(
            insert(schema.sector_memberships).values(
                sector_id=sector_id,
                vt_symbol=v,
                symbol=sym,
                exchange=ex or "SSE",
                name=f"股{sym}",
                source="test",
            )
        )


@pytest.fixture()
def seeded_session(fake_session):
    """复刻 08-14 关键分布: 亨通光电挂泛+专概念, 金田股份挂稀土永磁。"""
    s = fake_session
    # 专概念: 液冷 3 只聚集(成员总规模小)
    _concept(s, "BKLC", "液冷概念", ["600105.SSE", "600106.SSE", "600107.SSE"])
    # 专概念: 稀土永磁 2 只聚集
    _concept(s, "BKXT", "稀土永磁", ["600201.SSE", "600202.SSE"])
    # 泛概念: 人工智能(成员 >300 模拟: 造 301 个成员)
    wide = [f"3{i:05d}.SZSE" for i in range(301)]
    wide += ["600105.SSE", "600201.SSE"]  # 涨停股也挂在泛概念下
    _concept(s, "BKAI", "人工智能", wide)
    # 伪概念: 融资融券(风格类)聚集再多也排除
    _concept(s, "BKRZ", "融资融券", ["600105.SSE", "600106.SSE", "600107.SSE", "600201.SSE"])
    # 伪概念: 含"昨日"模式
    _concept(s, "BKZT", "昨日涨停", ["600105.SSE", "600106.SSE"])
    # 单只不成组的专概念
    _concept(s, "BKGPS", "光通信模块", ["600106.SSE"])
    # industry 板块(非 concept 不参与)
    _concept(s, "BKHY", "通信设备", ["600105.SSE"], stype="industry")
    s.flush()
    return s


def test_special_concept_beats_wide_concept(seeded_session):
    """专概念聚集优先于泛概念: 600105 同挂人工智能(泛,2聚集)与液冷(专,3聚集) → 液冷。"""
    result = assign_theme_concepts(
        seeded_session, ["600105.SSE", "600106.SSE", "600107.SSE", "600201.SSE"]
    )
    assert result["600105.SSE"] == "液冷"
    assert result["600106.SSE"] == "液冷"


def test_wide_concept_used_only_as_fallback(seeded_session):
    """600201 挂人工智能(泛)与稀土永磁(专) → 稀土永磁; "概念"后缀已剥。"""
    result = assign_theme_concepts(
        seeded_session, ["600105.SSE", "600106.SSE", "600107.SSE", "600201.SSE", "600202.SSE"]
    )
    assert result["600201.SSE"] == "稀土永磁"
    assert result["600202.SSE"] == "稀土永磁"


def test_fake_concepts_excluded(seeded_session):
    """融资融券/昨日涨停(伪)聚集再多不参与; 单只概念不成组。"""
    result = assign_theme_concepts(seeded_session, ["600105.SSE", "600106.SSE"])
    assert set(result.values()) <= {"液冷"}  # 光通信模块 1 只不成组
    assert "融资融券" not in result.values()
    assert "昨日涨停" not in result.values()
    assert "光通信模块" not in result.values()


def test_member_keeps_own_best_concept_when_companion_leaves(seeded_session):
    """每股独立取最优(金时科技案例): 同伴被更强概念抢走 → 本股保留原概念
    单只组, 不踢回行业兜底——lianban「液冷(1)康盛 + 超级电容(1)金时」并存。"""
    s = seeded_session
    # 金时+康盛 挂"超级电容"(聚集2); 康盛还挂聚集更强的"液冷概念"(3只)
    _concept(s, "BKAI2", "超级电容", ["300001.SZSE", "300002.SZSE"])
    _concept(s, "BKDS", "液冷概念", ["300002.SZSE", "600301.SSE", "600302.SSE"])
    s.flush()
    result = assign_theme_concepts(
        s, ["300001.SZSE", "300002.SZSE", "600301.SSE", "600302.SSE"]
    )
    # 康盛 → 液冷(聚集更强); 金时仍归超级电容(单只组保留)
    assert result["300002.SZSE"] == "液冷"
    assert result["600301.SSE"] == "液冷"
    assert result["300001.SZSE"] == "超级电容"


def test_same_industry_cluster_beats_bigger_cross_industry_cluster(seeded_session):
    """亨通光电案例(2026-08-14): 液冷聚集 7 但同行业仅 2; 光通信聚集 5
    同行业 3 → 归光通信主业而非液冷沾边。行业用板块集合(共享即同族)。"""
    s = seeded_session
    # 亨通/剑桥(通信设备) + 5 只跨行业股 挂"液冷概念"(聚集 7, 同行业 2)
    _concept(s, "BKLC2", "液冷概念",
             ["600487.SSE", "603083.SSE", "300017.SZSE", "002418.SZSE",
              "601609.SSE", "300684.SZSE", "603881.SSE"])
    # 亨通/剑桥/中瓷(通信设备)+富信/杭电 挂"光通信模块"(聚集 5, 同行业 3)
    _concept(s, "BKGM", "光通信模块",
             ["600487.SSE", "603083.SSE", "003031.SZSE", "688662.SSE", "603618.SSE"])
    s.flush()
    industry_groups = {
        "600487.SSE": {"通信设备", "通信"}, "603083.SSE": {"通信设备", "通信"},
        "003031.SZSE": {"通信设备", "通信"}, "688662.SSE": {"其他电子"},
        "603618.SSE": {"电网设备", "电力设备"}, "300017.SZSE": {"IT服务Ⅱ"},
        "002418.SZSE": {"家电零部", "家用电器"}, "601609.SSE": {"工业金属", "有色金属"},
        "300684.SZSE": {"电子化学"}, "603881.SSE": {"通信服务", "通信"},
    }
    result = assign_theme_concepts(s, list(industry_groups), industry_groups=industry_groups)
    assert result["600487.SSE"] == "光通信模块"
    assert result["603083.SSE"] == "光通信模块"
    # 液冷残部(同行业各 1)仍聚在液冷
    assert result["300017.SZSE"] == "液冷"
    assert result["603881.SSE"] == "液冷"


def test_industry_group_hierarchy_links_rare_earth_chain(seeded_session):
    """金田股份案例(2026-08-14, lianban 3 只全归稀土永磁): 二级行业互不同行
    (工业金属/能源金属/环保设备)但共享「有色金属」一级行业板块 → 稀土聚集
    同族 2 家 > 液冷聚集 1 家 → 归稀土而非聚集更大的液冷。"""
    s = seeded_session
    # 金田+中国稀土+华宏 挂"稀土永磁"(聚集 3, 有色族共享 2 家)
    _concept(s, "BKXT2", "稀土永磁",
             ["601609.SSE", "000831.SZSE", "002645.SZSE"])
    # 金田+5 只非有色股 挂"液冷概念"(聚集 6, 有色族仅金田 1 家)
    _concept(s, "BKLC3", "液冷概念",
             ["601609.SSE", "300017.SZSE", "002418.SZSE", "300684.SZSE",
              "603881.SSE", "300018.SZSE"])
    s.flush()
    industry_groups = {
        "601609.SSE": {"工业金属", "有色金属", "铜"},
        "000831.SZSE": {"小金属", "有色金属", "稀土"},
        "002645.SZSE": {"环保", "环保设备"},
        "300017.SZSE": {"IT服务Ⅱ"}, "002418.SZSE": {"家用电器"},
        "300684.SZSE": {"电子"}, "603881.SSE": {"通信"}, "300018.SZSE": {"计算机"},
    }
    result = assign_theme_concepts(s, list(industry_groups), industry_groups=industry_groups)
    assert result["601609.SSE"] == "稀土永磁"
    assert result["000831.SZSE"] == "稀土永磁"
    assert result["002645.SZSE"] == "稀土永磁"


def test_dynamic_fake_name_patterns_cover_unseen_names(seeded_session):
    """动态语法判定: 未维护过的新伪概念命名(以「股」结尾/时间前缀/热股类)
    自动被挡, 无需人工补词表。"""
    s = seeded_session
    # 造从未在词表里的伪概念名, 全部应被模式挡住
    _concept(s, "BK1", "量化股", ["600501.SSE", "600502.SSE"])
    _concept(s, "BK2", "2027年报预增", ["600503.SSE", "600504.SSE"])
    _concept(s, "BK3", "某财商热股", ["600505.SSE", "600506.SSE"])
    _concept(s, "BK4", "AI应用", ["600507.SSE", "600508.SSE"])  # 真概念不挡
    s.flush()
    result = assign_theme_concepts(
        s,
        ["600501.SSE", "600502.SSE", "600503.SSE", "600504.SSE",
         "600505.SSE", "600506.SSE", "600507.SSE", "600508.SSE"],
    )
    assert "量化股" not in result.values()
    assert "2027年报预增" not in result.values()
    assert "某财商热股" not in result.values()
    assert result["600507.SSE"] == "AI应用"


def test_single_stock_solo_concept_still_labeled(fake_session):
    """单股兜底: 股票当日只挂一个专概念(聚集 1, 无任何聚集>=2 概念) →
    仍获得该概念题材标签(题材覆盖全部涨停票), 弱候选不与聚集组竞争。"""
    s = fake_session
    # 两只涨停股各挂互不重叠的专概念(各自聚集 1)
    _concept(s, "BKX", "电子纸", ["600511.SSE"])
    _concept(s, "BKY", "电子后视镜", ["600512.SSE"])
    # 一只挂聚集 2 的概念(正常组)
    _concept(s, "BKZ", "石墨烯", ["600513.SSE", "600514.SSE"])
    # 600513 同时挂一个「当日仅它」的专概念 → 应选聚集组(弱候选排后)
    _concept(s, "BKW", "汽车黑匣子", ["600513.SSE"])
    s.flush()
    result = assign_theme_concepts(
        fake_session,
        ["600511.SSE", "600512.SSE", "600513.SSE", "600514.SSE"],
    )
    assert result["600511.SSE"] == "电子纸"
    assert result["600512.SSE"] == "电子后视镜"
    assert result["600513.SSE"] == "石墨烯"
    assert result["600514.SSE"] == "石墨烯"


def test_no_memberships_returns_empty(fake_session):
    assert assign_theme_concepts(fake_session, ["000001.SSE"]) == {}
    assert assign_theme_concepts(fake_session, []) == {}


def test_missing_table_degrades_to_empty(fake_session):
    """查询异常(如表缺失) → {} 降级行业分组, 不抛出。"""
    from sqlalchemy import text

    with fake_session.get_bind().connect() as conn:
        conn.execute(text("DROP TABLE sector_memberships"))
        conn.commit()
    assert assign_theme_concepts(fake_session, ["600105.SSE"]) == {}
