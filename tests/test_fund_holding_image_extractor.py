# -*- coding: utf-8 -*-
"""Tests for personal fund holding screenshot extraction."""

import sys
from unittest.mock import MagicMock, patch

if "litellm" not in sys.modules:
    sys.modules["litellm"] = MagicMock()
for _stub in ("google.generativeai", "google.genai", "anthropic"):
    if _stub not in sys.modules:
        sys.modules[_stub] = MagicMock()

import pytest

from src.config import Config
from src.services.fund_holding_image_extractor import (
    VISION_API_TIMEOUT,
    _call_litellm_fund_vision,
    _parse_items_from_text,
    extract_fund_holdings_from_image,
)

_GEMINI_KEY = "sk-gemini-testkey-1234"


def _cfg(**kwargs) -> Config:
    defaults = dict(
        stock_list=["600519"],
        tushare_token=None,
        llm_model_list=[],
        llm_channels=[],
        litellm_config_path=None,
        litellm_model="",
        litellm_fallback_models=[],
        vision_model="",
        vision_provider_priority="gemini,anthropic,openai",
        gemini_api_keys=[_GEMINI_KEY],
        gemini_model="gemini-3.1-pro-preview",
        anthropic_api_keys=[],
        anthropic_model="claude-sonnet-4-6",
        openai_api_keys=[],
        openai_model="gpt-5.5",
        openai_base_url=None,
        openai_vision_model=None,
        deepseek_api_keys=[],
        config_validate_mode="warn",
    )
    defaults.update(kwargs)
    return Config(**defaults)


def _make_jpeg_bytes() -> bytes:
    return b"\xff\xd8\xff" + b"\x00" * 20


def _good_response(content: str) -> MagicMock:
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def test_parse_fund_holding_items_keeps_money_as_strings():
    raw = """
    ```json
    [
      {
        "fund_code": "005918",
        "fund_name": "天弘沪深300ETF联接C",
        "platform": "支付宝",
        "holding_amount": "1,234.56",
        "holding_share": "987.65",
        "cost_amount": "1200.00",
        "cost_nav": "1.2160",
        "latest_nav": "1.2500",
        "holding_gain": "+34.56",
        "holding_gain_pct": "+2.88%",
        "yesterday_gain": "-1.23",
        "currency": "CNY",
        "confidence": "high"
      }
    ]
    ```
    """
    items, warnings = _parse_items_from_text(raw)

    assert warnings == []
    assert items[0]["fund_code"] == "005918"
    assert items[0]["holding_amount"] == "1,234.56"
    assert items[0]["holding_share"] == "987.65"
    assert items[0]["holding_gain_pct"] == "+2.88%"
    assert items[0]["confidence"] == "high"


def test_parse_fund_holding_items_normalizes_warnings():
    raw = """
    [
      {
        "fund_code": "基金代码: 110011",
        "fund_name": "易方达中小盘混合",
        "platform": "其他平台",
        "holding_amount": "-10.00",
        "holding_share": "0",
        "currency": "USD",
        "confidence": "bad-value"
      },
      {"stock_code": "600519", "stock_name": "贵州茅台"}
    ]
    """
    items, warnings = _parse_items_from_text(raw)

    assert len(items) == 1
    assert items[0]["fund_code"] == "110011"
    assert items[0]["platform"] == "未知"
    assert items[0]["confidence"] == "medium"
    assert any("平台识别" in w for w in items[0]["warnings"])
    assert any("不应为负数" in w for w in items[0]["warnings"])
    assert any("识别为 0" in w for w in items[0]["warnings"])
    assert any("币种识别" in w for w in items[0]["warnings"])
    assert any("忽略了缺少基金代码和基金名称" in w for w in warnings)


def test_call_litellm_fund_vision_uses_fund_prompt():
    cfg = _cfg()
    with patch("src.services.image_stock_extractor.get_config", return_value=cfg), patch(
        "src.services.image_stock_extractor.litellm.completion",
        return_value=_good_response("[]"),
    ) as mock_comp:
        assert _call_litellm_fund_vision("base64data", "image/jpeg") == "[]"

    kwargs = mock_comp.call_args[1]
    prompt = kwargs["messages"][0]["content"][0]["text"]
    assert "基金持仓截图" in prompt
    assert "不要把基金底层重仓股识别成我的基金持仓" in prompt
    assert kwargs["timeout"] == VISION_API_TIMEOUT
    assert kwargs["max_tokens"] == 2048


def test_extract_fund_holdings_from_image_returns_items_and_raw():
    raw = '[{"fund_code":"005918","fund_name":"天弘沪深300ETF联接C","platform":"支付宝","holding_amount":"100.00","confidence":"high"}]'
    cfg = _cfg()
    with patch("src.services.image_stock_extractor.get_config", return_value=cfg), patch(
        "src.services.image_stock_extractor.litellm.completion",
        return_value=_good_response(raw),
    ):
        items, raw_text, warnings = extract_fund_holdings_from_image(_make_jpeg_bytes(), "image/jpeg")

    assert raw_text == raw
    assert warnings == []
    assert items[0]["fund_code"] == "005918"
    assert items[0]["holding_amount"] == "100.00"


def test_extract_fund_holdings_from_image_rejects_wrong_magic_bytes():
    with pytest.raises(ValueError):
        extract_fund_holdings_from_image(b"\x00\x00\x00" + b"\x00" * 20, "image/jpeg")
