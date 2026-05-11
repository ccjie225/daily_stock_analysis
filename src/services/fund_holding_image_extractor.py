# -*- coding: utf-8 -*-
"""
基金个人持仓截图识别。

只负责从截图中提取可核对字段，不落库、不计算收益，避免 OCR 误识别直接
影响用户真实持仓数据。
"""

from __future__ import annotations

import base64
import json
import logging
import random
import re
import time
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from src.services import image_stock_extractor as image_extractor

logger = logging.getLogger(__name__)

ALLOWED_MIME = image_extractor.ALLOWED_MIME
MAX_SIZE_BYTES = image_extractor.MAX_SIZE_BYTES
VISION_API_TIMEOUT = image_extractor.VISION_API_TIMEOUT

FUND_HOLDING_EXTRACT_PROMPT = """请分析这张基金持仓截图，可能来自支付宝、天天基金、养基宝、腾讯理财通、雪球等平台。提取每只基金的个人持仓信息。

仅返回有效 JSON 数组，不要 markdown，不要解释。
每个元素为对象：
{
  "fund_code": "6位基金代码或 null",
  "fund_name": "基金名称或 null",
  "platform": "支付宝|天天基金|养基宝|腾讯理财通|雪球|未知",
  "holding_amount": "持有金额/市值，保留原始数字字符串或 null",
  "holding_share": "持有份额，保留原始数字字符串或 null",
  "cost_amount": "持仓成本/本金，保留原始数字字符串或 null",
  "cost_nav": "持仓成本净值/持仓成本价或 null",
  "latest_nav": "最新净值或 null",
  "holding_gain": "持有收益/累计盈亏，保留正负号或 null",
  "holding_gain_pct": "持有收益率，保留百分号或 null",
  "yesterday_gain": "昨日收益，保留正负号或 null",
  "currency": "CNY",
  "confidence": "high|medium|low"
}
注意：
- 不要把基金底层重仓股识别成我的基金持仓。
- 如果图中只有基金名称没有金额，也要返回名称，confidence 设为 low/medium。
- 金额、份额、收益率不要自行计算，只提取截图中可见内容。
- 没有基金持仓时返回 []。"""

_VALID_CONFIDENCE = frozenset({"high", "medium", "low"})
_SUPPORTED_PLATFORMS = frozenset({"支付宝", "天天基金", "养基宝", "腾讯理财通", "雪球", "未知"})
_ITEM_FIELDS = (
    "fund_code",
    "fund_name",
    "platform",
    "holding_amount",
    "holding_share",
    "cost_amount",
    "cost_nav",
    "latest_nav",
    "holding_gain",
    "holding_gain_pct",
    "yesterday_gain",
    "currency",
    "confidence",
)
_NON_NEGATIVE_FIELDS = frozenset(
    {"holding_amount", "holding_share", "cost_amount", "cost_nav", "latest_nav"}
)
_OPTIONAL_NEGATIVE_FIELDS = frozenset({"holding_gain", "holding_gain_pct", "yesterday_gain"})
_FIELD_LABELS = {
    "holding_amount": "持有金额",
    "holding_share": "持有份额",
    "cost_amount": "持仓成本",
    "cost_nav": "成本净值",
    "latest_nav": "最新净值",
    "holding_gain": "持有收益",
    "holding_gain_pct": "持有收益率",
    "yesterday_gain": "昨日收益",
}


def _strip_json_fence(text: str) -> str:
    cleaned = text.strip()
    for start in ("```json", "```"):
        if cleaned.startswith(start):
            cleaned = cleaned[len(start) :].strip()
            break
    end_idx = cleaned.rfind("```")
    if end_idx >= 0:
        cleaned = cleaned[:end_idx].strip()
    return cleaned


def _load_json_response(text: str) -> Any:
    cleaned = _strip_json_fence(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        try:
            from json_repair import repair_json

            return repair_json(cleaned, return_objects=True)
        except Exception as exc:
            raise ValueError("Vision API 返回内容不是有效 JSON") from exc


def _normalize_fund_code(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text.lower() in {"null", "none", "n/a", "nan", "-"}:
        return None
    match = re.search(r"(?<!\d)(\d{6})(?!\d)", text)
    return match.group(1) if match else None


def _clean_text(raw: Any, max_len: int = 120) -> Optional[str]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text.lower() in {"null", "none", "n/a", "nan", "-"}:
        return None
    text = re.sub(r"\s+", " ", text)
    return text[:max_len]


def _normalize_confidence(raw: Any) -> str:
    text = _clean_text(raw, max_len=16)
    if text and text.lower() in _VALID_CONFIDENCE:
        return text.lower()
    return "medium"


def _normalize_platform(raw: Any, warnings: List[str]) -> str:
    text = _clean_text(raw, max_len=20) or "未知"
    if text in _SUPPORTED_PLATFORMS:
        return text
    warnings.append(f"平台识别为 {text}，已按未知处理")
    return "未知"


def _decimal_from_text(value: Optional[str]) -> Optional[Decimal]:
    if not value:
        return None
    # 只做校验用的 Decimal 解析，不参与金额计算。
    normalized = value.replace(",", "").replace("，", "").strip()
    normalized = re.sub(r"[¥￥元份%]", "", normalized)
    normalized = normalized.replace("+", "", 1)
    if any(unit in value for unit in ("万", "亿")):
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", normalized)
    if not match:
        return None
    try:
        return Decimal(match.group(0))
    except InvalidOperation:
        return None


def _collect_numeric_warnings(item: Dict[str, Optional[str]], warnings: List[str]) -> None:
    for field in _NON_NEGATIVE_FIELDS | _OPTIONAL_NEGATIVE_FIELDS:
        value = item.get(field)
        if not value:
            continue
        if len(value) > 64:
            warnings.append(f"{_FIELD_LABELS[field]}字段过长，请人工核对")
            continue
        parsed = _decimal_from_text(value)
        if parsed is None:
            continue
        if field in _NON_NEGATIVE_FIELDS and parsed < Decimal("0"):
            warnings.append(f"{_FIELD_LABELS[field]}不应为负数，请核对截图识别结果")
        if field in {"holding_amount", "holding_share"} and parsed == Decimal("0"):
            warnings.append(f"{_FIELD_LABELS[field]}识别为 0，请核对是否误识别")


def _normalize_item(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    warnings: List[str] = []
    normalized: Dict[str, Any] = {field: None for field in _ITEM_FIELDS}
    normalized["fund_code"] = _normalize_fund_code(raw.get("fund_code") or raw.get("code"))
    normalized["fund_name"] = _clean_text(raw.get("fund_name") or raw.get("name"))
    normalized["platform"] = _normalize_platform(raw.get("platform"), warnings)
    normalized["currency"] = "CNY"
    normalized["confidence"] = _normalize_confidence(raw.get("confidence"))

    for field in (
        "holding_amount",
        "holding_share",
        "cost_amount",
        "cost_nav",
        "latest_nav",
        "holding_gain",
        "holding_gain_pct",
        "yesterday_gain",
    ):
        normalized[field] = _clean_text(raw.get(field), max_len=80)

    raw_currency = _clean_text(raw.get("currency"), max_len=12)
    if raw_currency and raw_currency.upper() not in {"CNY", "RMB", "人民币"}:
        warnings.append(f"币种识别为 {raw_currency}，当前仅按 CNY 预览")

    if not normalized["fund_code"] and not normalized["fund_name"]:
        return None
    if (
        not normalized["holding_amount"]
        and not normalized["holding_share"]
        and not normalized["cost_amount"]
        and not normalized["holding_gain"]
        and not normalized["holding_gain_pct"]
    ):
        warnings.append("未识别到金额、份额或收益字段，只能作为候选基金名称核对")

    _collect_numeric_warnings(normalized, warnings)
    normalized["warnings"] = warnings
    return normalized


def _parse_items_from_text(text: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    payload = _load_json_response(text)
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        payload = payload["items"]
    if not isinstance(payload, list):
        raise ValueError("Vision API 返回 JSON 不是数组")

    items: List[Dict[str, Any]] = []
    warnings: List[str] = []
    seen: set[tuple[str, str, str]] = set()
    for raw in payload:
        if not isinstance(raw, dict):
            warnings.append("忽略了非对象格式的识别结果")
            continue
        item = _normalize_item(raw)
        if not item:
            warnings.append("忽略了缺少基金代码和基金名称的识别结果")
            continue
        key = (
            item.get("fund_code") or "",
            item.get("fund_name") or "",
            item.get("platform") or "",
        )
        if key in seen:
            continue
        seen.add(key)
        items.append(item)

    if not items and not warnings:
        warnings.append("未识别到个人基金持仓")
    return items, warnings


def _call_litellm_fund_vision(
    image_b64: str,
    mime_type: str,
    api_key: Optional[str] = None,
) -> str:
    cfg = image_extractor.get_config()
    model = image_extractor._resolve_vision_model()
    if not model:
        raise ValueError("未配置 Vision API。请设置 LITELLM_MODEL 或相关 API Key。")

    keys = image_extractor._get_api_keys_for_model(model, cfg)
    if not keys:
        raise ValueError(f"No API key found for vision model {model}")
    key = api_key if api_key and api_key in keys else random.choice(keys)

    data_url = f"data:{mime_type};base64,{image_b64}"
    call_kwargs: dict = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": FUND_HOLDING_EXTRACT_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "max_tokens": 2048,
        "api_key": key,
        "timeout": VISION_API_TIMEOUT,
    }
    if not model.startswith("gemini/") and not model.startswith("anthropic/") and not model.startswith("vertex_ai/"):
        if cfg.openai_base_url:
            call_kwargs["api_base"] = cfg.openai_base_url
        if cfg.openai_base_url and "aihubmix.com" in cfg.openai_base_url:
            call_kwargs["extra_headers"] = {"APP-Code": "GPIJ3886"}

    if getattr(image_extractor.litellm, "completion", None) is None:
        import litellm as litellm_module

        image_extractor.litellm = litellm_module

    response = image_extractor.litellm.completion(**call_kwargs)
    if response and response.choices and response.choices[0].message.content:
        return response.choices[0].message.content
    raise ValueError("LiteLLM vision returned empty response")


def extract_fund_holdings_from_image(
    image_bytes: bytes,
    mime_type: str,
) -> Tuple[List[Dict[str, Any]], str, List[str]]:
    """
    从图片中提取个人基金持仓字段。

    Returns:
        (items, raw_text, warnings)
    """
    mime_type = (mime_type or "image/jpeg").strip().lower().split(";")[0].strip()
    if mime_type not in ALLOWED_MIME:
        raise ValueError(f"不支持的图片类型: {mime_type}。允许: {list(ALLOWED_MIME)}")
    if not image_bytes:
        raise ValueError("图片内容为空")
    if len(image_bytes) > MAX_SIZE_BYTES:
        raise ValueError(f"Image too large (max {MAX_SIZE_BYTES // (1024 * 1024)}MB)")

    image_extractor._verify_image_magic_bytes(image_bytes, mime_type)

    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    model = image_extractor._resolve_vision_model()
    keys = image_extractor._get_api_keys_for_model(model, image_extractor.get_config())

    last_error: Optional[Exception] = None
    for attempt in range(3):
        try:
            key = random.choice(keys) if keys else None
            raw = _call_litellm_fund_vision(image_b64, mime_type, api_key=key)
            logger.debug("[FundHoldingImageExtractor] raw LLM response:\n%s", raw)
            items, warnings = _parse_items_from_text(raw)
            logger.info("[FundHoldingImageExtractor] %s 提取 %d 个个人基金持仓", model, len(items))
            return items, raw, warnings
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                delay = 2 ** attempt
                logger.warning(
                    "[FundHoldingImageExtractor] 尝试 %s/3 失败，%ss 后重试: %s",
                    attempt + 1,
                    delay,
                    exc,
                )
                time.sleep(delay)

    raise ValueError(f"Vision API 调用失败，请检查 API Key 与网络: {last_error}") from last_error
