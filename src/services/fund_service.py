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
_RATIO_QUANT = Decimal("0.01")
_MARKET_VALUE_QUANT = Decimal("0.01")

# AkShare's Legulegu index valuation endpoint only supports this finite set.
# Keep matching ordered so "中证1000" is tested before "中证100".
_INDEX_VALUATION_CANDIDATES = (
    ("中证1000", "中证1000"),
    ("创业板50", "创业板50"),
    ("沪深300", "沪深300"),
    ("中证500", "中证500"),
    ("中证800", "中证800"),
    ("深证100", "深证100"),
    ("上证380", "上证380"),
    ("上证180", "上证180"),
    ("上证50", "上证50"),
    ("深证红利", "深证红利"),
    ("上证红利", "上证红利"),
    ("中证100", "中证100"),
)


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
        reference_valuation = self.get_reference_valuation(profile)
        peer_analysis = self.get_peer_analysis(code)
        holdings = self.get_top_holdings(code)
        industry_allocation = self.get_industry_allocation(code)
        fees = self.get_fees(code)
        label, reasons, risks, evidence_gaps = self._classify(
            profile,
            returns,
            risk,
            nav_points,
            reference_valuation=reference_valuation,
            peer_analysis=peer_analysis,
            holdings=holdings,
            industry_allocation=industry_allocation,
            fees=fees,
        )
        latest = nav_points[-1]

        return {
            "profile": profile,
            "latest_nav": self._serialize_nav_point(latest),
            "returns": returns,
            "risk": risk,
            "reference_valuation": reference_valuation,
            "peer_analysis": peer_analysis,
            "holdings": holdings,
            "industry_allocation": industry_allocation,
            "fees": fees,
            "label": label,
            "summary": self._build_summary(profile, returns, risk, label, reference_valuation),
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

    def get_reference_valuation(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        """Return PE/PB reference data for index-like funds when it is available."""
        reference_name = self._infer_reference_index(profile)
        result = {
            "reference_name": reference_name,
            "reference_type": "index" if reference_name else "unknown",
            "pe_ttm": None,
            "pe_percentile": None,
            "pb": None,
            "pb_percentile": None,
            "dividend_yield": None,
            "roe": None,
            "as_of_date": None,
            "source": None,
            "notes": [],
        }

        if not reference_name:
            result["notes"].append(
                "未自动匹配到可用指数估值；QDII/主动基金需参考跟踪指数或重仓资产估值"
            )
            return result

        try:
            import akshare as ak
        except ImportError:
            result["notes"].append("当前环境未安装 AkShare，无法获取指数 PE/PB")
            return result

        try:
            pe_df = ak.stock_index_pe_lg(symbol=reference_name)
            pe_current, pe_percentile, pe_date = self._extract_index_metric(
                pe_df,
                ("滚动市盈率", "市盈率", "静态市盈率"),
            )
            result["pe_ttm"] = _round_decimal(pe_current, _RATIO_QUANT)
            result["pe_percentile"] = _round_decimal(pe_percentile, _PCT_QUANT)
            result["as_of_date"] = pe_date or result["as_of_date"]
        except Exception as exc:
            result["notes"].append(f"{reference_name} PE 获取失败")
            logger.info("基金参考指数 %s PE 获取失败: %s", reference_name, exc)

        try:
            pb_df = ak.stock_index_pb_lg(symbol=reference_name)
            pb_current, pb_percentile, pb_date = self._extract_index_metric(
                pb_df,
                ("市净率", "PB"),
            )
            result["pb"] = _round_decimal(pb_current, _RATIO_QUANT)
            result["pb_percentile"] = _round_decimal(pb_percentile, _PCT_QUANT)
            result["as_of_date"] = result["as_of_date"] or pb_date
        except Exception as exc:
            result["notes"].append(f"{reference_name} PB 获取失败")
            logger.info("基金参考指数 %s PB 获取失败: %s", reference_name, exc)

        if result["pe_ttm"] is not None or result["pb"] is not None:
            result["source"] = "akshare.stock_index_pe_lg/stock_index_pb_lg"
        else:
            result["notes"].append("参考指数已识别，但估值数据源暂不可用")
        return result

    def get_peer_analysis(self, fund_code: str) -> Optional[Dict[str, Any]]:
        try:
            import akshare as ak
        except ImportError:
            return None

        if not hasattr(ak, "fund_individual_analysis_xq"):
            return None

        try:
            df = ak.fund_individual_analysis_xq(symbol=fund_code)
        except Exception as exc:
            logger.info("基金 %s 同类分析获取失败: %s", fund_code, exc)
            return None

        if df is None or getattr(df, "empty", False):
            return None

        row = self._pick_period_row(df, ("近1年", "近一年", "1年"))
        if row is None:
            try:
                row = next(df.iterrows())[1]
            except StopIteration:
                return None

        return {
            "period": str(_first_value(row, ("周期", "period")) or "近1年"),
            "risk_return_score": _round_decimal(_to_decimal(_first_value(row, ("较同类风险收益比", "risk_return_score")))),
            "anti_risk_score": _round_decimal(_to_decimal(_first_value(row, ("较同类抗风险波动", "anti_risk_score")))),
            "volatility_annualized_pct": _round_decimal(_to_decimal(_first_value(row, ("年化波动率", "volatility_annualized_pct")))),
            "sharpe_ratio": _round_decimal(_to_decimal(_first_value(row, ("年化夏普比率", "sharpe_ratio"))), _RATIO_QUANT),
            "max_drawdown_pct": _round_decimal(_to_decimal(_first_value(row, ("最大回撤", "max_drawdown_pct")))),
            "source": "akshare.fund_individual_analysis_xq",
        }

    def get_top_holdings(self, fund_code: str, *, limit: int = 10) -> List[Dict[str, Any]]:
        try:
            import akshare as ak
        except ImportError:
            return []

        frames = []
        for year in self._candidate_report_years():
            try:
                df = ak.fund_portfolio_hold_em(symbol=fund_code, date=year)
            except Exception as exc:
                logger.info("基金 %s %s 持仓获取失败: %s", fund_code, year, exc)
                continue
            if df is not None and not getattr(df, "empty", False):
                frames.append(df)
                break

        if not frames:
            return []

        df = frames[0]
        rows = list(df.iterrows())
        latest_report = self._latest_report_key(row for _, row in rows)
        result: List[Dict[str, Any]] = []
        for _, row in rows:
            quarter = str(_first_value(row, ("季度", "报告期", "report_period")) or "").strip()
            if latest_report and self._report_sort_key(quarter) != latest_report:
                continue
            code = str(_first_value(row, ("股票代码", "代码", "stock_code")) or "").strip()
            name = str(_first_value(row, ("股票名称", "名称", "stock_name")) or "").strip()
            if not code and not name:
                continue
            result.append({
                "stock_code": code,
                "stock_name": name,
                "weight_pct": _round_decimal(_to_decimal(_first_value(row, ("占净值比例", "持仓占比", "weight_pct")))),
                "shares": _round_decimal(_to_decimal(_first_value(row, ("持股数", "shares"))), _RATIO_QUANT),
                "market_value": _round_decimal(_to_decimal(_first_value(row, ("持仓市值", "市值", "market_value"))), _MARKET_VALUE_QUANT),
                "report_period": quarter or None,
            })
            if len(result) >= limit:
                break
        return result

    def get_industry_allocation(self, fund_code: str, *, limit: int = 8) -> List[Dict[str, Any]]:
        try:
            import akshare as ak
        except ImportError:
            return []

        frames = []
        for year in self._candidate_report_years():
            try:
                df = ak.fund_portfolio_industry_allocation_em(symbol=fund_code, date=year)
            except Exception as exc:
                logger.info("基金 %s %s 行业配置获取失败: %s", fund_code, year, exc)
                continue
            if df is not None and not getattr(df, "empty", False):
                frames.append(df)
                break

        if not frames:
            return []

        df = frames[0]
        rows = list(df.iterrows())
        latest_date = self._latest_report_date(row for _, row in rows)
        result: List[Dict[str, Any]] = []
        for _, row in rows:
            report_date = _normalize_date(_first_value(row, ("截止时间", "报告期", "date")))
            if latest_date and report_date != latest_date:
                continue
            industry = str(_first_value(row, ("行业类别", "行业", "industry")) or "").strip()
            if not industry:
                continue
            result.append({
                "industry": industry,
                "weight_pct": _round_decimal(_to_decimal(_first_value(row, ("占净值比例", "weight_pct")))),
                "market_value": _round_decimal(_to_decimal(_first_value(row, ("市值", "market_value"))), _MARKET_VALUE_QUANT),
                "report_date": report_date.isoformat() if report_date else None,
            })
            if len(result) >= limit:
                break
        return result

    def get_fees(self, fund_code: str) -> Dict[str, Any]:
        result = {
            "management_fee_pct": None,
            "custodian_fee_pct": None,
            "sales_service_fee_pct": None,
            "short_term_redemption_fee_pct": None,
            "items": [],
            "source": None,
        }

        try:
            import akshare as ak
        except ImportError:
            return result

        if not hasattr(ak, "fund_individual_detail_info_xq"):
            return result

        try:
            df = ak.fund_individual_detail_info_xq(symbol=fund_code)
        except Exception as exc:
            logger.info("基金 %s 费率获取失败: %s", fund_code, exc)
            return result

        if df is None or getattr(df, "empty", False):
            return result

        for _, row in df.iterrows():
            fee_type = str(_first_value(row, ("费用类型", "fee_type")) or "").strip()
            condition = str(_first_value(row, ("条件或名称", "条件", "名称", "condition")) or "").strip()
            value = _to_decimal(_first_value(row, ("费用", "费率", "value")))
            value_float = _round_decimal(value, _RATIO_QUANT)
            fee_text = f"{value_float:.2f}%" if value_float is not None else None
            if value is not None and value > Decimal("100"):
                value_float = None
                fee_text = f"{_round_decimal(value, _RATIO_QUANT):.2f}元"
            if fee_type or condition or value is not None:
                result["items"].append({
                    "fee_type": fee_type,
                    "condition": condition,
                    "fee_pct": value_float,
                    "fee_text": fee_text,
                })

            if "基金管理费" in condition:
                result["management_fee_pct"] = value_float
            elif "基金托管费" in condition:
                result["custodian_fee_pct"] = value_float
            elif "销售服务费" in condition:
                result["sales_service_fee_pct"] = value_float
            elif "持有期限<7" in condition or "持有期限 < 7" in condition:
                result["short_term_redemption_fee_pct"] = value_float

        result["items"] = result["items"][:12]
        result["source"] = "akshare.fund_individual_detail_info_xq" if result["items"] else None
        return result

    @staticmethod
    def _infer_reference_index(profile: Dict[str, Any]) -> Optional[str]:
        haystack = " ".join(
            str(profile.get(key) or "")
            for key in ("fund_name", "fund_type")
        )
        for keyword, index_name in _INDEX_VALUATION_CANDIDATES:
            if keyword in haystack:
                return index_name
        return None

    @staticmethod
    def _extract_index_metric(
        df: Any,
        column_candidates: Sequence[str],
    ) -> tuple[Optional[Decimal], Optional[Decimal], Optional[str]]:
        if df is None or getattr(df, "empty", False):
            return None, None, None

        values: List[Decimal] = []
        latest_date = None
        for _, row in df.iterrows():
            value = _to_decimal(_first_value(row, column_candidates))
            if value is None or value <= 0:
                continue
            values.append(value)
            latest_date = _normalize_date(_first_value(row, ("日期", "date", "trade_date")))

        if not values:
            return None, None, None

        current = values[-1]
        percentile = Decimal(sum(1 for item in values if item <= current)) / Decimal(len(values)) * Decimal("100")
        return current, percentile, latest_date.isoformat() if latest_date else None

    @staticmethod
    def _pick_period_row(df: Any, preferred_periods: Sequence[str]) -> Any:
        preferred = set(preferred_periods)
        for _, row in df.iterrows():
            period = str(_first_value(row, ("周期", "period")) or "").strip()
            if period in preferred:
                return row
        return None

    @staticmethod
    def _candidate_report_years() -> List[str]:
        current_year = date.today().year
        return [str(current_year), str(current_year - 1), str(current_year - 2)]

    @staticmethod
    def _report_sort_key(value: str) -> int:
        text = (value or "").strip()
        match = re.search(r"(\d{4})\D*([1-4])\D*季度", text)
        if match:
            return int(match.group(1)) * 10 + int(match.group(2))

        parsed = _normalize_date(text)
        if parsed:
            return int(parsed.strftime("%Y%m%d"))

        match = re.search(r"(\d{4})(\d{2})(\d{2})", text)
        if match:
            return int("".join(match.groups()))
        return -1

    @classmethod
    def _latest_report_key(cls, rows: Iterable[Any]) -> Optional[int]:
        keys = [
            cls._report_sort_key(str(_first_value(row, ("季度", "报告期", "date")) or ""))
            for row in rows
        ]
        valid = [item for item in keys if item >= 0]
        return max(valid) if valid else None

    @staticmethod
    def _latest_report_date(rows: Iterable[Any]) -> Optional[date]:
        dates = [
            _normalize_date(_first_value(row, ("截止时间", "报告期", "date")))
            for row in rows
        ]
        valid = [item for item in dates if item is not None]
        return max(valid) if valid else None

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
        *,
        reference_valuation: Optional[Dict[str, Any]] = None,
        peer_analysis: Optional[Dict[str, Any]] = None,
        holdings: Optional[Sequence[Dict[str, Any]]] = None,
        industry_allocation: Optional[Sequence[Dict[str, Any]]] = None,
        fees: Optional[Dict[str, Any]] = None,
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
        reference_valuation = reference_valuation or {}
        peer_analysis = peer_analysis or {}
        holdings = holdings or []
        industry_allocation = industry_allocation or []
        fees = fees or {}

        if three_month is not None and three_month > 0:
            reasons.append(f"近 3 月收益为 {three_month:.2f}%，短期净值处于修复或上行阶段")
        if one_year is not None and one_year > 0:
            reasons.append(f"近 1 年收益为 {one_year:.2f}%，中期表现为正")
        if drawdown is not None and drawdown > -10:
            reasons.append(f"观察期最大回撤约 {drawdown:.2f}%，回撤相对可控")

        reference_name = reference_valuation.get("reference_name")
        pe = reference_valuation.get("pe_ttm")
        pe_percentile = reference_valuation.get("pe_percentile")
        pb = reference_valuation.get("pb")
        pb_percentile = reference_valuation.get("pb_percentile")
        if reference_name and (pe is not None or pb is not None):
            value_parts = []
            if pe is not None:
                value_parts.append(f"PE {pe:.2f}")
            if pb is not None:
                value_parts.append(f"PB {pb:.2f}")
            reasons.append(f"已匹配参考指数 {reference_name}，可用 {'、'.join(value_parts)} 作为估值参照")
        elif reference_valuation.get("reference_type") == "unknown":
            gaps.append("未匹配到 PE/PB 估值参考，需通过跟踪指数、重仓股估值或人工映射补充")

        if pe_percentile is not None and pe_percentile >= 80:
            risks.append(f"{reference_name or '参考指数'} PE 处于历史约 {pe_percentile:.0f}% 分位，估值偏高")
        elif pe_percentile is not None and pe_percentile <= 25:
            reasons.append(f"{reference_name or '参考指数'} PE 处于历史约 {pe_percentile:.0f}% 分位，估值压力相对较低")
        if pb_percentile is not None and pb_percentile >= 80:
            risks.append(f"{reference_name or '参考指数'} PB 处于历史约 {pb_percentile:.0f}% 分位，净资产估值偏高")

        risk_return_score = peer_analysis.get("risk_return_score")
        anti_risk_score = peer_analysis.get("anti_risk_score")
        sharpe = peer_analysis.get("sharpe_ratio")
        if risk_return_score is not None and risk_return_score >= 70:
            reasons.append(f"同类风险收益评分约 {risk_return_score:.0f}，同类对比表现较好")
        if anti_risk_score is not None and anti_risk_score < 40:
            risks.append(f"同类抗风险波动评分约 {anti_risk_score:.0f}，下跌波动控制偏弱")
        if sharpe is not None and sharpe > 1:
            reasons.append(f"近 1 年夏普比率约 {sharpe:.2f}，风险调整后收益为正")

        top_ten_weight = sum(
            item.get("weight_pct") or 0
            for item in holdings[:10]
        ) if holdings else None
        if top_ten_weight is not None and top_ten_weight >= 50:
            risks.append(f"前十大重仓合计约 {top_ten_weight:.2f}%，持仓集中度较高")
        elif holdings:
            reasons.append(f"已获取最新披露重仓股，前十大合计约 {top_ten_weight:.2f}%")
        else:
            gaps.append("缺少重仓股披露数据，暂不能判断持仓集中度和风格漂移")

        top_industry = industry_allocation[0] if industry_allocation else None
        if top_industry and (top_industry.get("weight_pct") or 0) >= 40:
            risks.append(
                f"行业配置集中在{top_industry.get('industry')}，占净值约 {top_industry.get('weight_pct'):.2f}%"
            )
        elif industry_allocation:
            reasons.append("已获取最新行业配置，可辅助判断主题暴露")
        else:
            gaps.append("缺少行业配置数据，暂不能判断主题暴露")

        short_fee = fees.get("short_term_redemption_fee_pct")
        if short_fee is not None and short_fee > 0:
            risks.append(f"短持有期赎回费率最高约 {short_fee:.2f}%，不适合频繁短线进出")

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
        reference_valuation: Optional[Dict[str, Any]] = None,
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
        reference_valuation = reference_valuation or {}
        reference_name = reference_valuation.get("reference_name")
        pe = reference_valuation.get("pe_ttm")
        pb = reference_valuation.get("pb")
        if reference_name and (pe is not None or pb is not None):
            valuation_text = f"参考{reference_name}"
            valuation_parts = []
            if pe is not None:
                valuation_parts.append(f"PE {pe:.2f}")
            if pb is not None:
                valuation_parts.append(f"PB {pb:.2f}")
            valuation_text = f"{valuation_text}{'、'.join(valuation_parts)}。"
        else:
            valuation_text = "PE/PB 估值参考尚未稳定匹配，需要结合跟踪指数或重仓资产补充。"

        return (
            f"{name} 当前识别为{fund_type}，综合标签为「{label}」。"
            f"{perf_text}，{drawdown_text}。{valuation_text}"
            "分析基于公开净值、披露持仓、费用和可用估值参考；接入你的持仓成本后可进一步判断真实盈亏和组合风险。"
        )
