/**
 * Type definitions for financial report APIs.
 *
 * Research endpoints return plain JSON (not the {success, data} wrapper).
 */

// ── Quarterly Financial Report ──

export interface QuarterlyFinanceItem {
  report_date: string;
  period_type?: string;
  revenue: number | null;
  revenue_yoy: number | null;
  revenue_qoq?: number | null;
  net_profit: number | null;
  net_profit_yoy: number | null;
  net_profit_qoq?: number | null;
  deducted_net_profit?: number | null;
  gross_margin: number | null;
  net_margin: number | null;
  eps?: number | null;
  roe: number | null;
  debt_asset_ratio?: number | null;
  operating_cash_flow?: number | null;
  cash_flow_quality?: number | null;
  publish_date?: string | null;
  raw?: Record<string, unknown>;
}

export interface QuarterlyFinanceResponse {
  vt_symbol: string;
  period_type?: string;
  items: QuarterlyFinanceItem[];
  total: number;
  source: string;
  updated_at?: string;
  message?: string;
}

// ── Financial Statements (dynamic column names) ──

export type StatementItem = Record<string, string | number | null>;

export interface FinancialStatementResponse {
  vt_symbol: string;
  statement_type: "balance_sheet" | "profit_sheet" | "cash_flow";
  items: StatementItem[];
  total: number;
  source: string;
  updated_at?: string;
  message?: string;
}
