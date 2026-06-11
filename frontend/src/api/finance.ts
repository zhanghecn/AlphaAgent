/**
 * API client for financial report endpoints.
 *
 * These endpoints return plain JSON, so we use the shared `plainGet` helper.
 */

import { plainGet } from "./client";
import type { QuarterlyFinanceResponse, FinancialStatementResponse } from "@/types/finance";

/** Fetch quarterly financial reports (revenue, profit, margins, ROE, etc.) */
export function fetchQuarterlyFinance(
  vtSymbol: string,
  limit = 16,
): Promise<QuarterlyFinanceResponse> {
  return plainGet<QuarterlyFinanceResponse>(
    `/research/stocks/${encodeURIComponent(vtSymbol)}/finance/quarterly?limit=${limit}`,
  );
}

/** Fetch one of the three financial statements */
export function fetchFinancialStatement(
  vtSymbol: string,
  statementType: "balance_sheet" | "profit_sheet" | "cash_flow",
): Promise<FinancialStatementResponse> {
  return plainGet<FinancialStatementResponse>(
    `/research/stocks/${encodeURIComponent(vtSymbol)}/finance/statements?statement_type=${statementType}`,
  );
}
