from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = (
    REPO_ROOT
    / "量化因子研究"
    / "一接二"
    / "scripts"
    / "j12_final_composite.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("j12_final_composite", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row(**changes):
    row = {
        "pre5_pct": 0.0,
        "foundation_body": 0.0,
        "b1_turn": 10.0,
        "foundation_amplitude": 5.0,
        "today_open": 2.0,
        "foundation_yang": True,
        "foundation_pose": "骑线",
        "ma_state": "+++",
        "b1_gap": 2.0,
        "pre20_pct": 0.0,
        "b1_open": 2.0,
        "b1_break60": True,
        "foundation_vol_rel5": 1.0,
        "b1_turn_change": 5.0,
        "b1_vol_rel5": 1.0,
        "pre3_pct": 0.0,
        "dist_h60": -20.0,
        "unfinished": False,
        "data_bad_gap": False,
    }
    row.update(changes)
    return row


@pytest.mark.parametrize(
    ("rule_id", "changes"),
    [
        ("F1", {"pre5_pct": -16, "foundation_body": -4}),
        ("F2", {"b1_turn": 4, "foundation_amplitude": 12}),
        ("F3", {"today_open": 8, "foundation_yang": False, "foundation_pose": "站线上"}),
        ("F4", {"ma_state": "---", "foundation_body": -6, "b1_gap": 9}),
        ("F5", {"foundation_yang": False, "b1_gap": 6, "pre20_pct": 31}),
        ("F6", {"today_open": 9, "b1_open": -1, "b1_break60": False}),
        ("F7", {"foundation_body": -6, "foundation_vol_rel5": 1.3, "b1_turn_change": 1}),
        ("F8", {"b1_turn": 6, "b1_vol_rel5": 0.7, "pre3_pct": -10}),
        ("F9", {"ma_state": "---", "today_open": 8, "b1_turn_change": 1}),
        ("F10", {"dist_h60": -9, "foundation_body": 6, "pre3_pct": 7}),
    ],
)
def test_each_final_rule_hits_its_own_example(rule_id, changes):
    module = _load_module()
    frame = pd.DataFrame([_row(**changes)])

    masks = module.final_rule_masks(frame)

    assert masks[rule_id].tolist() == [True]
    assert sum(mask.iloc[0] for mask in masks.values()) == 1


def test_final_rules_use_left_closed_right_open_intervals():
    module = _load_module()
    frame = pd.DataFrame([
        _row(today_open=7.5, foundation_yang=False, foundation_pose="站线上"),
        _row(today_open=8.5, foundation_yang=False, foundation_pose="站线上"),
        _row(b1_turn=3, foundation_amplitude=12),
        _row(b1_turn=5, foundation_amplitude=12),
        _row(dist_h60=-10, foundation_body=5, pre3_pct=5),
        _row(dist_h60=-8, foundation_body=5, pre3_pct=5),
    ])

    masks = module.final_rule_masks(frame)

    assert masks["F3"].tolist() == [True, False, False, False, False, False]
    assert masks["F2"].tolist() == [False, False, True, False, False, False]
    assert masks["F10"].tolist() == [False, False, False, False, True, False]


def test_final_ledger_deduplicates_overlaps_and_rejects_bad_rows():
    module = _load_module()
    overlap = _row(
        today_open=8,
        foundation_yang=False,
        foundation_pose="站线上",
        ma_state="---",
        b1_turn_change=1,
    )
    frame = pd.DataFrame([
        overlap,
        _row(pre5_pct=-16, foundation_body=-4, unfinished=True),
        _row(pre5_pct=-16, foundation_body=-4, data_bad_gap=True),
        _row(),
    ])

    ledger = module.build_final_ledger(frame)

    assert len(ledger) == 1
    assert ledger.iloc[0]["rule_ids"] == "F3+F9"


def test_missing_values_do_not_hit_final_rules():
    module = _load_module()
    frame = pd.DataFrame([_row(pre5_pct=float("nan"), foundation_body=float("nan"))])

    masks = module.final_rule_masks(frame)

    assert not any(mask.iloc[0] for mask in masks.values())
