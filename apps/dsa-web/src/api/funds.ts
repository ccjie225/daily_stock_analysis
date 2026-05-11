import apiClient from './index';
import { toCamelCase } from './utils';
import type { FundAnalysisResponse } from '../types/funds';

export const fundsApi = {
  async analyze(fundCode: string, days = 365): Promise<FundAnalysisResponse> {
    const response = await apiClient.get<Record<string, unknown>>(
      `/api/v1/funds/${encodeURIComponent(fundCode)}/analysis`,
      { params: { days } },
    );
    return toCamelCase<FundAnalysisResponse>(response.data);
  },
};
