from alphaagent.server.services.high_relay.quiz import _nearest_weak_line


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
