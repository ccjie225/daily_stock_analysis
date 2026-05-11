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


class FundReferenceValuation(BaseModel):
    """基金参考估值"""

    reference_name: Optional[str] = Field(None, description="参考指数或资产名称")
    reference_type: str = Field("unknown", description="参考类型：index/portfolio/unknown")
    pe_ttm: Optional[float] = Field(None, description="参考 PE TTM")
    pe_percentile: Optional[float] = Field(None, description="PE 历史分位")
    pb: Optional[float] = Field(None, description="参考 PB")
    pb_percentile: Optional[float] = Field(None, description="PB 历史分位")
    dividend_yield: Optional[float] = Field(None, description="股息率")
    roe: Optional[float] = Field(None, description="ROE")
    as_of_date: Optional[str] = Field(None, description="估值日期")
    source: Optional[str] = Field(None, description="估值数据源")
    notes: List[str] = Field(default_factory=list, description="估值说明或缺口")


class FundPeerAnalysis(BaseModel):
    """基金同类对比"""

    period: str = Field(..., description="对比周期")
    risk_return_score: Optional[float] = Field(None, description="较同类风险收益评分")
    anti_risk_score: Optional[float] = Field(None, description="较同类抗风险波动评分")
    volatility_annualized_pct: Optional[float] = Field(None, description="同类源年化波动率")
    sharpe_ratio: Optional[float] = Field(None, description="年化夏普比率")
    max_drawdown_pct: Optional[float] = Field(None, description="同类源最大回撤")
    source: Optional[str] = Field(None, description="数据源")


class FundHolding(BaseModel):
    """基金重仓持股"""

    stock_code: str = Field("", description="股票代码")
    stock_name: str = Field("", description="股票名称")
    weight_pct: Optional[float] = Field(None, description="占基金净值比例")
    shares: Optional[float] = Field(None, description="持股数")
    market_value: Optional[float] = Field(None, description="持仓市值")
    report_period: Optional[str] = Field(None, description="报告期")


class FundIndustryAllocation(BaseModel):
    """基金行业配置"""

    industry: str = Field(..., description="行业")
    weight_pct: Optional[float] = Field(None, description="占基金净值比例")
    market_value: Optional[float] = Field(None, description="市值")
    report_date: Optional[str] = Field(None, description="报告日期")


class FundFeeItem(BaseModel):
    """基金费率明细"""

    fee_type: str = Field("", description="费用类型")
    condition: str = Field("", description="条件或费用名称")
    fee_pct: Optional[float] = Field(None, description="费率")
    fee_text: Optional[str] = Field(None, description="展示用费用文本")


class FundFeeSummary(BaseModel):
    """基金费用摘要"""

    management_fee_pct: Optional[float] = Field(None, description="管理费率")
    custodian_fee_pct: Optional[float] = Field(None, description="托管费率")
    sales_service_fee_pct: Optional[float] = Field(None, description="销售服务费率")
    short_term_redemption_fee_pct: Optional[float] = Field(None, description="短持有期赎回费率")
    items: List[FundFeeItem] = Field(default_factory=list, description="费率明细")
    source: Optional[str] = Field(None, description="数据源")


class FundHoldingImportItem(BaseModel):
    """个人基金持仓截图识别结果"""

    fund_code: Optional[str] = Field(None, description="基金代码")
    fund_name: Optional[str] = Field(None, description="基金名称")
    platform: Optional[str] = Field(None, description="识别到的平台")
    holding_amount: Optional[str] = Field(None, description="持有金额/市值，字符串原样预览")
    holding_share: Optional[str] = Field(None, description="持有份额，字符串原样预览")
    cost_amount: Optional[str] = Field(None, description="持仓成本/本金，字符串原样预览")
    cost_nav: Optional[str] = Field(None, description="持仓成本净值/成本价，字符串原样预览")
    latest_nav: Optional[str] = Field(None, description="最新净值，字符串原样预览")
    holding_gain: Optional[str] = Field(None, description="持有收益/累计盈亏，字符串原样预览")
    holding_gain_pct: Optional[str] = Field(None, description="持有收益率，字符串原样预览")
    yesterday_gain: Optional[str] = Field(None, description="昨日收益，字符串原样预览")
    currency: str = Field("CNY", description="币种")
    confidence: str = Field("medium", description="识别置信度：high/medium/low")
    warnings: List[str] = Field(default_factory=list, description="单条识别风险提示")


class FundHoldingImportResponse(BaseModel):
    """个人基金持仓截图导入预览响应"""

    items: List[FundHoldingImportItem] = Field(default_factory=list, description="识别出的个人基金持仓")
    raw_text: Optional[str] = Field(None, description="原始 Vision LLM 响应")
    warnings: List[str] = Field(default_factory=list, description="全局识别风险提示")


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
    reference_valuation: FundReferenceValuation
    peer_analysis: Optional[FundPeerAnalysis] = Field(None, description="同类风险收益对比")
    holdings: List[FundHolding] = Field(default_factory=list, description="最新披露重仓")
    industry_allocation: List[FundIndustryAllocation] = Field(default_factory=list, description="最新披露行业配置")
    fees: FundFeeSummary
    label: str = Field(..., description="候选 / 观察 / 回避 / 信息不足")
    summary: str = Field(..., description="规则分析摘要")
    reasons: List[str] = Field(default_factory=list, description="核心理由")
    risks: List[str] = Field(default_factory=list, description="主要风险")
    evidence_gaps: List[str] = Field(default_factory=list, description="证据缺口")
    nav: List[FundNavPoint] = Field(default_factory=list, description="近期净值序列")
