# -*- coding: utf-8 -*-
"""
场外公募基金相关响应模型。
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class FundNavPoint(BaseModel):
    """基金净值点"""

    date: str = Field(..., description="净值日期")
    unit_nav: float = Field(..., description="单位净值")
    accumulated_nav: Optional[float] = Field(None, description="累计净值")
    daily_return_pct: Optional[float] = Field(None, description="日涨跌幅")


class FundReturnMetrics(BaseModel):
    """基金区间收益指标"""

    one_month_pct: Optional[float] = Field(None, description="近 1 月收益率")
    three_month_pct: Optional[float] = Field(None, description="近 3 月收益率")
    six_month_pct: Optional[float] = Field(None, description="近 6 月收益率")
    one_year_pct: Optional[float] = Field(None, description="近 1 年收益率")


class FundRiskMetrics(BaseModel):
    """基金风险指标"""

    max_drawdown_pct: Optional[float] = Field(None, description="最大回撤")
    volatility_annualized_pct: Optional[float] = Field(None, description="年化波动率")
    latest_drawdown_pct: Optional[float] = Field(None, description="当前相对历史高点回撤")
    risk_level: str = Field(..., description="风险等级：low/medium/high/unknown")


class FundProfile(BaseModel):
    """基金基础画像"""

    fund_code: str = Field(..., description="基金代码")
    fund_name: Optional[str] = Field(None, description="基金名称")
    fund_type: Optional[str] = Field(None, description="基金类型")
    manager: Optional[str] = Field(None, description="基金经理")
    custodian: Optional[str] = Field(None, description="托管人")
    inception_date: Optional[str] = Field(None, description="成立日期")
    asset_size: Optional[str] = Field(None, description="基金规模")
    source: str = Field("akshare", description="主要数据源")


class FundAnalysisResponse(BaseModel):
    """基金分析响应"""

    profile: FundProfile
    latest_nav: Optional[FundNavPoint] = Field(None, description="最新净值")
    returns: FundReturnMetrics
    risk: FundRiskMetrics
    label: str = Field(..., description="候选 / 观察 / 回避 / 信息不足")
    summary: str = Field(..., description="规则分析摘要")
    reasons: List[str] = Field(default_factory=list, description="核心理由")
    risks: List[str] = Field(default_factory=list, description="主要风险")
    evidence_gaps: List[str] = Field(default_factory=list, description="证据缺口")
    nav: List[FundNavPoint] = Field(default_factory=list, description="近期净值序列")
