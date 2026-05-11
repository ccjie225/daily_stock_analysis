export interface FundNavPoint {
  date: string;
  unitNav: number;
  accumulatedNav?: number | null;
  dailyReturnPct?: number | null;
}

export interface FundReturnMetrics {
  oneMonthPct?: number | null;
  threeMonthPct?: number | null;
  sixMonthPct?: number | null;
  oneYearPct?: number | null;
}

export interface FundRiskMetrics {
  maxDrawdownPct?: number | null;
  volatilityAnnualizedPct?: number | null;
  latestDrawdownPct?: number | null;
  riskLevel: 'low' | 'medium' | 'high' | 'unknown' | string;
}

export interface FundReferenceValuation {
  referenceName?: string | null;
  referenceType: 'index' | 'portfolio' | 'unknown' | string;
  peTtm?: number | null;
  pePercentile?: number | null;
  pb?: number | null;
  pbPercentile?: number | null;
  dividendYield?: number | null;
  roe?: number | null;
  asOfDate?: string | null;
  source?: string | null;
  notes: string[];
}

export interface FundPeerAnalysis {
  period: string;
  riskReturnScore?: number | null;
  antiRiskScore?: number | null;
  volatilityAnnualizedPct?: number | null;
  sharpeRatio?: number | null;
  maxDrawdownPct?: number | null;
  source?: string | null;
}

export interface FundHolding {
  stockCode: string;
  stockName: string;
  weightPct?: number | null;
  shares?: number | null;
  marketValue?: number | null;
  reportPeriod?: string | null;
}

export interface FundIndustryAllocation {
  industry: string;
  weightPct?: number | null;
  marketValue?: number | null;
  reportDate?: string | null;
}

export interface FundFeeItem {
  feeType: string;
  condition: string;
  feePct?: number | null;
  feeText?: string | null;
}

export interface FundFeeSummary {
  managementFeePct?: number | null;
  custodianFeePct?: number | null;
  salesServiceFeePct?: number | null;
  shortTermRedemptionFeePct?: number | null;
  items: FundFeeItem[];
  source?: string | null;
}

export interface FundProfile {
  fundCode: string;
  fundName?: string | null;
  fundType?: string | null;
  manager?: string | null;
  custodian?: string | null;
  inceptionDate?: string | null;
  assetSize?: string | null;
  source: string;
}

export interface FundAnalysisResponse {
  profile: FundProfile;
  latestNav?: FundNavPoint | null;
  returns: FundReturnMetrics;
  risk: FundRiskMetrics;
  referenceValuation: FundReferenceValuation;
  peerAnalysis?: FundPeerAnalysis | null;
  holdings: FundHolding[];
  industryAllocation: FundIndustryAllocation[];
  fees: FundFeeSummary;
  label: string;
  summary: string;
  reasons: string[];
  risks: string[];
  evidenceGaps: string[];
  nav: FundNavPoint[];
}
