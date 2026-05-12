# -*- coding: utf-8 -*-
"""Tests for fund holding valuation alignment review."""

import unittest

from src.services.fund_holding_review_service import FundHoldingReviewService


class StubHoldingService:
    def __init__(self, rows):
        self.rows = rows

    def list_holdings(self, limit=50):
        return self.rows[:limit]


class StubFundService:
    def resolve_fund_by_name(self, fund_name):
        if fund_name == "测试沪深300联接C":
            return {
                "fund_code": "005918",
                "fund_name": "测试沪深300联接C",
                "match_type": "exact",
            }
        return None

    def analyze_fund(self, fund_code, days=365):
        return {
            "profile": {"fund_code": fund_code, "fund_name": "测试沪深300联接C"},
            "latest_nav": {"date": "2026-05-11", "unit_nav": 1.25, "daily_return_pct": 0.8},
            "returns": {"one_year_pct": 12.34},
            "risk": {"risk_level": "medium", "max_drawdown_pct": -12.5},
            "reference_valuation": {"pe_percentile": 45.0, "pb_percentile": 35.0},
            "label": "候选",
            "reasons": ["回撤可控"],
            "risks": ["跟踪指数波动"],
            "evidence_gaps": [],
        }


class FundHoldingReviewServiceTestCase(unittest.TestCase):
    def test_review_aligns_holding_with_latest_nav(self):
        service = FundHoldingReviewService(
            holding_service=StubHoldingService([
                {
                    "id": 1,
                    "fund_code": "005918",
                    "fund_name": "测试基金",
                    "platform": "支付宝",
                    "holding_amount": "1200.00",
                    "holding_share": "1000",
                    "cost_amount": "1000",
                    "cost_nav": "1.0000",
                    "latest_nav": "1.2000",
                    "holding_gain": "200.00",
                    "holding_gain_pct": "20.00%",
                    "yesterday_gain": None,
                    "currency": "CNY",
                    "confidence": "high",
                    "source": "screenshot",
                    "warnings": [],
                    "created_at": "2026-05-11T10:00:00",
                    "updated_at": "2026-05-11T10:00:00",
                }
            ]),
            fund_service=StubFundService(),
        )

        result = service.review_holdings(use_ai=False)

        self.assertEqual(result["summary"]["item_count"], 1)
        self.assertEqual(result["summary"]["priced_count"], 1)
        self.assertEqual(result["summary"]["total_estimated_market_value"], "1250.00")
        self.assertEqual(result["summary"]["total_value_change_from_saved"], "+50.00")
        self.assertEqual(result["summary"]["total_estimated_gain"], "+250.00")
        item = result["items"][0]
        self.assertEqual(item["latest_public_nav"], "1.2500")
        self.assertEqual(item["estimated_market_value"], "1250.00")
        self.assertEqual(item["value_change_from_saved"], "+50.00")
        self.assertEqual(item["estimated_gain"], "+250.00")
        self.assertEqual(item["estimated_gain_pct"], "+25.00%")
        self.assertEqual(item["analysis_label"], "候选")
        self.assertIn("公开数据评价偏正面", item["advice"])

    def test_review_marks_missing_position_fields(self):
        service = FundHoldingReviewService(
            holding_service=StubHoldingService([
                {
                    "id": 2,
                    "fund_code": "005918",
                    "fund_name": "测试基金",
                    "platform": "支付宝",
                    "holding_amount": None,
                    "holding_share": None,
                    "cost_amount": None,
                    "currency": "CNY",
                    "confidence": "medium",
                    "source": "screenshot",
                    "warnings": [],
                }
            ]),
            fund_service=StubFundService(),
        )

        item = service.review_holdings()["items"][0]

        self.assertEqual(item["data_status"], "missing_position_fields")
        self.assertIsNone(item["estimated_market_value"])
        self.assertTrue(any("缺少持有份额" in gap for gap in item["evidence_gaps"]))

    def test_review_resolves_missing_code_by_fund_name(self):
        service = FundHoldingReviewService(
            holding_service=StubHoldingService([
                {
                    "id": 3,
                    "fund_code": None,
                    "fund_name": "测试沪深300联接C",
                    "platform": "支付宝",
                    "holding_amount": "1200.00",
                    "holding_share": "1000",
                    "cost_amount": "1000",
                    "currency": "CNY",
                    "confidence": "medium",
                    "source": "screenshot",
                    "warnings": [],
                }
            ]),
            fund_service=StubFundService(),
        )

        item = service.review_holdings()["items"][0]

        self.assertEqual(item["fund_code"], "005918")
        self.assertEqual(item["data_status"], "priced")
        self.assertEqual(item["estimated_market_value"], "1250.00")
        self.assertTrue(any("自动匹配到 005918" in reason for reason in item["reasons"]))


if __name__ == "__main__":
    unittest.main()
