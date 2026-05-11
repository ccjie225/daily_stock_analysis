import apiClient from './index';
import { toCamelCase } from './utils';
import type { FundAnalysisResponse, FundHoldingImportResponse } from '../types/funds';

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
};
