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


def test_orphan_concept_member_falls_to_next_choice(seeded_session):
    """最优概念被同伴的更优选择掏空(剩1只) → 孤儿降级次优/行业, 不留单只组。"""
    s = seeded_session
    # 游族网络+风语筑 挂"AI应用"(聚集2); 风语筑还挂聚集更强的"DeepSeek"(3只)
    _concept(s, "BKAI2", "AI应用概念", ["300001.SZSE", "300002.SZSE"])
    _concept(s, "BKDS", "DeepSeek", ["300002.SZSE", "600301.SSE", "600302.SSE"])
    s.flush()
    result = assign_theme_concepts(
        s, ["300001.SZSE", "300002.SZSE", "600301.SSE", "600302.SSE"]
    )
    # 风语筑 → DeepSeek(聚集更强); 游族网络的 AI应用 被掏空 → 无次优 → 不分配(行业兜底)
    assert result["300002.SZSE"] == "DeepSeek"
    assert result["600301.SSE"] == "DeepSeek"
    assert "300001.SZSE" not in result
    assert all(name != "AI应用" for name in result.values())


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
