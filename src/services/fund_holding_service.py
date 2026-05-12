# -*- coding: utf-8 -*-
"""Personal offsite fund holding persistence.

This service stores OCR-confirmed holding fields as strings. It intentionally
does not calculate money, cost basis, or PnL in this MVP.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, select
from sqlalchemy.exc import OperationalError

from src.storage import DatabaseManager, FundPersonalHolding

_VALID_CONFIDENCE = frozenset({"high", "medium", "low"})
_NON_NEGATIVE_FIELDS = frozenset(
    {"holding_amount", "holding_share", "cost_amount", "cost_nav", "latest_nav"}
)


class FundHoldingBusyError(Exception):
    """Raised when the local holding store is busy."""


class FundHoldingService:
    """Save/list user-confirmed offsite fund holdings."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    def save_imported_holdings(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not items:
            raise ValueError("items is required")
        if len(items) > 100:
            raise ValueError("items cannot exceed 100")

        normalized = [self._normalize_item(item) for item in items]

        def _write(session):
            now = datetime.now()
            saved: List[Dict[str, Any]] = []
            for item in normalized:
                dedup_hash = self._dedup_hash(item)
                candidate_hashes = self._candidate_dedup_hashes(item)
                existing_rows = session.execute(
                    select(FundPersonalHolding)
                    .where(FundPersonalHolding.dedup_hash.in_(candidate_hashes))
                ).scalars().all()
                rows_by_hash = {row.dedup_hash: row for row in existing_rows}
                row = rows_by_hash.get(dedup_hash)
                if row is None:
                    row = next(
                        (rows_by_hash[item_hash] for item_hash in candidate_hashes[1:] if item_hash in rows_by_hash),
                        None,
                    )
                if row is None:
                    row = FundPersonalHolding(dedup_hash=dedup_hash, created_at=now)
                    session.add(row)
                elif row.dedup_hash != dedup_hash and dedup_hash not in rows_by_hash:
                    row.dedup_hash = dedup_hash

                row.fund_code = item.get("fund_code")
                row.fund_name = item.get("fund_name")
                row.platform = item.get("platform") or "未知"
                row.holding_amount = item.get("holding_amount")
                row.holding_share = item.get("holding_share")
                row.cost_amount = item.get("cost_amount")
                row.cost_nav = item.get("cost_nav")
                row.latest_nav = item.get("latest_nav")
                row.holding_gain = item.get("holding_gain")
                row.holding_gain_pct = item.get("holding_gain_pct")
                row.yesterday_gain = item.get("yesterday_gain")
                row.currency = item.get("currency") or "CNY"
                row.confidence = item.get("confidence") or "medium"
                row.source = "screenshot"
                row.warnings_json = json.dumps(item.get("warnings") or [], ensure_ascii=False)
                row.raw_payload = json.dumps(item, ensure_ascii=False)
                row.updated_at = now
                session.flush()
                saved.append(self._row_to_dict(row))
            return {"saved_count": len(saved), "items": saved}

        try:
            return self.db._run_write_transaction("save_fund_personal_holdings", _write)
        except OperationalError as exc:
            if self.db._is_sqlite_locked_error(exc):
                raise FundHoldingBusyError("基金持仓保存繁忙，请稍后重试") from exc
            raise

    def list_holdings(self, limit: int = 200) -> List[Dict[str, Any]]:
        safe_limit = max(1, min(int(limit or 200), 500))
        with self.db.get_session() as session:
            rows = session.execute(
                select(FundPersonalHolding)
                .order_by(desc(FundPersonalHolding.updated_at), desc(FundPersonalHolding.id))
                .limit(safe_limit)
            ).scalars().all()
            return [self._row_to_dict(row) for row in rows]

    def _normalize_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(item, dict):
            raise ValueError("holding item must be an object")

        fund_code = self._normalize_fund_code(item.get("fund_code") or item.get("fundCode"))
        fund_name = self._clean_text(item.get("fund_name") or item.get("fundName"), max_len=120)
        if not fund_code and not fund_name:
            raise ValueError("基金代码和基金名称至少需要一个")

        normalized: Dict[str, Any] = {
            "fund_code": fund_code,
            "fund_name": fund_name,
            "platform": self._clean_text(item.get("platform"), max_len=32) or "未知",
            "currency": self._normalize_currency(item.get("currency")),
            "confidence": self._normalize_confidence(item.get("confidence")),
            "warnings": self._normalize_warnings(item.get("warnings")),
        }

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
            camel = self._snake_to_camel(field)
            value = self._clean_text(item.get(field) or item.get(camel), max_len=80)
            if field in _NON_NEGATIVE_FIELDS:
                parsed = self._decimal_from_text(value)
                if parsed is not None and parsed < Decimal("0"):
                    raise ValueError(f"{field} cannot be negative")
            normalized[field] = value
        return normalized

    @staticmethod
    def _normalize_fund_code(raw: Any) -> Optional[str]:
        if raw is None:
            return None
        match = re.search(r"(?<!\d)(\d{6})(?!\d)", str(raw).strip())
        return match.group(1) if match else None

    @staticmethod
    def _clean_text(raw: Any, max_len: int) -> Optional[str]:
        if raw is None:
            return None
        text = str(raw).strip()
        if not text or text.lower() in {"null", "none", "n/a", "nan", "-"}:
            return None
        text = re.sub(r"\s+", " ", text)
        return text[:max_len]

    @staticmethod
    def _normalize_currency(raw: Any) -> str:
        text = str(raw or "CNY").strip().upper()
        if text in {"CNY", "RMB"} or text == "人民币":
            return "CNY"
        raise ValueError("currency only supports CNY")

    @staticmethod
    def _normalize_confidence(raw: Any) -> str:
        text = str(raw or "medium").strip().lower()
        return text if text in _VALID_CONFIDENCE else "medium"

    @staticmethod
    def _normalize_warnings(raw: Any) -> List[str]:
        if not isinstance(raw, list):
            return []
        warnings = []
        for item in raw:
            text = str(item).strip()
            if text:
                warnings.append(text[:160])
        return warnings[:20]

    @staticmethod
    def _decimal_from_text(value: Optional[str]) -> Optional[Decimal]:
        if not value:
            return None
        if any(unit in value for unit in ("万", "亿")):
            return None
        normalized = value.replace(",", "").replace("，", "").strip()
        normalized = re.sub(r"[¥￥元份%]", "", normalized)
        normalized = normalized.replace("+", "", 1)
        match = re.search(r"-?\d+(?:\.\d+)?", normalized)
        if not match:
            return None
        try:
            return Decimal(match.group(0))
        except InvalidOperation:
            return None

    @staticmethod
    def _snake_to_camel(value: str) -> str:
        head, *tail = value.split("_")
        return head + "".join(part[:1].upper() + part[1:] for part in tail)

    @staticmethod
    def _dedup_hash(item: Dict[str, Any]) -> str:
        fund_identity = item.get("fund_code") or item.get("fund_name") or ""
        identity = "|".join(
            [
                "fund-holding-v1",
                fund_identity,
                item.get("platform") or "未知",
            ]
        )
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    @classmethod
    def _candidate_dedup_hashes(cls, item: Dict[str, Any]) -> List[str]:
        hashes = [cls._dedup_hash(item)]
        if item.get("fund_code") and item.get("fund_name"):
            legacy_name_item = {**item, "fund_code": None}
            legacy_name_hash = cls._dedup_hash(legacy_name_item)
            if legacy_name_hash not in hashes:
                hashes.append(legacy_name_hash)
        return hashes

    @staticmethod
    def _row_to_dict(row: FundPersonalHolding) -> Dict[str, Any]:
        try:
            warnings = json.loads(row.warnings_json or "[]")
        except Exception:
            warnings = []
        if not isinstance(warnings, list):
            warnings = []
        return {
            "id": int(row.id),
            "fund_code": row.fund_code,
            "fund_name": row.fund_name,
            "platform": row.platform,
            "holding_amount": row.holding_amount,
            "holding_share": row.holding_share,
            "cost_amount": row.cost_amount,
            "cost_nav": row.cost_nav,
            "latest_nav": row.latest_nav,
            "holding_gain": row.holding_gain,
            "holding_gain_pct": row.holding_gain_pct,
            "yesterday_gain": row.yesterday_gain,
            "currency": row.currency,
            "confidence": row.confidence,
            "source": row.source,
            "warnings": [str(item) for item in warnings],
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
