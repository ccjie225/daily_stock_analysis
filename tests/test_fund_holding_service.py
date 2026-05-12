# -*- coding: utf-8 -*-
"""Tests for personal fund holding persistence."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

if "fake_useragent" not in sys.modules:
    fake_useragent = MagicMock()
    fake_useragent.UserAgent.return_value.random = "pytest-agent"
    sys.modules["fake_useragent"] = fake_useragent

from src.config import Config
from src.services.fund_holding_service import FundHoldingService
from src.storage import DatabaseManager


class FundHoldingServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "fund_holding_test.db"
        os.environ["DATABASE_PATH"] = str(self.db_path)
        Config.reset_instance()
        DatabaseManager.reset_instance()
        self.service = FundHoldingService()

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        os.environ.pop("DATABASE_PATH", None)
        self.temp_dir.cleanup()

    def test_save_and_list_keeps_money_fields_as_strings(self) -> None:
        result = self.service.save_imported_holdings([
            {
                "fund_code": "005918",
                "fund_name": "天弘沪深300ETF联接C",
                "platform": "支付宝",
                "holding_amount": "1,234.56",
                "holding_share": "987.65",
                "cost_amount": "1200.00",
                "holding_gain": "+34.56",
                "holding_gain_pct": "+2.88%",
                "currency": "CNY",
                "confidence": "high",
                "warnings": ["人工核对"],
            }
        ])

        self.assertEqual(result["saved_count"], 1)
        saved = self.service.list_holdings()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["fund_code"], "005918")
        self.assertEqual(saved[0]["holding_amount"], "1,234.56")
        self.assertEqual(saved[0]["holding_share"], "987.65")
        self.assertEqual(saved[0]["holding_gain_pct"], "+2.88%")
        self.assertEqual(saved[0]["warnings"], ["人工核对"])

    def test_save_same_fund_platform_updates_existing_row(self) -> None:
        payload = {
            "fund_code": "005918",
            "fund_name": "天弘沪深300ETF联接C",
            "platform": "支付宝",
            "holding_amount": "100.00",
            "currency": "CNY",
            "confidence": "medium",
            "warnings": [],
        }
        first = self.service.save_imported_holdings([payload])
        second = self.service.save_imported_holdings([{**payload, "holding_amount": "200.00"}])

        self.assertEqual(first["items"][0]["id"], second["items"][0]["id"])
        saved = self.service.list_holdings()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["holding_amount"], "200.00")

    def test_save_same_fund_code_updates_when_name_changes(self) -> None:
        first = self.service.save_imported_holdings([
            {
                "fund_code": "005918",
                "fund_name": "天弘沪深300ETF联接C",
                "platform": "支付宝",
                "holding_amount": "100.00",
                "currency": "CNY",
                "confidence": "medium",
                "warnings": [],
            }
        ])
        second = self.service.save_imported_holdings([
            {
                "fund_code": "005918",
                "fund_name": "天弘沪深300指数C",
                "platform": "支付宝",
                "holding_amount": "210.00",
                "currency": "CNY",
                "confidence": "medium",
                "warnings": [],
            }
        ])

        self.assertEqual(first["items"][0]["id"], second["items"][0]["id"])
        saved = self.service.list_holdings()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["fund_name"], "天弘沪深300指数C")
        self.assertEqual(saved[0]["holding_amount"], "210.00")

    def test_save_code_backfills_existing_name_only_row(self) -> None:
        first = self.service.save_imported_holdings([
            {
                "fund_name": "易方达沪深300ETF联接A",
                "platform": "支付宝",
                "holding_amount": "100.00",
                "currency": "CNY",
                "confidence": "medium",
                "warnings": [],
            }
        ])
        second = self.service.save_imported_holdings([
            {
                "fund_code": "110020",
                "fund_name": "易方达沪深300ETF联接A",
                "platform": "支付宝",
                "holding_amount": "100.00",
                "currency": "CNY",
                "confidence": "medium",
                "warnings": [],
            }
        ])

        self.assertEqual(first["items"][0]["id"], second["items"][0]["id"])
        saved = self.service.list_holdings()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["fund_code"], "110020")

    def test_rejects_negative_non_negative_fields(self) -> None:
        with self.assertRaises(ValueError):
            self.service.save_imported_holdings([
                {
                    "fund_code": "005918",
                    "platform": "支付宝",
                    "holding_amount": "-1.00",
                    "currency": "CNY",
                    "confidence": "high",
                    "warnings": [],
                }
            ])


if __name__ == "__main__":
    unittest.main()
