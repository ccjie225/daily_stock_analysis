# -*- coding: utf-8 -*-

import sys
import types
import unittest
from datetime import date, timedelta
from unittest.mock import patch

import pandas as pd

from src.services.fund_service import FundService


class TestFundService(unittest.TestCase):
    def setUp(self):
        FundService._get_latest_open_fund_map.cache_clear()

    def _fake_akshare(self):
        module = types.SimpleNamespace()

        def fund_open_fund_info_em(**_kwargs):
            start = date(2026, 1, 1)
            rows = []
            nav = 1.0
            for index in range(120):
                nav *= 1.0015
                rows.append({
                    "净值日期": (start + timedelta(days=index)).isoformat(),
                    "单位净值": round(nav, 4),
                    "累计净值": round(nav + 0.15, 4),
                    "日增长率": 0.15,
                })
            return pd.DataFrame(rows)

        def fund_open_fund_daily_em():
            return pd.DataFrame([{
                "基金代码": "005918",
                "基金简称": "测试成长混合",
                "基金类型": "混合型",
            }])

        def fund_individual_basic_info_xq(symbol):
            self.assertEqual(symbol, "005918")
            return pd.DataFrame([
                {"项目": "基金经理", "内容": "张三"},
                {"项目": "基金规模", "内容": "35.20亿元"},
                {"项目": "成立日期", "内容": "2018-01-01"},
                {"项目": "基金托管人", "内容": "测试银行"},
            ])

        module.fund_open_fund_info_em = fund_open_fund_info_em
        module.fund_open_fund_daily_em = fund_open_fund_daily_em
        module.fund_individual_basic_info_xq = fund_individual_basic_info_xq
        return module

    def test_analyze_fund_builds_profile_and_metrics(self):
        with patch.dict(sys.modules, {"akshare": self._fake_akshare()}):
            result = FundService().analyze_fund("005918", days=120)

        self.assertEqual(result["profile"]["fund_code"], "005918")
        self.assertEqual(result["profile"]["fund_name"], "测试成长混合")
        self.assertEqual(result["profile"]["fund_type"], "混合型")
        self.assertEqual(result["profile"]["manager"], "张三")
        self.assertEqual(result["latest_nav"]["date"], "2026-04-30")
        self.assertGreater(result["returns"]["one_month_pct"], 0)
        self.assertGreater(result["returns"]["three_month_pct"], 0)
        self.assertIn(result["label"], {"候选", "观察"})
        self.assertTrue(result["reasons"])
        self.assertTrue(result["nav"])

    def test_invalid_fund_code_is_rejected(self):
        with self.assertRaises(ValueError):
            FundService().analyze_fund("abc")


if __name__ == "__main__":
    unittest.main()
