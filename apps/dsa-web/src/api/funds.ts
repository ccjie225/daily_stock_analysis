import apiClient from './index';
import { toCamelCase } from './utils';
import type {
  FundAnalysisResponse,
  FundHoldingImportItem,
  FundHoldingImportResponse,
  FundHoldingListResponse,
  FundHoldingReviewResponse,
  FundHoldingSaveResponse,
} from '../types/funds';

function toSnakeHoldingItem(item: FundHoldingImportItem): Record<string, unknown> {
  return {
    fund_code: item.fundCode,
    fund_name: item.fundName,
    platform: item.platform,
    holding_amount: item.holdingAmount,
    holding_share: item.holdingShare,
    cost_amount: item.costAmount,
    cost_nav: item.costNav,
    latest_nav: item.latestNav,
    holding_gain: item.holdingGain,
    holding_gain_pct: item.holdingGainPct,
    yesterday_gain: item.yesterdayGain,
    currency: item.currency,
    confidence: item.confidence,
    warnings: item.warnings,
  };
}

export const fundsApi = {
  async analyze(fundCode: string, days = 365): Promise<FundAnalysisResponse> {
    const response = await apiClient.get<Record<string, unknown>>(
      `/api/v1/funds/${encodeURIComponent(fundCode)}/analysis`,
      { params: { days } },
    );
    return toCamelCase<FundAnalysisResponse>(response.data);
  },

  async importHoldingsImage(file: File): Promise<FundHoldingImportResponse> {
    const formData = new FormData();
    formData.append('file', file);

    const headers: { [key: string]: string | undefined } = { 'Content-Type': undefined };
    const response = await apiClient.post<Record<string, unknown>>(
      '/api/v1/funds/import-holdings-image',
      formData,
      {
        headers,
        timeout: 60000,
      },
    );
    return toCamelCase<FundHoldingImportResponse>(response.data);
  },

  async saveHoldings(items: FundHoldingImportItem[]): Promise<FundHoldingSaveResponse> {
    const response = await apiClient.post<Record<string, unknown>>(
      '/api/v1/funds/holdings',
      { items: items.map(toSnakeHoldingItem) },
    );
    return toCamelCase<FundHoldingSaveResponse>(response.data);
  },

  async listHoldings(): Promise<FundHoldingListResponse> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/funds/holdings');
    return toCamelCase<FundHoldingListResponse>(response.data);
  },

  async reviewHoldings(useAi = false): Promise<FundHoldingReviewResponse> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/funds/holdings/review', {
      params: { use_ai: useAi },
      timeout: useAi ? 90000 : 60000,
    });
    return toCamelCase<FundHoldingReviewResponse>(response.data);
  },
};
