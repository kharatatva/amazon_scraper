import type {
  AnalyticsPoint, DashboardSnapshot, DemandBackfillJob, DemandTrackerData, HistoryPoint,
  Keyword, Niche, PageResult, Product, RunStatus, Schedule, ScrapeError, SearchRun,
} from "./domain";

export interface ProductFilters {
  page?: number; page_size?: number; search?: string; niche_id?: number; keyword_id?: number;
  seller_id?: number; brand?: string; fulfillment_type?: "FBA" | "FBM" | "Unknown";
  currency?: string; price_min?: number; price_max?: number; rating_min?: number; reviews_min?: number;
  sort?: string; order?: "asc" | "desc";
}
export interface RunFilters {
  page?: number; page_size?: number; niche_id?: number; keyword_id?: number;
  status?: RunStatus; start_date?: string; end_date?: string;
}
export type ScrapeStartPayload =
  | { nicheName: string; keywords: string[]; pages: number; products: number }
  | { nicheId: number; keywordId: number; pages: number; products: number; recurring: boolean; frequency: "daily" | "weekly" };

export interface ScraperSettingField {
  key: string;
  label: string;
  group: string;
  description: string;
  kind: "number" | "boolean" | "text" | "json";
  default: unknown;
  minimum?: number;
  maximum?: number;
  step?: number;
}

export interface ScraperSettingsData {
  settings: Record<string, unknown>;
  defaults: Record<string, unknown>;
  groups: string[];
  fields: ScraperSettingField[];
  system: Record<string, string>;
}

export type EnvironmentComponentStatus = "ready" | "missing" | "error" | "unknown";

export interface EnvironmentComponent {
  id: string;
  name: string;
  status: EnvironmentComponentStatus;
  required: boolean;
  message: string;
}

export interface EnvironmentSnapshot {
  ready: boolean;
  scraper_ready: boolean;
  checked_at: string;
  components: EnvironmentComponent[];
  issues: Array<{ id: string; name: string; message: string }>;
}

export interface EnvironmentOperation {
  id: string;
  status: "running" | "completed" | "failed";
  stage: string | null;
  progress: number;
  completed: number;
  total: number;
  message: string;
  error: string | null;
  updated_at: string;
  stages: Array<{
    id: string;
    name: string;
    status: "pending" | "running" | "ready" | "error";
    message: string;
  }>;
}

export interface EnvironmentResponse {
  environment: EnvironmentSnapshot;
  operation: EnvironmentOperation | null;
}

function queryString(values: Record<string, string | number | boolean | undefined | null>) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const result = params.toString();
  return result ? `?${result}` : "";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: { Accept: "application/json", ...(init?.body ? { "Content-Type": "application/json" } : {}), ...init?.headers },
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = await response.json() as { detail?: string };
      if (body.detail) message = body.detail;
    } catch { /* keep the HTTP status message */ }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export const api = {
  getDashboard: () => request<DashboardSnapshot>("/dashboard"),
  getNiches: (search?: string, keywordId?: number) => request<Niche[]>(`/niches${queryString({ search, keyword_id: keywordId })}`),
  getNiche: (id: number) => request<Niche & { product_count: number; run_count: number }>(`/niches/${id}`),
  getNicheRuns: (id: number, page = 1, pageSize = 25) => request<PageResult<SearchRun>>(`/niches/${id}/runs${queryString({ page, page_size: pageSize })}`),
  getProducts: (filters: ProductFilters = {}) => request<PageResult<Product>>(`/products${queryString({ ...filters })}`),
  getProduct: (id: number) => request<Product>(`/products/${id}`),
  getProductFilters: () => request<{ brands: string[]; fulfillment_types: string[]; sellers: Array<{ id: number; name: string }>; keywords: Keyword[]; currencies: string[] }>("/products/filters"),
  getSellers: (search?: string, page = 1, pageSize = 50) => request<PageResult<{ id: number; name: string; first_seen_at: string; product_count: number; niche_count: number }>>(`/sellers${queryString({ search, page, page_size: pageSize })}`),
  getSeller: (id: number, page = 1, pageSize = 50) => request<{ id: number; name: string; first_seen_at: string; product_count: number; products: PageResult<Product> }>(`/sellers/${id}${queryString({ page, page_size: pageSize })}`),
  getRuns: (filters: RunFilters = {}) => request<PageResult<SearchRun>>(`/runs${queryString({ ...filters })}`),
  getRun: (id: number) => request<SearchRun & { errors: ScrapeError[] }>(`/runs/${id}`),
  getErrors: (runId?: number, page = 1, pageSize = 50) => request<PageResult<ScrapeError>>(`/errors${queryString({ run_id: runId, page, page_size: pageSize })}`),
  getSchedules: () => request<Schedule[]>("/schedules"),
  getRunLogs: (id: number) => request<{ run_id: number; lines: string[] }>(`/runs/${id}/logs`),
  deleteSchedule: (id: number) => request<{ deleted: boolean }>(`/schedules/${id}`, { method: "DELETE" }),
  getDemand: (nicheId?: number, page = 1, pageSize = 100) => request<DemandTrackerData>(`/demand${queryString({ niche_id: nicheId, page, page_size: pageSize })}`),
  createDemandSchedule: (payload: { nicheId: number; keywordId: number; pages: number; products: number; runTimes: string; timezone?: string }) => request<{ id: number; active: boolean; runTimes: string; timezone: string }>("/demand/schedules", { method: "POST", body: JSON.stringify(payload) }),
  startDemandBackfill: () => request<DemandBackfillJob>("/demand/backfill", { method: "POST", body: JSON.stringify({}) }),
  getDemandBackfill: () => request<DemandBackfillJob | null>("/demand/backfill"),
  getScraperSettings: () => request<ScraperSettingsData>("/scraper/settings"),
  getEnvironment: () => request<EnvironmentResponse>("/environment"),
  checkEnvironment: () => request<EnvironmentResponse>("/environment/check", { method: "POST", body: JSON.stringify({}) }),
  initializeEnvironment: (repair = false) => request<EnvironmentResponse>("/environment/initialize", { method: "POST", body: JSON.stringify({ repair }) }),
  saveScraperSettings: (settings: Record<string, unknown>) => request<ScraperSettingsData>("/scraper/settings", { method: "PUT", body: JSON.stringify({ settings }) }),
  resetScraperSettings: () => request<ScraperSettingsData>("/scraper/settings/reset", { method: "POST", body: JSON.stringify({}) }),
  getHistory: (productId: number, nicheId?: number, startDate?: string, endDate?: string) => request<HistoryPoint[]>(`/products/${productId}/history${queryString({ niche_id: nicheId, start_date: startDate, end_date: endDate })}`),
  getAnalytics: (nicheId?: number, startDate?: string, endDate?: string, limit = 5000, currency?: string) => request<{
    items: AnalyticsPoint[]; total_returned: number; unique_products: number; scored_products: number;
    truncated: boolean; limit: number; currencies: string[];
    filters: { niche_id: number | null; start_date: string | null; end_date: string | null; currency: string | null };
    time_series: Array<{ label: string; observations: number; avg_rating: number | null; avg_review_count: number | null; avg_search_rank: number | null; avg_final_score: number | null }>;
    price_time_series: Array<{ label: string; currency: string | null; price_observations: number; avg_price: number | null }>;
    score_distributions: Record<string, Array<{ label: string; bucket: number; count: number }>>;
    fulfillment_distribution: Array<{ label: string; count: number }>;
    products_by_brand: Array<{ label: string; count: number }>;
    products_by_seller: Array<{ label: string; count: number }>;
    badges: Array<{ label: string; yes_count: number | null; no_count: number | null; unknown_count: number | null; total: number }>;
    images_vs_quality: Array<{ label: number; count: number; avg_rating: number | null; avg_final_score: number | null }>;
    bullets_vs_quality: Array<{ label: number; count: number; avg_rating: number | null; avg_final_score: number | null }>;
    search_rank_distribution: Array<{ bucket: number; count: number }>;
    bsr_by_category: Array<{ label: string; count: number; avg_rank: number; min_rank: number; max_rank: number }>;
    price_distribution: Array<{ currency: string; bucket: number; count: number }>;
    rating_distribution: Array<{ bucket: number; count: number }>;
    review_distribution: Array<{ label: string; count: number }>;
  }>(`/analytics${queryString({ niche_id: nicheId, start_date: startDate, end_date: endDate, limit, currency })}`),
  getKeywords: async (nicheId: number) => (await request<Niche>(`/niches/${nicheId}`)).keywords,
  startScrape: (payload: ScrapeStartPayload) => request<{ accepted: boolean; runId: number; runIds: number[] }>("/scrape/start", { method: "POST", body: JSON.stringify(payload) }),
};
