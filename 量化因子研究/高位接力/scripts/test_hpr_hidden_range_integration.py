"""同源数据集成验证；仅在 API 容器内显式开启，避免日常测试重复全量回放。"""

from __future__ import annotations

import os
import unittest
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

import hpr_hidden_range_research as research


@unittest.skipUnless(os.environ.get("HPR_RESEARCH_INTEGRATION") == "1", "仅研究容器显式执行")
class HiddenRangeIntegrationTest(unittest.TestCase):
    def test_dataset_matches_materialized_report_and_dec2024_cases(self):
        output = Path("/tmp/hpr_hidden_range_events.pkl")
        if os.environ.get("HPR_RESEARCH_REBUILD") == "1" or not output.exists():
            events = research.build_dataset(output)
        else:
            events = pd.read_pickle(output)
        engine = create_engine(os.environ["DATABASE_URL"])
        payload = pd.read_sql(text(
            "SELECT payload FROM hpr_backtest_runs WHERE id=(SELECT MAX(id) FROM hpr_backtest_runs)"),
            engine)["payload"].iloc[0]
        expected = payload["summary"]["dyn_sim"]
        actual = research.summarize(events[events["出手点"] != ""])
        self.assertEqual(actual["n"], expected["n"])
        self.assertAlmostEqual(actual["mean"], expected["e3_pct"], places=2)
        self.assertAlmostEqual(actual["win"], expected["e3_win"] * 100, places=1)

        case_keys = [("2024-12-13", "粤传媒"), ("2024-12-13", "李子园"),
                     ("2024-12-16", "北纬科技"), ("2024-12-24", "国星光电")]
        normalized_names = events["名称"].str.replace(" ", "", regex=False)
        cases = pd.concat([events[(events["买入日"] == day) & (normalized_names == name)]
                           for day, name in case_keys])
        self.assertEqual(cases["名称"].str.replace(" ", "", regex=False).tolist(),
                         ["粤传媒", "李子园", "北纬科技", "国星光电"])
        self.assertEqual(cases["出手点"].tolist(), ["B3", "K5", "C2", "C2"])
        self.assertTrue((cases["E3%"] < 0).all())
        self.assertTrue(output.exists())


if __name__ == "__main__":
    unittest.main()
