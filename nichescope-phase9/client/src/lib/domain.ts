export type RunStatus = "success" | "partial" | "failed" | "running";
export type FulfillmentType = "FBA" | "FBM" | "Unknown" | null;

export interface Keyword { id: number; text: string }
export interface Niche {
  id: number; name: string; slug: string; created_at: string; last_scraped_at: string | null;
  keyword_count?: number; product_count?: number; seller_count?: number; keywords: Keyword[];
}
export interface OpportunityScore {
  snapshot_id: number; demand_score: number | null; competition_score: number | null;
  quality_gap_score: number | null; final_score: number | null; computed_at: string;
}
export interface Snapshot {
  id: number; product_id: number; search_run_id: number; parsed_at: string;
  price: number | null; currency: string | null; rating: number | null; review_count: number | null;
  bsr: unknown[] | null; search_rank_position: number | null;
  is_sponsored: number | null; is_amazons_choice: number | null; is_best_seller: number | null;
  images_count: number | null; bullet_points_count: number | null; has_a_plus_content: number | null;
  variant_count: number | null; weight_and_dimensions: string | null; opportunity: OpportunityScore | null;
}
export interface Product {
  id: number; asin: string; title: string | null; brand: string | null; seller_id: number | null;
  seller_name: string | null; fulfillment_type: FulfillmentType; category_path: string[];
  product_url: string | null; thumbnail_url: string | null; first_seen_at: string;
  niches: Array<{ id: number; name: string }>; current: Snapshot | null;
}
export interface SearchRun {
  id: number; niche_id: number; niche_name: string; keyword_id: number | null; keyword: string | null;
  run_timestamp: string; pages_scraped: number | null; products_found: number | null; status: RunStatus;
  current_stage: string | null; current_task: string | null; notes: string | null; error_count: number;
}
export interface ScrapeError {
  id: number; search_run_id: number | null; url: string | null; error_type: string | null;
  error_message: string | null; attempt_number: number | null; occurred_at: string;
  niche_name?: string | null; keyword?: string | null;
}
export interface PageResult<T> { items: T[]; total: number; page: number; page_size: number }
export interface DashboardSnapshot {
  totals: { niches: number; products: number; sellers: number; search_runs: number;
    successful_runs: number; partial_runs: number; failed_runs: number; running_runs: number;
    snapshots: number; scored_products: number };
  runs_by_day: Array<{ date: string; count: number }>;
  run_status: Array<{ label: RunStatus; count: number }>;
  products_by_niche: Array<{ id: number; label: string; count: number }>;
  price_distribution: Array<{ currency: string; bucket: number; count: number }>;
  rating_distribution: Array<{ bucket: number; count: number }>;
  score_distribution: Array<{ bucket: number; count: number }>;
  top_opportunities: Array<{ id: number; asin: string; title: string | null; brand: string | null; final_score: number }>;
  recent_runs: SearchRun[];
}
export interface HistoryPoint {
  id: number; product_id: number; search_run_id: number; parsed_at: string; run_timestamp: string;
  niche_id: number; niche_name: string; price: number | null; currency: string | null;
  rating: number | null; review_count: number | null; bsr: unknown[] | null;
  search_rank_position: number | null; is_sponsored: number | null; is_amazons_choice: number | null;
  is_best_seller: number | null; images_count: number | null; bullet_points_count: number | null;
  has_a_plus_content: number | null; variant_count: number | null; weight_and_dimensions: string | null;
  opportunity: OpportunityScore | null;
}
export interface AnalyticsPoint {
  snapshot_id: number; product_id: number; asin: string; title: string | null; brand: string | null;
  seller_id: number | null; seller_name: string | null; fulfillment_type: FulfillmentType;
  search_run_id: number; niche_id: number; niche_name: string; parsed_at: string;
  price: number | null; currency: string | null; rating: number | null; review_count: number | null;
  bsr: unknown[] | null; search_rank_position: number | null; is_sponsored: number | null;
  is_amazons_choice: number | null; is_best_seller: number | null; images_count: number | null;
  bullet_points_count: number | null; has_a_plus_content: number | null; variant_count: number | null;
  demand_score: number | null; competition_score: number | null; quality_gap_score: number | null; final_score: number | null;
}
export interface Schedule {
  id: number; niche_id: number; niche_name: string; keyword_id: number; keyword: string;
  frequency: "daily" | "weekly"; is_active: 0 | 1; pages: number; products: number;
  run_times: string; timezone: string; last_triggered_at: string | null;
  last_slot_key: string | null; created_at: string;
}
export interface DemandTrackerData {
  niches: Array<{ id: number; name: string; product_count: number; latest_observation: string | null }>;
  selected_niche: { id: number; name: string; product_count: number; latest_observation: string | null } | null;
  summary: { products_with_snapshots: number; scored_products: number; latest_observation: string | null;
    product_count: number; coverage_percent: number } | null;
  items: Array<{ product_id: number; asin: string; title: string | null; brand: string | null;
    snapshot_id: number; parsed_at: string; review_count: number | null; search_run_id: number;
    demand_score: number | null; computed_at: string | null; review_observations: number;
    score_status: string }>;
  time_series: Array<{ run_id: number; label: string; observed_products: number;
    scored_products: number; average_demand_score: number | null }>;
  page: number; page_size: number; total: number;
}
export interface DemandBackfillJob {
  id: number; status: "queued" | "running" | "completed" | "failed"; total_runs: number;
  processed_runs: number; products_scored: number; created_at: string; started_at: string | null;
  completed_at: string | null; error_message: string | null; already_active?: boolean;
}
