/* AUTO-GENERATED from docs/contracts/query-market-trends-request.schema.json via json-schema-to-typescript — do not edit. */

export type Region = string;
export type Limit = number;
export type CompanyId = string | null;
export type UserRequest = string | null;

/**
 * Read-only market signal lookup (background ingest + session trend_searcher).
 */
export interface QueryMarketTrendsRequest {
  region?: Region;
  limit?: Limit;
  company_id?: CompanyId;
  user_request?: UserRequest;
}
