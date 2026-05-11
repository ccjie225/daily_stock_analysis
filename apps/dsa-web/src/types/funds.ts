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
  label: string;
  summary: string;
  reasons: string[];
  risks: string[];
  evidenceGaps: string[];
  nav: FundNavPoint[];
}
