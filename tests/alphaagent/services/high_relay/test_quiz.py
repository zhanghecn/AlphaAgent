from alphaagent.server.services.high_relay.quiz import (
    _nearest_scheme_line,
    _nearest_weak_line,
)


def test_k4_near_miss_explains_turnover_as_two_rulers():
    text, near_hit, fail_fields, row = _nearest_weak_line(
        "三接四阳",
        b1_open=3.6,
        b2_open=5.7,
        b3_open=10.0,
        b1_turn=5.8,
        b2_turn=4.2,
        b3_turn=14.3,
        buy_open=1.2,
        foundation_chg=8.8,
        prev_wave60=0,
        dist_h60=-13.9,
    )

    assert near_hit is True
    assert fail_fields == ["三板开"]
    assert "三板换手14.3过了12~20这把尺" in text
    assert "二板只有4.2" in text
    assert "三换<二换" in text
    assert "放量没承接" not in text
    assert row is not None
    assert row["b3"] == "换手12~20且<二换"
    assert row["ground"] == "—"


def test_yizi_chain_miss_row_prefers_c3_over_c2():
    """一字链题差一腿并列时对照 C3 行不选 C2(欢瑞世纪 2026-09-03:
    讲解文引 C3「今开6~9.5」,对照表格却发 C2 行「今天开5~9」——
    今开+5.2 在表内、口诀文又说不能打,自相矛盾,主人 2026-10-23 拍板修)。"""
    text, near_hit, fail_fields, row = _nearest_scheme_line(
        "三接四阳",
        b1_open=3.3,
        b2_open=10.0,
        b3_open=9.9,
        b2_turn=1.8,
        b3_turn=3.1,
        buy_open=5.2,
        foundation_chg=3.2,
        pre10_pct=-2.3,
        foundation_pose="骑线",
        anchor_pos=-6.2,
        anchor_dist=None,
        dist_ma10=2.6,
    )

    assert near_hit is True
    assert fail_fields == ["今开"]
    assert row is not None
    assert row["no"] == "C3"
    assert row["b3"] == "换手3~5"
    assert row["today"] == "6~9.5"
    assert row["stat"] == "6笔·胜100%·均+11.9"


def test_solid_chain_miss_row_still_picks_c2():
    """实体换手链差一腿(换手超窗)仍对照 C2 行——一字系选行修正不回归 C2 正常题。"""
    text, near_hit, fail_fields, row = _nearest_scheme_line(
        "三接四阳",
        b1_open=3.0,
        b2_open=5.0,
        b3_open=6.0,
        b2_turn=8.0,
        b3_turn=22.0,
        buy_open=6.0,
    )

    assert near_hit is True
    assert fail_fields == ["三板开"]
    assert row is not None
    assert row["no"] == "C2"
    assert row["today"] == "5~9"
