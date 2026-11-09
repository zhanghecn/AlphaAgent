from alphaagent.server.services.high_relay.quiz import (
    _nearest_scheme_line,
    _nearest_weak_line,
    explain_miss,
    mix_question_keys,
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
    assert row["ground"] == "二板实体/一字不碰"


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
    assert row["stat"] == "5笔·胜100%·均+13.2"


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


def test_three_board_yizi_is_retired_from_c3():
    """三板一字分支已退役(v7.26):不再归C3,按C2换手10~20讲,不能打。"""
    text, near_hit, fail_fields, row = _nearest_scheme_line(
        "三接四阳",
        b1_open=2.0,
        b2_open=1.0,
        b3_open=10.0,
        b2_turn=2.0,
        b3_turn=4.0,
        buy_open=7.2,
        foundation_chg=-8.0,
        pre10_pct=-2.0,
        foundation_pose="骑线",
        anchor_pos=-6.0,
        anchor_dist=None,
        dist_ma10=1.0,
    )

    assert near_hit is True
    assert fail_fields == ["三板开"]
    assert row is not None
    assert row["no"] == "C2"
    reasons, _, _, _ = explain_miss(
        n_board=3, yang=True, group4="三接四阳",
        b1_open=2.0, b2_open=1.0, b3_open=10.0,
        b2_turn=2.0, b3_turn=4.0, buy_open=7.2, pre20_pct=None,
        foundation_chg=-8.0, pre10_pct=-2.0, foundation_pose="骑线",
        anchor_pos=-6.0, anchor_dist=None, dist_ma10=1.0,
    )
    assert any("三板一字分支已退役" in r for r in reasons)


# ── v7.33 当前口径卷 + 陷阱空类配额回填 ──

def _mix_rows(n_good: int = 4, n_near: int = 50, n_yy: int = 5, n_toxic: int = 0):
    rows = []
    for i in range(n_good):
        rows.append({"decision_date": f"2021-03-1{i % 10}", "vt_symbol": f"00010{i}.SZSE",
                     "point": "K5", "trap_kind": None})
    for i in range(n_near):
        rows.append({"decision_date": f"2021-06-0{i % 9 + 1}", "vt_symbol": f"10000{i}.SZSE",
                     "point": "—", "trap_kind": "near"})
    for i in range(n_yy):
        rows.append({"decision_date": f"2021-07-0{i + 1}", "vt_symbol": f"20000{i}.SZSE",
                     "point": "—", "trap_kind": "yin_yang"})
    for i in range(n_toxic):
        rows.append({"decision_date": f"2021-08-0{i % 9 + 1}", "vt_symbol": f"30000{i}.SZSE",
                     "point": "—", "trap_kind": "toxic"})
    return rows


def test_mix_trap_deficit_backfills_empty_kind():
    """空类配额回填(2026-11-09 主人拍板顺手修):排最后的 toxic 存量=0(弱市卷
    形态——弱市口诀链松,miss 题全归 near)时,缺口不再沉淀,陷阱总数=trap_total。"""
    rows = _mix_rows(n_good=4, n_near=50, n_yy=5, n_toxic=0)
    keys = mix_question_keys(rows, trap_total=30, rng=7)
    kind_of = {(str(r["decision_date"]), str(r["vt_symbol"])): r["trap_kind"] for r in rows}
    kinds = [kind_of[k] for k in keys]
    # 好票 4 道 K5 池按 per_point=2 抽 2;陷阱 5+15+回填10 = 30 恰好抽满
    assert len(keys) == 2 + 30
    assert len(set(keys)) == len(keys)  # 回填轮不重复抽
    assert kinds.count(None) == 2
    assert kinds.count("near") == 25   # 15(直接) + 10(回填,yin_yang 池已干)
    assert kinds.count("yin_yang") == 5


def test_mix_trap_deficit_survives_when_all_empty():
    """三类陷阱全空(极小年景卷):回填轮全干即止,不死循环,只出好票。"""
    keys = mix_question_keys(_mix_rows(n_good=2, n_near=0, n_yy=0), trap_total=30, rng=1)
    assert len(keys) == 2


def test_get_quiz_mixed_current_era_resolves_group(monkeypatch):
    """era=current:读当前动态组(current_dyn_group 同源物化)按月状态过滤抽题,
    响应带 era_group(2026-11-09 主人拍板「按当前动态口径自行判断强弱」)。"""
    from alphaagent.server.services.high_relay import quiz as quiz_mod
    from alphaagent.server.services.high_relay import service

    calls = {}
    monkeypatch.setattr(service, "current_dyn_group",
                        lambda: {"group": "strong", "asof": "2026-10"})
    monkeypatch.setattr(service.repository, "quiz_bank_status",
                        lambda: {"rules_versions": [quiz_mod.quiz_rules_version()], "count": 1})

    def fake_proj(years, era, dyn_state=None):
        calls["args"] = (years, era, dyn_state)
        return []

    monkeypatch.setattr(service.repository, "load_quiz_mix_projection", fake_proj)
    monkeypatch.setattr(service.repository, "load_quiz_questions_by_keys", lambda keys: [])
    out = service.get_quiz_mixed(era="current")
    assert out["status"] == "ok"
    assert out["era_group"] == "strong"
    assert calls["args"] == (None, "current", "strong")


def test_get_quiz_mixed_current_era_both_falls_back(monkeypatch):
    """era=current 且组=both(无物化兜底,理论不可达):回退全库不过滤,照实标注。"""
    from alphaagent.server.services.high_relay import quiz as quiz_mod
    from alphaagent.server.services.high_relay import service

    calls = {}
    monkeypatch.setattr(service, "current_dyn_group", lambda: {"group": "both", "asof": None})
    monkeypatch.setattr(service.repository, "quiz_bank_status",
                        lambda: {"rules_versions": [quiz_mod.quiz_rules_version()], "count": 1})

    def fake_proj(years, era, dyn_state=None):
        calls["args"] = (years, era, dyn_state)
        return []

    monkeypatch.setattr(service.repository, "load_quiz_mix_projection", fake_proj)
    monkeypatch.setattr(service.repository, "load_quiz_questions_by_keys", lambda keys: [])
    out = service.get_quiz_mixed(era="current")
    assert out["status"] == "ok"
    assert out["era_group"] == "both"
    assert calls["args"] == (None, "current", None)
