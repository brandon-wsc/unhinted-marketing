/* AUTO-GENERATED from docs/contracts/query-market-trends-response.schema.json via json-schema-to-typescript — do not edit. */

export type Region = string;
export type SignalId = string;
export type Source = string;
export type Title = string;
export type Url = string | null;
export type Excerpt = string | null;
export type Region1 = string | null;
export type Signals = QueryMarketTrendsSignal[];
export type RankedSignalIds = string[];
export type Notes = string;

export interface QueryMarketTrendsResponse {
  region: Region;
  signals?: Signals;
  ranked_signal_ids?: RankedSignalIds;
  notes?: Notes;
}
/**
 * This interface was referenced by `QueryMarketTrendsResponse`'s JSON-Schema
 * via the `definition` "QueryMarketTrendsSignal".
 */
export interface QueryMarketTrendsSignal {
  signal_id: SignalId;
  source: Source;
  title: Title;
  url?: Url;
  excerpt?: Excerpt;
  region?: Region1;
  metrics?: Metrics;
}
export interface Metrics {
  [k: string]: unknown;
}
