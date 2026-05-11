# -*- coding: utf-8 -*-
"""
场外公募基金分析服务。

第一版只读取公开基金净值与基础资料，不接入支付宝/天天基金个人账户，
避免登录态、验证码和隐私数据带来的不稳定风险。
"""

import logging
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)

_FUND_CODE_RE = re.compile(r"^\d{6}$")
_PCT_QUANT = Decimal("0.01")
_NAV_QUANT = Decimal("0.0001")


class FundServiceError(Exception):
    """基金服务异常。"""


class FundNotFoundError(FundServiceError):
    """基金不存在或无公开数据。"""


@dataclass(frozen=True)
class _NavPoint:
    date: date
    unit_nav: Decimal
    accumulated_nav: Optional[Decimal] = None
    daily_return_pct: Optional[Decimal] = None


def _to_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("%", "")
    if not text or text in {"--", "-", "nan", "NaN", "None"}:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _round_decimal(value: Optional[Decimal], quant: Decimal = _PCT_QUANT) -> Optional[float]:
    if value is None:
        return None
    return float(value.quantize(quant, rounding=ROUND_HALF_UP))


def _normalize_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(text[:10] if fmt != "%Y%m%d" else text[:8], fmt).date()
        except ValueError:
            continue
    return None


def _first_value(row: Any, candidates: Sequence[str]) -> Any:
    for key in candidates:
        try:
            value = row.get(key)
        except AttributeError:
            value = getattr(row, key, None)
        if value is not None and str(value).strip() != "":
            return value
    return None


class FundService:
    """公开场外基金数据与规则分析。"""

    def analyze_fund(self, fund_code: str, *, days: int = 365) -> Dict[str, Any]:
        code = self._normalize_fund_code(fund_code)
        days = max(30, min(int(days), 1825))

        profile = self.get_profile(code)
        nav_points = self.get_nav_history(code, days=days)
        if not nav_points:
            raise FundNotFoundError(f"未找到基金 {code} 的净值数据")

        returns = self._calculate_returns(nav_points)
        risk = self._calculate_risk(nav_points)
        label, reasons, risks, evidence_gaps = self._classify(profile, returns, risk, nav_points)
        latest = nav_points[-1]

        return {
            "profile": profile,
            "latest_nav": self._serialize_nav_point(latest),
            "returns": returns,
            "risk": risk,
            "label": label,
            "summary": self._build_summary(profile, returns, risk, label),
            "reasons": reasons,
            "risks": risks,
            "evidence_gaps": evidence_gaps,
            "nav": [self._serialize_nav_point(item) for item in nav_points[-180:]],
        }

    def get_profile(self, fund_code: str) -> Dict[str, Any]:
        code = self._normalize_fund_code(fund_code)
        profile = {
            "fund_code": code,
            "fund_name": None,
            "fund_type": None,
            "manager": None,
            "custodian": None,
            "inception_date": None,
            "asset_size": None,
            "source": "akshare",
        }

        latest_map = self._get_latest_open_fund_map()
        latest = latest_map.get(code, {})
        profile["fund_name"] = (
            latest.get("fund_name")
            or latest.get("基金简称")
            or latest.get("基金名称")
        )
        profile["fund_type"] = latest.get("fund_type") or latest.get("类型")

        try:
            basic = self._fetch_basic_info(code)
            profile.update({k: v for k, v in basic.items() if v})
        except Exception as exc:
            logger.info("基金 %s 基础资料获取失败，继续使用净值数据: %s", code, exc)

        return profile

    def get_nav_history(self, fund_code: str, *, days: int = 365) -> List[_NavPoint]:
        code = self._normalize_fund_code(fund_code)
        try:
            import akshare as ak
        except ImportError as exc:
            raise FundServiceError("当前环境未安装 AkShare，无法获取场外基金净值") from exc

        raw_df = None
        call_errors: List[str] = []
        for kwargs in (
            {"symbol": code, "indicator": "单位净值走势"},
            {"fund": code, "indicator": "单位净值走势"},
        ):
            try:
                raw_df = ak.fund_open_fund_info_em(**kwargs)
                break
            except TypeError as exc:
                call_errors.append(str(exc))
            except Exception as exc:
                call_errors.append(str(exc))
                break

        if raw_df is None:
            raise FundServiceError(f"AkShare 基金净值接口调用失败: {'; '.join(call_errors)}")

        points = self._parse_nav_frame(raw_df)
        if not points:
            raise FundNotFoundError(f"未找到基金 {code} 的净值数据")

        points = sorted(points, key=lambda item: item.date)
        cutoff = points[-1].date - timedelta(days=days)
        return [item for item in points if item.date >= cutoff]

    @staticmethod
    def _normalize_fund_code(fund_code: str) -> str:
        code = (fund_code or "").strip()
        if "." in code:
            code = code.split(".", 1)[0]
        code = re.sub(r"\D", "", code)
        if not _FUND_CODE_RE.fullmatch(code):
            raise ValueError("请输入 6 位场外基金代码，例如 005918")
        return code

    @staticmethod
    def _parse_nav_frame(df: Any) -> List[_NavPoint]:
        if df is None or getattr(df, "empty", False):
            return []

        points: List[_NavPoint] = []
        for _, row in df.iterrows():
            nav_date = _normalize_date(_first_value(row, ("净值日期", "日期", "FSRQ", "date")))
            unit_nav = _to_decimal(_first_value(row, ("单位净值", "净值", "DWJZ", "unit_nav")))
            if nav_date is None or unit_nav is None or unit_nav <= 0:
                continue

            accumulated_nav = _to_decimal(_first_value(row, ("累计净值", "LJJZ", "accumulated_nav")))
            daily_return = _to_decimal(_first_value(row, ("日增长率", "涨跌幅", "JZZZL", "daily_return_pct")))
            points.append(_NavPoint(
                date=nav_date,
                unit_nav=unit_nav,
                accumulated_nav=accumulated_nav,
                daily_return_pct=daily_return,
            ))
        return points

    @staticmethod
    @lru_cache(maxsize=1)
    def _get_latest_open_fund_map() -> Dict[str, Dict[str, Any]]:
        try:
            import akshare as ak

            df = ak.fund_open_fund_daily_em()
        except Exception as exc:
            logger.info("开放式基金最新净值列表获取失败: %s", exc)
            return {}

        if df is None or getattr(df, "empty", False):
            return {}

        result: Dict[str, Dict[str, Any]] = {}
        for _, row in df.iterrows():
            code = str(_first_value(row, ("基金代码", "代码", "fund_code")) or "").strip()
            if not _FUND_CODE_RE.fullmatch(code):
                continue
            result[code] = {
                "fund_code": code,
                "fund_name": _first_value(row, ("基金简称", "基金名称", "fund_name")),
                "fund_type": _first_value(row, ("基金类型", "类型", "fund_type")),
            }
        return result

    @staticmethod
    def _fetch_basic_info(fund_code: str) -> Dict[str, Any]:
        try:
            import akshare as ak
        except ImportError:
            return {}

        if not hasattr(ak, "fund_individual_basic_info_xq"):
            return {}

        df = ak.fund_individual_basic_info_xq(symbol=fund_code)
        if df is None or getattr(df, "empty", False):
            return {}

        raw: Dict[str, Any] = {}
        for _, row in df.iterrows():
            key = str(_first_value(row, ("item", "项目", "key", "name")) or "").strip()
            value = _first_value(row, ("value", "内容", "值"))
            if key and value is not None:
                raw[key] = str(value).strip()

        return {
            "fund_name": raw.get("基金名称") or raw.get("名称"),
            "fund_type": raw.get("基金类型") or raw.get("类型"),
            "manager": raw.get("基金经理"),
            "custodian": raw.get("基金托管人") or raw.get("托管人"),
            "inception_date": raw.get("成立日期"),
            "asset_size": raw.get("基金规模") or raw.get("资产规模"),
        }

    @staticmethod
    def _serialize_nav_point(point: _NavPoint) -> Dict[str, Any]:
        return {
            "date": point.date.isoformat(),
            "unit_nav": _round_decimal(point.unit_nav, _NAV_QUANT),
            "accumulated_nav": _round_decimal(point.accumulated_nav, _NAV_QUANT),
            "daily_return_pct": _round_decimal(point.daily_return_pct),
        }

    @staticmethod
    def _calculate_period_return(points: Sequence[_NavPoint], days: int) -> Optional[float]:
        if len(points) < 2:
            return None
        latest = points[-1]
        target = latest.date - timedelta(days=days)
        if points[0].date > target:
            return None
        base = None
        for item in reversed(points):
            if item.date <= target:
                base = item
                break
        if base is None:
            base = points[0]
        if base.unit_nav <= 0:
            return None
        pct = (latest.unit_nav / base.unit_nav - Decimal("1")) * Decimal("100")
        return _round_decimal(pct)

    def _calculate_returns(self, points: Sequence[_NavPoint]) -> Dict[str, Optional[float]]:
        return {
            "one_month_pct": self._calculate_period_return(points, 30),
            "three_month_pct": self._calculate_period_return(points, 90),
            "six_month_pct": self._calculate_period_return(points, 180),
            "one_year_pct": self._calculate_period_return(points, 365),
        }

    @staticmethod
    def _calculate_risk(points: Sequence[_NavPoint]) -> Dict[str, Any]:
        if len(points) < 2:
            return {
                "max_drawdown_pct": None,
                "volatility_annualized_pct": None,
                "latest_drawdown_pct": None,
                "risk_level": "unknown",
            }

        peak = points[0].unit_nav
        max_drawdown = Decimal("0")
        for item in points:
            if item.unit_nav > peak:
                peak = item.unit_nav
            if peak > 0:
                drawdown = (item.unit_nav / peak - Decimal("1")) * Decimal("100")
                if drawdown < max_drawdown:
                    max_drawdown = drawdown

        latest_peak = max(item.unit_nav for item in points)
        latest_drawdown = (
            (points[-1].unit_nav / latest_peak - Decimal("1")) * Decimal("100")
            if latest_peak > 0
            else None
        )

        returns: List[float] = []
        for prev, curr in zip(points, points[1:]):
            if prev.unit_nav > 0:
                returns.append(float(curr.unit_nav / prev.unit_nav - Decimal("1")))

        volatility = None
        if len(returns) >= 20:
            avg = sum(returns) / len(returns)
            variance = sum((item - avg) ** 2 for item in returns) / (len(returns) - 1)
            volatility = Decimal(str(math.sqrt(variance) * math.sqrt(252) * 100))

        abs_drawdown = abs(max_drawdown)
        if volatility is None:
            risk_level = "unknown"
        elif abs_drawdown >= Decimal("25") or volatility >= Decimal("30"):
            risk_level = "high"
        elif abs_drawdown >= Decimal("10") or volatility >= Decimal("12"):
            risk_level = "medium"
        else:
            risk_level = "low"

        return {
            "max_drawdown_pct": _round_decimal(max_drawdown),
            "volatility_annualized_pct": _round_decimal(volatility),
            "latest_drawdown_pct": _round_decimal(latest_drawdown),
            "risk_level": risk_level,
        }

    @staticmethod
    def _classify(
        profile: Dict[str, Any],
        returns: Dict[str, Optional[float]],
        risk: Dict[str, Any],
        points: Sequence[_NavPoint],
    ) -> tuple[str, List[str], List[str], List[str]]:
        reasons: List[str] = []
        risks: List[str] = []
        gaps: List[str] = []

        if len(points) < 60:
            gaps.append("历史净值不足 60 个交易日，回撤和波动判断不稳定")

        if not profile.get("fund_type"):
            gaps.append("缺少基金类型，暂不能判断风格是否匹配")
        if not profile.get("manager"):
            gaps.append("缺少基金经理信息，暂不能评估经理稳定性")

        one_month = returns.get("one_month_pct")
        three_month = returns.get("three_month_pct")
        one_year = returns.get("one_year_pct")
        drawdown = risk.get("max_drawdown_pct")
        volatility = risk.get("volatility_annualized_pct")

        if three_month is not None and three_month > 0:
            reasons.append(f"近 3 月收益为 {three_month:.2f}%，短期净值处于修复或上行阶段")
        if one_year is not None and one_year > 0:
            reasons.append(f"近 1 年收益为 {one_year:.2f}%，中期表现为正")
        if drawdown is not None and drawdown > -10:
            reasons.append(f"观察期最大回撤约 {drawdown:.2f}%，回撤相对可控")

        if drawdown is not None and drawdown <= -20:
            risks.append(f"观察期最大回撤约 {drawdown:.2f}%，波动承受要求较高")
        if volatility is not None and volatility >= 25:
            risks.append(f"年化波动率约 {volatility:.2f}%，不适合追求短期稳定收益")
        if one_month is not None and three_month is not None and one_month > 0 and three_month < 0:
            risks.append("近 1 月反弹但近 3 月仍为负，短期修复尚未确认中期趋势")

        if risk.get("risk_level") == "unknown" or len(points) < 30:
            label = "信息不足"
        elif risk.get("risk_level") == "high" and (three_month is None or three_month < 0):
            label = "回避"
        elif risks:
            label = "观察"
        elif (three_month is not None and three_month > 0) and (drawdown is None or drawdown > -15):
            label = "候选"
        else:
            label = "观察"

        if not reasons:
            reasons.append("已获取历史净值，可先作为观察样本纳入基金池")
        if not risks:
            risks.append("公开净值无法反映实时持仓变化，基金重仓和行业暴露存在披露滞后")

        return label, reasons, risks, gaps

    @staticmethod
    def _build_summary(
        profile: Dict[str, Any],
        returns: Dict[str, Optional[float]],
        risk: Dict[str, Any],
        label: str,
    ) -> str:
        name = profile.get("fund_name") or profile["fund_code"]
        fund_type = profile.get("fund_type") or "类型待确认"
        one_month = returns.get("one_month_pct")
        three_month = returns.get("three_month_pct")
        drawdown = risk.get("max_drawdown_pct")

        perf_parts = []
        if one_month is not None:
            perf_parts.append(f"近 1 月 {one_month:.2f}%")
        if three_month is not None:
            perf_parts.append(f"近 3 月 {three_month:.2f}%")
        perf_text = "，".join(perf_parts) if perf_parts else "阶段收益暂不足"
        drawdown_text = f"最大回撤约 {drawdown:.2f}%" if drawdown is not None else "回撤数据不足"

        return (
            f"{name} 当前识别为{fund_type}，综合标签为「{label}」。"
            f"{perf_text}，{drawdown_text}。"
            "第一版分析基于公开净值和基础资料，后续接入你的持仓成本后可进一步判断真实盈亏和组合风险。"
        )
