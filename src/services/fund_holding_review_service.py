# -*- coding: utf-8 -*-
"""Review saved offsite fund holdings against latest public fund data."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from src.services.fund_holding_service import FundHoldingService
from src.services.fund_service import FundNotFoundError, FundService, FundServiceError

logger = logging.getLogger(__name__)

_MONEY_QUANT = Decimal("0.01")
_NAV_QUANT = Decimal("0.0001")
_PCT_QUANT = Decimal("0.01")
_SHARE_QUANT = Decimal("0.0001")


class FundHoldingReviewService:
    """Build position-level valuation alignment and holding suggestions."""

    def __init__(
        self,
        holding_service: Optional[FundHoldingService] = None,
        fund_service: Optional[FundService] = None,
    ) -> None:
        self.holding_service = holding_service or FundHoldingService()
        self.fund_service = fund_service or FundService()

    def review_holdings(self, *, limit: int = 50, use_ai: bool = False) -> Dict[str, Any]:
        safe_limit = max(1, min(int(limit or 50), 100))
        holdings = self.holding_service.list_holdings(limit=safe_limit)
        items = [self._review_one(item) for item in holdings]
        summary = self._build_summary(items)
        ai_summary = None
        ai_error = None

        if use_ai and items:
            ai_summary, ai_error = self._build_ai_summary(items, summary)

        return {
            "generated_at": datetime.now().isoformat(),
            "items": items,
            "summary": {
                **summary,
                "ai_summary": ai_summary,
                "ai_enabled": bool(ai_summary),
                "ai_error": ai_error,
                "source_notes": [
                    "场外基金无股票式逐笔实时价；本页使用最新公开净值/最近交易日净值做持仓对齐。",
                    "截图字段和估算字段均为展示与研究用途，暂不写回真实交易流水。",
                ],
            },
        }

    def _review_one(self, holding: Dict[str, Any]) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            **holding,
            "latest_public_nav": None,
            "latest_nav_date": None,
            "latest_daily_return_pct": None,
            "estimated_market_value": None,
            "value_change_from_saved": None,
            "estimated_gain": None,
            "estimated_gain_pct": None,
            "inferred_holding_share": None,
            "inferred_cost_amount": None,
            "valuation_basis": [],
            "analysis_label": "信息不足",
            "risk_level": "unknown",
            "advice": "缺少基金代码或公开净值数据，先补齐识别结果后再做持仓判断。",
            "reasons": [],
            "risks": [],
            "evidence_gaps": [],
            "data_status": "missing_fund_code",
        }

        fund_code = holding.get("fund_code")
        matched_by_name = None
        if not fund_code:
            matched_by_name = self._resolve_missing_fund_code(holding)
            if matched_by_name:
                fund_code = matched_by_name["fund_code"]
                result["fund_code"] = fund_code
                result["fund_name"] = holding.get("fund_name") or matched_by_name.get("fund_name")
                result["data_status"] = "matched_by_name"
            else:
                result["evidence_gaps"].append("缺少基金代码，且未能通过基金名称唯一匹配公开基金代码")
                return result

        try:
            analysis = self.fund_service.analyze_fund(str(fund_code), days=365)
        except (FundNotFoundError, FundServiceError, ValueError) as exc:
            result["data_status"] = "fund_data_unavailable"
            result["advice"] = "公开基金数据暂不可用，先保留原始截图持仓，稍后再刷新净值对齐。"
            result["evidence_gaps"].append(str(exc))
            return result
        except Exception as exc:
            logger.warning("基金 %s 持仓复盘失败: %s", fund_code, exc, exc_info=True)
            result["data_status"] = "fund_data_error"
            result["advice"] = "基金持仓复盘失败，先不要使用该条估算结果。"
            result["evidence_gaps"].append("基金公开数据分析异常")
            return result

        latest_nav = analysis.get("latest_nav") or {}
        risk = analysis.get("risk") or {}
        returns = analysis.get("returns") or {}
        reference_valuation = analysis.get("reference_valuation") or {}
        latest_nav_dec = self._decimal_from_any(latest_nav.get("unit_nav"))
        latest_return_dec = self._decimal_from_any(latest_nav.get("daily_return_pct"))
        holding_share = self._decimal_from_text(holding.get("holding_share"))
        saved_amount = self._decimal_from_text(holding.get("holding_amount"))
        cost_amount = self._decimal_from_text(holding.get("cost_amount"))
        cost_nav = self._decimal_from_text(holding.get("cost_nav"))
        snapshot_nav = self._decimal_from_text(holding.get("latest_nav"))
        holding_gain = self._decimal_from_text(holding.get("holding_gain"))
        holding_gain_pct = self._decimal_from_text(holding.get("holding_gain_pct"))
        inferred_share = None
        inferred_cost_amount = None
        valuation_basis: List[str] = []

        share_nav = snapshot_nav if snapshot_nav is not None and snapshot_nav > 0 else latest_nav_dec
        share_nav_label = "截图净值" if snapshot_nav is not None and snapshot_nav > 0 else "最新公开净值"
        if holding_share is None and share_nav is not None and share_nav > 0:
            derived_market_value, share_basis = self._derive_market_value_for_share(
                saved_amount=saved_amount,
                cost_amount=cost_amount,
                holding_gain=holding_gain,
                holding_gain_pct=holding_gain_pct,
            )
            if derived_market_value is not None and derived_market_value >= 0:
                holding_share = derived_market_value / share_nav
                inferred_share = holding_share
                valuation_basis.append(f"未识别持有份额，按 {share_basis} ÷ {share_nav_label} 反推份额")

        if cost_amount is None and cost_nav is not None and holding_share is not None:
            cost_amount = cost_nav * holding_share
            inferred_cost_amount = cost_amount
            valuation_basis.append("未识别持仓成本，按成本净值 × 份额反推成本")

        estimated_market_value = (
            holding_share * latest_nav_dec
            if holding_share is not None and latest_nav_dec is not None
            else None
        )
        if cost_amount is None:
            cost_amount, cost_basis = self._derive_cost_amount(
                estimated_market_value=estimated_market_value,
                saved_amount=saved_amount,
                holding_gain=holding_gain,
                holding_gain_pct=holding_gain_pct,
            )
            if cost_amount is not None:
                inferred_cost_amount = cost_amount
                valuation_basis.append(f"未识别持仓成本，按 {cost_basis} 反推成本")

        value_change = (
            estimated_market_value - saved_amount
            if estimated_market_value is not None and saved_amount is not None
            else None
        )
        estimated_gain = (
            estimated_market_value - cost_amount
            if estimated_market_value is not None and cost_amount is not None
            else None
        )
        estimated_gain_pct = (
            estimated_gain / cost_amount * Decimal("100")
            if estimated_gain is not None and cost_amount is not None and cost_amount > 0
            else None
        )

        result.update({
            "fund_name": holding.get("fund_name") or (analysis.get("profile") or {}).get("fund_name"),
            "latest_public_nav": self._format_decimal(latest_nav_dec, _NAV_QUANT),
            "latest_nav_date": latest_nav.get("date"),
            "latest_daily_return_pct": self._format_pct(latest_return_dec),
            "estimated_market_value": self._format_decimal(estimated_market_value, _MONEY_QUANT),
            "value_change_from_saved": self._format_signed_decimal(value_change, _MONEY_QUANT),
            "estimated_gain": self._format_signed_decimal(estimated_gain, _MONEY_QUANT),
            "estimated_gain_pct": self._format_pct(estimated_gain_pct),
            "inferred_holding_share": self._format_decimal(inferred_share, _SHARE_QUANT),
            "inferred_cost_amount": self._format_decimal(inferred_cost_amount, _MONEY_QUANT),
            "valuation_basis": valuation_basis[:4],
            "analysis_label": analysis.get("label") or "信息不足",
            "risk_level": risk.get("risk_level") or "unknown",
            "data_status": "priced" if estimated_market_value is not None else "missing_position_fields",
        })

        gaps = list(analysis.get("evidence_gaps") or [])
        if holding_share is None:
            gaps.append("缺少持有份额，无法按最新净值估算当前市值")
        if cost_amount is None:
            gaps.append("缺少持仓成本，无法估算当前累计盈亏")

        result["reasons"] = self._build_reasons(analysis, returns, reference_valuation, result)
        if valuation_basis:
            result["reasons"].extend(valuation_basis)
            result["reasons"] = result["reasons"][:6]
        if matched_by_name:
            result["reasons"].insert(
                0,
                f"按基金名称自动匹配到 {matched_by_name['fund_code']}（{matched_by_name.get('fund_name') or '名称待确认'}），请核对 A/C 份额是否一致",
            )
            result["reasons"] = result["reasons"][:6]
        result["risks"] = list(analysis.get("risks") or [])[:4]
        result["evidence_gaps"] = gaps[:6]
        result["advice"] = self._build_rule_advice(result, risk, returns, reference_valuation)
        return result

    def _resolve_missing_fund_code(self, holding: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        fund_name = holding.get("fund_name")
        if not fund_name or not hasattr(self.fund_service, "resolve_fund_by_name"):
            return None
        try:
            return self.fund_service.resolve_fund_by_name(str(fund_name))
        except Exception as exc:
            logger.info("按基金名称匹配代码失败: %s", exc)
            return None

    @staticmethod
    def _derive_market_value_for_share(
        *,
        saved_amount: Optional[Decimal],
        cost_amount: Optional[Decimal],
        holding_gain: Optional[Decimal],
        holding_gain_pct: Optional[Decimal],
    ) -> tuple[Optional[Decimal], str]:
        if saved_amount is not None:
            return saved_amount, "持有金额"

        if cost_amount is not None and holding_gain is not None:
            return cost_amount + holding_gain, "持仓成本 + 持有收益"

        if cost_amount is not None and holding_gain_pct is not None:
            multiplier = Decimal("1") + holding_gain_pct / Decimal("100")
            if multiplier > 0:
                return cost_amount * multiplier, "持仓成本 × (1 + 收益率)"

        if holding_gain is not None and holding_gain_pct not in (None, Decimal("0")):
            cost = holding_gain / (holding_gain_pct / Decimal("100"))
            if cost > 0:
                return cost + holding_gain, "持有收益 ÷ 收益率反推市值"

        return None, "可用持仓字段"

    @staticmethod
    def _derive_cost_amount(
        *,
        estimated_market_value: Optional[Decimal],
        saved_amount: Optional[Decimal],
        holding_gain: Optional[Decimal],
        holding_gain_pct: Optional[Decimal],
    ) -> tuple[Optional[Decimal], str]:
        reference_market_value = estimated_market_value if estimated_market_value is not None else saved_amount
        if reference_market_value is not None and holding_gain is not None:
            cost_amount = reference_market_value - holding_gain
            if cost_amount >= 0:
                return cost_amount, "估算市值 - 持有收益"

        if reference_market_value is not None and holding_gain_pct is not None:
            denominator = Decimal("1") + holding_gain_pct / Decimal("100")
            if denominator > 0:
                return reference_market_value / denominator, "估算市值 ÷ (1 + 收益率)"

        return None, "可用收益字段"

    @staticmethod
    def _build_reasons(
        analysis: Dict[str, Any],
        returns: Dict[str, Any],
        valuation: Dict[str, Any],
        reviewed: Dict[str, Any],
    ) -> List[str]:
        reasons: List[str] = []
        if reviewed.get("latest_public_nav") and reviewed.get("latest_nav_date"):
            reasons.append(
                f"最新公开净值 {reviewed['latest_public_nav']}，日期 {reviewed['latest_nav_date']}"
            )
        one_year = returns.get("one_year_pct")
        if one_year is not None:
            reasons.append(f"近一年收益率约 {one_year:.2f}%")
        pe_pct = valuation.get("pe_percentile")
        pb_pct = valuation.get("pb_percentile")
        if pe_pct is not None or pb_pct is not None:
            parts = []
            if pe_pct is not None:
                parts.append(f"PE 分位 {pe_pct:.2f}%")
            if pb_pct is not None:
                parts.append(f"PB 分位 {pb_pct:.2f}%")
            reasons.append("参考估值：" + "，".join(parts))
        reasons.extend(str(item) for item in (analysis.get("reasons") or [])[:3])
        return reasons[:6]

    @staticmethod
    def _build_rule_advice(
        reviewed: Dict[str, Any],
        risk: Dict[str, Any],
        returns: Dict[str, Any],
        valuation: Dict[str, Any],
    ) -> str:
        if reviewed.get("data_status") != "priced":
            return "先补齐份额和成本字段，再做收益/仓位判断；当前只能作为基金名单跟踪。"

        label = str(reviewed.get("analysis_label") or "信息不足")
        risk_level = str(reviewed.get("risk_level") or "unknown")
        one_year = returns.get("one_year_pct")
        max_drawdown = risk.get("max_drawdown_pct")
        pe_pct = valuation.get("pe_percentile")
        pb_pct = valuation.get("pb_percentile")

        expensive = any(value is not None and value >= 80 for value in (pe_pct, pb_pct))
        cheap = any(value is not None and value <= 30 for value in (pe_pct, pb_pct))
        weak_return = one_year is not None and one_year < 0
        deep_drawdown = max_drawdown is not None and max_drawdown <= -25

        if label == "回避" or risk_level == "high" or deep_drawdown:
            return "持仓者建议优先控制回撤和集中度，复核是否还符合你的基金配置目标。"
        if expensive and not cheap:
            return "估值分位偏高，持仓者适合降低新增投入节奏，并跟踪回撤风险。"
        if weak_return:
            return "近期收益表现偏弱，建议结合基金风格和同类表现复盘是否继续观察。"
        if label == "候选":
            return "公开数据评价偏正面，持仓者可继续观察净值和重仓变化，避免单只基金过度集中。"
        return "信息偏中性，建议维持观察，重点看最新净值、回撤和持仓风格是否偏离预期。"

    def _build_summary(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        estimated_values = [
            value for value in (self._decimal_from_text(item.get("estimated_market_value")) for item in items)
            if value is not None
        ]
        estimated_gains = [
            value for value in (self._decimal_from_text(item.get("estimated_gain")) for item in items)
            if value is not None
        ]
        value_changes = [
            value for value in (self._decimal_from_text(item.get("value_change_from_saved")) for item in items)
            if value is not None
        ]
        high_risk_count = sum(1 for item in items if item.get("risk_level") == "high")
        avoid_count = sum(1 for item in items if item.get("analysis_label") == "回避")

        return {
            "item_count": len(items),
            "priced_count": len(estimated_values),
            "high_risk_count": high_risk_count,
            "avoid_count": avoid_count,
            "total_estimated_market_value": self._format_decimal(sum(estimated_values, Decimal("0")), _MONEY_QUANT)
            if estimated_values else None,
            "total_value_change_from_saved": self._format_signed_decimal(sum(value_changes, Decimal("0")), _MONEY_QUANT)
            if value_changes else None,
            "total_estimated_gain": self._format_signed_decimal(sum(estimated_gains, Decimal("0")), _MONEY_QUANT)
            if estimated_gains else None,
        }

    def _build_ai_summary(
        self,
        items: List[Dict[str, Any]],
        summary: Dict[str, Any],
    ) -> tuple[Optional[str], Optional[str]]:
        try:
            from src.agent.llm_adapter import LLMToolAdapter

            adapter = LLMToolAdapter()
            if not adapter.is_available:
                return None, "LLM 未配置，已返回本地规则建议"

            compact_items = [
                {
                    "fund_code": item.get("fund_code"),
                    "fund_name": item.get("fund_name"),
                    "estimated_market_value": item.get("estimated_market_value"),
                    "estimated_gain": item.get("estimated_gain"),
                    "estimated_gain_pct": item.get("estimated_gain_pct"),
                    "inferred_holding_share": item.get("inferred_holding_share"),
                    "inferred_cost_amount": item.get("inferred_cost_amount"),
                    "valuation_basis": item.get("valuation_basis", [])[:2],
                    "analysis_label": item.get("analysis_label"),
                    "risk_level": item.get("risk_level"),
                    "advice": item.get("advice"),
                    "reasons": item.get("reasons", [])[:3],
                    "risks": item.get("risks", [])[:2],
                }
                for item in items[:12]
            ]
            response = adapter.call_text(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是中文公募基金持仓复盘助手。基于给定数据输出研究辅助建议，"
                            "不要承诺收益，不要输出绝对买卖指令，重点说明依据、风险和待确认项。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            "请用 4-6 条中文要点复盘这个场外基金持仓组合，"
                            f"组合摘要：{summary}；持仓：{compact_items}"
                        ),
                    },
                ],
                temperature=0.2,
                max_tokens=800,
                timeout=45,
            )
            content = (response.content or "").strip()
            if not content or response.provider == "error" or content.startswith("All LLM models failed"):
                return None, content or "LLM 调用失败，已返回本地规则建议"
            return content[:1800], None
        except Exception as exc:
            logger.info("基金持仓 AI 复盘失败，降级到规则建议: %s", exc)
            return None, "LLM 调用失败，已返回本地规则建议"

    @classmethod
    def _decimal_from_any(cls, value: Any) -> Optional[Decimal]:
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return cls._decimal_from_text(value)

    @staticmethod
    def _decimal_from_text(value: Any) -> Optional[Decimal]:
        if value is None:
            return None
        text = str(value).strip()
        if not text or text.lower() in {"null", "none", "n/a", "nan", "--", "-"}:
            return None
        scale = Decimal("1")
        if "亿" in text:
            scale = Decimal("100000000")
        elif "万" in text:
            scale = Decimal("10000")
        normalized = text.replace(",", "").replace("，", "")
        normalized = re.sub(r"[¥￥元份%+]", "", normalized)
        match = re.search(r"-?\d+(?:\.\d+)?", normalized)
        if not match:
            return None
        try:
            return Decimal(match.group(0)) * scale
        except InvalidOperation:
            return None

    @staticmethod
    def _format_decimal(value: Optional[Decimal], quant: Decimal) -> Optional[str]:
        if value is None:
            return None
        return format(value.quantize(quant, rounding=ROUND_HALF_UP), "f")

    @classmethod
    def _format_signed_decimal(cls, value: Optional[Decimal], quant: Decimal) -> Optional[str]:
        text = cls._format_decimal(value, quant)
        if text is None:
            return None
        return text if text.startswith("-") else f"+{text}"

    @classmethod
    def _format_pct(cls, value: Optional[Decimal]) -> Optional[str]:
        text = cls._format_signed_decimal(value, _PCT_QUANT)
        return f"{text}%" if text is not None else None
