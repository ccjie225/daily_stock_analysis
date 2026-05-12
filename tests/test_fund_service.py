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

        def fund_individual_analysis_xq(symbol):
            self.assertEqual(symbol, "005918")
            return pd.DataFrame([{
                "周期": "近1年",
                "较同类风险收益比": 82,
                "较同类抗风险波动": 65,
                "年化波动率": 12.34,
                "年化夏普比率": 1.23,
                "最大回撤": 8.9,
            }])

        def fund_individual_detail_info_xq(symbol):
            self.assertEqual(symbol, "005918")
            return pd.DataFrame([
                {"费用类型": "其他费用", "条件或名称": "基金管理费", "费用": 0.5},
                {"费用类型": "其他费用", "条件或名称": "基金托管费", "费用": 0.1},
                {"费用类型": "其他费用", "条件或名称": "销售服务费", "费用": 0.2},
                {"费用类型": "卖出规则", "条件或名称": "0.0天<持有期限<7.0天", "费用": 1.5},
            ])

        def fund_portfolio_hold_em(symbol, date):
            self.assertEqual(symbol, "005918")
            self.assertTrue(date)
            return pd.DataFrame([
                {"股票代码": "600519", "股票名称": "贵州茅台", "占净值比例": 6.5, "持股数": 1.2, "持仓市值": 1000, "季度": "2026年1季度股票投资明细"},
                {"股票代码": "300750", "股票名称": "宁德时代", "占净值比例": 5.1, "持股数": 2.3, "持仓市值": 800, "季度": "2026年1季度股票投资明细"},
            ])

        def fund_portfolio_industry_allocation_em(symbol, date):
            self.assertEqual(symbol, "005918")
            self.assertTrue(date)
            return pd.DataFrame([
                {"行业类别": "制造业", "占净值比例": 28.2, "市值": 3500, "截止时间": "2026-03-31"},
                {"行业类别": "金融业", "占净值比例": 12.4, "市值": 1200, "截止时间": "2026-03-31"},
            ])

        def stock_index_pe_lg(symbol):
            self.assertEqual(symbol, "沪深300")
            return pd.DataFrame([
                {"日期": "2026-01-01", "滚动市盈率": 10},
                {"日期": "2026-01-02", "滚动市盈率": 12},
                {"日期": "2026-01-03", "滚动市盈率": 11},
            ])

        def stock_index_pb_lg(symbol):
            self.assertEqual(symbol, "沪深300")
            return pd.DataFrame([
                {"日期": "2026-01-01", "市净率": 1.1},
                {"日期": "2026-01-02", "市净率": 1.2},
                {"日期": "2026-01-03", "市净率": 1.15},
            ])

        module.fund_open_fund_info_em = fund_open_fund_info_em
        module.fund_open_fund_daily_em = fund_open_fund_daily_em
        module.fund_individual_basic_info_xq = fund_individual_basic_info_xq
        module.fund_individual_analysis_xq = fund_individual_analysis_xq
        module.fund_individual_detail_info_xq = fund_individual_detail_info_xq
        module.fund_portfolio_hold_em = fund_portfolio_hold_em
        module.fund_portfolio_industry_allocation_em = fund_portfolio_industry_allocation_em
        module.stock_index_pe_lg = stock_index_pe_lg
        module.stock_index_pb_lg = stock_index_pb_lg
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
        self.assertEqual(result["reference_valuation"]["reference_name"], None)
        self.assertEqual(result["peer_analysis"]["risk_return_score"], 82.0)
        self.assertEqual(result["holdings"][0]["stock_name"], "贵州茅台")
        self.assertEqual(result["industry_allocation"][0]["industry"], "制造业")
        self.assertEqual(result["fees"]["management_fee_pct"], 0.5)
        self.assertEqual(result["fees"]["items"][0]["fee_text"], "0.50%")
        self.assertIn(result["label"], {"候选", "观察"})
        self.assertTrue(result["reasons"])
        self.assertTrue(result["nav"])

    def test_reference_valuation_for_index_fund(self):
        fake = self._fake_akshare()

        def fund_open_fund_daily_em():
            return pd.DataFrame([{
                "基金代码": "005918",
                "基金简称": "天弘沪深300ETF联接C",
                "基金类型": "指数型",
            }])

        fake.fund_open_fund_daily_em = fund_open_fund_daily_em
        with patch.dict(sys.modules, {"akshare": fake}):
            result = FundService().analyze_fund("005918", days=120)

        self.assertEqual(result["reference_valuation"]["reference_name"], "沪深300")
        self.assertEqual(result["reference_valuation"]["pe_ttm"], 11.0)
        self.assertEqual(result["reference_valuation"]["pb"], 1.15)

    def test_resolve_fund_by_name(self):
        fake = self._fake_akshare()

        def fund_open_fund_daily_em():
            return pd.DataFrame([
                {"基金代码": "110020", "基金简称": "易方达沪深300ETF联接A", "基金类型": "指数型"},
                {"基金代码": "005918", "基金简称": "天弘沪深300ETF联接C", "基金类型": "指数型"},
            ])

        fake.fund_open_fund_daily_em = fund_open_fund_daily_em
        with patch.dict(sys.modules, {"akshare": fake}):
            match = FundService().resolve_fund_by_name("易方达沪深300ETF联接A")

        self.assertIsNotNone(match)
        self.assertEqual(match["fund_code"], "110020")
        self.assertEqual(match["match_type"], "exact")

    def test_resolve_fund_by_name_skips_ambiguous_share_classes(self):
        fake = self._fake_akshare()

        def fund_open_fund_daily_em():
            return pd.DataFrame([
                {"基金代码": "110020", "基金简称": "易方达沪深300ETF联接A", "基金类型": "指数型"},
                {"基金代码": "007339", "基金简称": "易方达沪深300ETF联接C", "基金类型": "指数型"},
            ])

        fake.fund_open_fund_daily_em = fund_open_fund_daily_em
        with patch.dict(sys.modules, {"akshare": fake}):
            match = FundService().resolve_fund_by_name("易方达沪深300ETF联接")

        self.assertIsNone(match)

    def test_invalid_fund_code_is_rejected(self):
        with self.assertRaises(ValueError):
            FundService().analyze_fund("abc")


if __name__ == "__main__":
    unittest.main()
