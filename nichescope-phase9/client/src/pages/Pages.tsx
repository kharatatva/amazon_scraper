import { useEffect, useState, type ReactNode } from "react";
import { Link, useLocation, useRoute } from "wouter";
import { Activity, AlertTriangle, Check, Clock3, Database, Download, ExternalLink, Gauge, Layers3, PackageCheck, Play, RefreshCw, Search, Server, Store, Target, TimerReset, XCircle } from "lucide-react";
import { toast } from "sonner";
import { useSettings } from "@/contexts/SettingsContext";
import { EmptyState, ErrorState, FilterBar, MetricCard, PageHeader, Panel, ProductGlyph, ProductTable, RunTable, ScoreChip, StatusPill } from "@/components/dashboard";
import { Visualization, chartMetric, type ChartRow, type VisualMetric } from "@/components/Visualization";
import { ProductComparison } from "@/components/ProductComparison";
import { api, type ProductFilters, type RunFilters } from "@/lib/api";
import type { DashboardSnapshot, DemandBackfillJob, DemandTrackerData, Niche, Product, RunStatus, Schedule, SearchRun } from "@/lib/domain";
import { formatCompact, formatCurrency, formatDate, formatNumber } from "@/lib/format";

function useRemote<T>(key: string, load: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    load().then((value) => { if (active) setData(value); })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason : new Error("Request failed")); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  // `key` contains every request argument; it avoids refetch loops from inline loaders.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, revision]);
  return { data, loading, error, retry: () => setRevision((value) => value + 1) };
}

function PageLoading() {
  return <div className="space-y-4" aria-label="Loading dashboard data"><div className="skeleton h-8 w-56" /><div className="skeleton h-20 w-full" /><div className="skeleton h-72 w-full" /></div>;
}

function RequestState<T>({ state, children }: { state: { data: T | null; loading: boolean; error: Error | null; retry: () => void }; children: (data: T) => ReactNode }) {
  if (state.error) return <ErrorState title={state.error.message} onRetry={state.retry} />;
  if (state.loading || !state.data) return <PageLoading />;
  return <>{children(state.data)}</>;
}

function Pagination({ page, pageSize, total, onChange }: { page: number; pageSize: number; total: number; onChange: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return <div className="flex items-center justify-between border-t border-white/[0.07] px-5 py-3 text-[11px] text-slate-500"><span>{total ? `${(page - 1) * pageSize + 1}–${Math.min(total, page * pageSize)} of ${formatNumber(total)}` : "0 results"}</span><div className="flex gap-2"><button className="secondary-button" disabled={page <= 1} onClick={() => onChange(page - 1)}>Previous</button><span className="self-center font-mono">{page} / {pages}</span><button className="secondary-button" disabled={page >= pages} onClick={() => onChange(page + 1)}>Next</button></div></div>;
}

function Select({ label, value, onChange, children, className = "" }: { label: string; value: string; onChange: (value: string) => void; children: React.ReactNode; className?: string }) {
  return <label className={`flex min-w-[150px] flex-col gap-1 text-[10px] font-medium uppercase tracking-[0.12em] text-slate-600 ${className}`}>{label}<select className="dark-select" value={value} onChange={(event) => onChange(event.target.value)}>{children}</select></label>;
}

function downloadCsv(rows: Array<Record<string, unknown>>, filename: string) {
  if (!rows.length) { toast.info("There are no rows to export."); return; }
  const keys = Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
  const quote = (value: unknown) => `"${String(value ?? "").replaceAll('"', '""')}"`;
  const text = [keys.map(quote).join(","), ...rows.map((row) => keys.map((key) => quote(row[key])).join(","))].join("\r\n");
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const anchor = document.createElement("a"); anchor.href = url; anchor.download = filename; anchor.click(); URL.revokeObjectURL(url);
}

export function OverviewPage() {
  const state = useRemote<DashboardSnapshot>("overview", () => api.getDashboard());
  const [, navigate] = useLocation();
  return <RequestState state={state}>{(data) => {
    const totals = data.totals;
    const statuses = (["success", "partial", "failed", "running"] as RunStatus[]).map((label) => ({ label, count: data.run_status.find((item) => item.label === label)?.count ?? 0 }));
    const scores = data.score_distribution.map((row) => ({ label: `${row.bucket}–${row.bucket + 9}`, count: row.count }));
    const prices = data.price_distribution.map((row) => ({ label: `${row.currency} ${row.bucket}–${row.bucket + 24}`, count: row.count, currency: row.currency }));
    return <>
      <div className="dev-banner mb-5"><Database size={13} /><span>SQLite data source</span><span className="hidden text-slate-600 sm:inline">·</span><span className="hidden text-slate-500 sm:inline">Configured project database · live read-only dashboard queries</span></div>
      <PageHeader eyebrow="Workspace / Overview" title="Database overview" description="A direct view of stored niches, products, snapshots, scores, and scraper runs." actions={<Link href="/scraper" className="primary-button"><Play size={14} fill="currentColor" /> Start a scrape</Link>} />
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <MetricCard label="Niches" value={formatNumber(totals.niches)} icon={Layers3} accent="cyan" />
        <MetricCard label="Unique products" value={formatNumber(totals.products)} icon={PackageCheck} accent="violet" />
        <MetricCard label="Sellers" value={formatNumber(totals.sellers)} icon={Store} accent="amber" />
        <MetricCard label="Search runs" value={formatNumber(totals.search_runs)} icon={Activity} accent="green" />
        <MetricCard label="Snapshots" value={formatNumber(totals.snapshots)} icon={Database} accent="cyan" detail="Observations, not unique products" />
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <MetricCard label="Successful runs" value={formatNumber(totals.successful_runs)} icon={Check} accent="green" />
        <MetricCard label="Partial runs" value={formatNumber(totals.partial_runs)} icon={AlertTriangle} accent="amber" />
        <MetricCard label="Failed runs" value={formatNumber(totals.failed_runs)} icon={XCircle} accent="amber" />
        <MetricCard label="Currently running" value={formatNumber(totals.running_runs)} icon={Activity} accent="cyan" />
        <MetricCard label="Products with scores" value={formatNumber(totals.scored_products)} icon={Gauge} accent="violet" detail="At least one scored snapshot" />
      </div>
      <div className="mt-5 grid gap-5 xl:grid-cols-2">
        <Visualization title="Search runs over time" description="Runs grouped by stored run date" data={data.runs_by_day.map((row) => ({ ...row, label: row.date }))} labelKey="label" metrics={[chartMetric.count]} types={["line", "area", "bar"]} initialType="line" onPointClick={(row) => navigate(`/runs?start_date=${String(row.date)}&end_date=${String(row.date)}`)} />
        <Visualization title="Run outcomes" description="One count per stored search run status" data={statuses} metrics={[chartMetric.count]} types={["bar", "horizontal", "donut"]} initialType="donut" onPointClick={(row) => navigate(`/runs?status=${String(row.label)}`)} />
        <Visualization title="Unique products by niche" description="Distinct product IDs through niche_products" data={data.products_by_niche} metrics={[chartMetric.count]} types={["bar", "horizontal", "donut"]} initialType="horizontal" onPointClick={(row) => navigate(`/niches/${String(row.id)}`)} />
        <Visualization title="Latest opportunity score distribution" description="Latest snapshot score per product; missing scores are excluded" data={scores} metrics={[chartMetric.count]} types={["bar", "horizontal", "line", "area"]} initialType="bar" />
        <Visualization title="Latest rating distribution" description="Latest non-null product rating observations" data={data.rating_distribution.map((row) => ({ label: row.bucket.toFixed(1), count: row.count }))} metrics={[chartMetric.count]} types={["bar", "horizontal", "line", "area"]} initialType="bar" />
        <Visualization title="Latest price distribution" description="Grouped by stored currency; fixed 25-unit bins" data={prices} metrics={[chartMetric.count]} types={["bar", "horizontal", "line", "area"]} initialType="bar" />
      </div>
      <Panel className="mt-5" title="Recent search runs" description="Current stage and task are shown as stored; no completion percentage is inferred" action={<Link href="/runs" className="text-xs text-cyan-300">All runs</Link>}><RunTable runs={data.recent_runs} limit={10} />{!data.recent_runs.length && <EmptyState title="No search runs yet" description="New pipeline executions will appear here when data has been collected." icon={Activity} />}</Panel>
      <Panel className="mt-5" title="Highest available opportunity scores" description="Score values belong to each product’s latest scored snapshot" action={<Link href="/opportunities" className="text-xs text-cyan-300">Open rankings</Link>}><div className="divide-y divide-white/[0.06]">{data.top_opportunities.map((item, index) => <Link href={`/products/${item.id}`} key={item.id} className="flex items-center gap-3 px-5 py-3"><span className="font-mono text-[10px] text-slate-600">{String(index + 1).padStart(2, "0")}</span><div className="min-w-0 flex-1"><p className="product-name truncate text-slate-200">{item.title ?? "Title unavailable"}</p><p className="mt-1 text-[10px] text-slate-600">{item.brand ?? "Brand unavailable"} · {item.asin}</p></div><ScoreChip score={item.final_score} /></Link>)}{!data.top_opportunities.length && <EmptyState title="No opportunity scores yet" description="Scores will appear here when stored for product snapshots." icon={Gauge} />}</div></Panel>
    </>;
  }}</RequestState>;
}

export function NichesPage() {
  const [search, setSearch] = useState(""); const [keywordId, setKeywordId] = useState("");
  const filters = useRemote("niche-filters", () => api.getProductFilters());
  const key = JSON.stringify([search, keywordId]);
  const state = useRemote<Niche[]>(key, () => api.getNiches(search, keywordId ? Number(keywordId) : undefined));
  return <><PageHeader eyebrow="Workspace / Niches" title="Niche explorer" description="Browse recorded niche metadata, explicit keyword associations, products, and scraping history." />
    <div className="filter-bar"><input className="input-search min-w-0 flex-1" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search niche name or slug" aria-label="Search niches" /><select className="filter-select" value={keywordId} onChange={(event) => setKeywordId(event.target.value)} aria-label="Filter by associated keyword"><option value="">All keywords</option>{filters.data?.keywords.map((keyword) => <option key={keyword.id} value={keyword.id}>{keyword.text}</option>)}</select><button className="secondary-button" onClick={() => { setSearch(""); setKeywordId(""); }}>Reset</button></div>
    <RequestState state={state}>{(niches) => <Panel className="mt-5" title={`${niches.length} niches`} description="Keyword/product counts use their explicit linking tables"><div className="data-table-wrap"><table className="data-table"><thead><tr><th>Niche</th><th>Keywords</th><th>Products</th><th>Sellers</th><th>Created</th><th>Last scraped</th><th /></tr></thead><tbody>{niches.map((niche) => <tr key={niche.id} className="group"><td><Link href={`/niches/${niche.id}`} className="block"><p className="text-xs font-medium text-slate-200 group-hover:text-cyan-300">{niche.name}</p><p className="mt-1 font-mono text-[10px] text-slate-600">{niche.slug}</p></Link></td><td className="max-w-[240px] whitespace-normal text-xs text-slate-400">{niche.keywords.map((item) => item.text).join(", ") || "None associated"}</td><td className="font-mono text-xs">{formatNumber(niche.product_count)}</td><td className="font-mono text-xs">{formatNumber(niche.seller_count)}</td><td className="text-[11px]">{formatDate(niche.created_at)}</td><td className="text-[11px]">{formatDate(niche.last_scraped_at)}</td><td><Link href={`/niches/${niche.id}`} className="text-cyan-300">Open</Link></td></tr>)}</tbody></table>{!niches.length && <EmptyState title="No niches found" description="Clear the filters or add data through the existing scraper pipeline." icon={Search} />}</div></Panel>}</RequestState>
  </>;
}

export function NicheDetailPage() {
  const [, params] = useRoute("/niches/:id"); const id = Number(params?.id);
  const [productPage, setProductPage] = useState(1); const [runPage, setRunPage] = useState(1);
  const nicheState = useRemote(`niche:${id}`, () => api.getNiche(id));
  const productState = useRemote(`niche-products:${id}:${productPage}`, () => api.getProducts({ niche_id: id, page: productPage, page_size: 25 }));
  const runState = useRemote(`niche-runs:${id}:${runPage}`, () => api.getNicheRuns(id, runPage));
  return <><Link href="/niches" className="back-link">← All niches</Link><RequestState state={nicheState}>{(niche) => <>
    <PageHeader eyebrow="Niche detail" title={niche.name} description={`${niche.slug} · created ${formatDate(niche.created_at)} · last scraped ${formatDate(niche.last_scraped_at)}`} actions={<Link href={`/products?niche_id=${id}`} className="secondary-button">Explore products</Link>} />
    <div className="grid gap-3 sm:grid-cols-3"><MetricCard label="Associated keywords" value={formatNumber(niche.keywords.length)} icon={Search} accent="cyan" /><MetricCard label="Unique products" value={formatNumber(niche.product_count)} icon={PackageCheck} accent="violet" /><MetricCard label="Search runs" value={formatNumber(niche.run_count)} icon={Activity} accent="green" /></div>
    <Panel className="mt-5" title="Associated keywords" description="Only niche_keywords relationships are shown"><div className="flex flex-wrap gap-2 p-5">{niche.keywords.map((keyword) => <span className="fulfillment-badge" key={keyword.id}>{keyword.text}</span>)}{!niche.keywords.length && <p className="text-xs text-slate-500">No keywords are linked to this niche.</p>}</div></Panel>
    <Panel className="mt-5" title="Latest product observations" description="Each product uses its latest parsed_at value, with snapshot ID as a deterministic tie-breaker">{productState.error ? <ErrorState title={productState.error.message} onRetry={productState.retry} /> : productState.loading || !productState.data ? <PageLoading /> : <><ProductTable products={productState.data.items} />{!productState.data.items.length && <EmptyState title="No associated products" description="Products are linked through niche_products when the pipeline stores an observation." icon={PackageCheck} />}<Pagination page={productState.data.page} pageSize={productState.data.page_size} total={productState.data.total} onChange={setProductPage} /></>}</Panel>
    <Panel className="mt-5" title="Search runs" description="Runs belong to their stored niche and keyword IDs">{runState.error ? <ErrorState title={runState.error.message} onRetry={runState.retry} /> : runState.loading || !runState.data ? <PageLoading /> : <><RunTable runs={runState.data.items} />{!runState.data.items.length && <EmptyState title="No runs for this niche" description="Run history will appear once scraping begins." icon={Activity} />}<Pagination page={runState.data.page} pageSize={runState.data.page_size} total={runState.data.total} onChange={setRunPage} /></>}</Panel>
  </>}</RequestState></>;
}

export function ProductsPage() {
  const [search, setSearch] = useState(""); const [nicheId, setNicheId] = useState(() => new URLSearchParams(window.location.search).get("niche_id") ?? ""); const [keywordId, setKeywordId] = useState(() => new URLSearchParams(window.location.search).get("keyword_id") ?? "");
  const [sellerId, setSellerId] = useState(""); const [brand, setBrand] = useState(""); const [fulfillment, setFulfillment] = useState(""); const [priceCurrency, setPriceCurrency] = useState("");
  const [priceMin, setPriceMin] = useState(""); const [priceMax, setPriceMax] = useState(""); const [ratingMin, setRatingMin] = useState(""); const [reviewsMin, setReviewsMin] = useState("");
  const [sort, setSort] = useState("first_seen_at"); const [order, setOrder] = useState<"asc" | "desc">("desc"); const [page, setPage] = useState(1); const [exporting, setExporting] = useState(false);
  const filterOptions = useRemote("product-filter-options", () => api.getProductFilters());
  const nicheState = useRemote("product-niches", () => api.getNiches());
  const filters: ProductFilters = { page, page_size: 25, search: search || undefined, niche_id: nicheId ? Number(nicheId) : undefined, keyword_id: keywordId ? Number(keywordId) : undefined, seller_id: sellerId ? Number(sellerId) : undefined, brand: brand || undefined, fulfillment_type: fulfillment ? fulfillment as "FBA" | "FBM" | "Unknown" : undefined, currency: priceCurrency || undefined, price_min: priceMin ? Number(priceMin) : undefined, price_max: priceMax ? Number(priceMax) : undefined, rating_min: ratingMin ? Number(ratingMin) : undefined, reviews_min: reviewsMin ? Number(reviewsMin) : undefined, sort, order };
  const key = JSON.stringify(filters); const state = useRemote(key, () => api.getProducts(filters));
  useEffect(() => { setPage(1); }, [search, nicheId, keywordId, sellerId, brand, fulfillment, priceCurrency, priceMin, priceMax, ratingMin, reviewsMin, sort, order]);
  async function exportAll() {
    setExporting(true);
    try {
      const all: Product[] = [];
      const first = await api.getProducts({ ...filters, page: 1, page_size: 100 }); all.push(...first.items);
      for (let current = 2; all.length < first.total; current++) {
        const part = await api.getProducts({ ...filters, page: current, page_size: 100 }); all.push(...part.items);
        if (!part.items.length) break;
      }
      downloadCsv(all.map((product) => ({ asin: product.asin, title: product.title, brand: product.brand, seller: product.seller_name, fulfillment_type: product.fulfillment_type, category: product.category_path.join(" / "), product_url: product.product_url, first_seen_at: product.first_seen_at, niche_names: product.niches.map((item) => item.name).join(" | "), price: product.current?.price, currency: product.current?.currency, rating: product.current?.rating, review_count: product.current?.review_count, bsr: JSON.stringify(product.current?.bsr), search_rank_position: product.current?.search_rank_position, is_sponsored: product.current?.is_sponsored, is_amazons_choice: product.current?.is_amazons_choice, is_best_seller: product.current?.is_best_seller, images_count: product.current?.images_count, bullet_points_count: product.current?.bullet_points_count, has_a_plus_content: product.current?.has_a_plus_content, variant_count: product.current?.variant_count, demand_score: product.current?.opportunity?.demand_score, competition_score: product.current?.opportunity?.competition_score, quality_gap_score: product.current?.opportunity?.quality_gap_score, final_score: product.current?.opportunity?.final_score })), "nichescope-products.csv");
    } catch (error) { toast.error(error instanceof Error ? error.message : "Export failed"); }
    finally { setExporting(false); }
  }
  return <><PageHeader eyebrow="Workspace / Products" title="Product explorer" description="Search and filter stable product attributes alongside the latest available snapshot. Historical observations are on each product detail page." actions={<button className="secondary-button" disabled={exporting} onClick={() => void exportAll()}><Download size={14} /> {exporting ? "Preparing CSV…" : "Export filtered results"}</button>} />
    <div className="panel mb-4 grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-5">
      <label className="sm:col-span-2"><span className="field-label">Search</span><input className="dark-input" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="ASIN, title, brand, seller" /></label>
      <Select label="Niche" value={nicheId} onChange={setNicheId}><option value="">All niches</option>{nicheState.data?.map((niche) => <option key={niche.id} value={niche.id}>{niche.name}</option>)}</Select>
      <Select label="Keyword" value={keywordId} onChange={setKeywordId}><option value="">All keywords</option>{filterOptions.data?.keywords.map((keyword) => <option key={keyword.id} value={keyword.id}>{keyword.text}</option>)}</Select>
      <Select label="Seller" value={sellerId} onChange={setSellerId}><option value="">All sellers</option>{filterOptions.data?.sellers.map((seller) => <option key={seller.id} value={seller.id}>{seller.name}</option>)}</Select>
      <Select label="Brand" value={brand} onChange={setBrand}><option value="">All brands</option>{filterOptions.data?.brands.map((item) => <option key={item} value={item}>{item}</option>)}</Select>
      <Select label="Fulfillment" value={fulfillment} onChange={setFulfillment}><option value="">All types</option>{filterOptions.data?.fulfillment_types.map((item) => <option key={item} value={item}>{item}</option>)}</Select>
      <Select label="Price currency" value={priceCurrency} onChange={setPriceCurrency}><option value="">All currencies</option>{filterOptions.data?.currencies.map((item) => <option key={item} value={item}>{item}</option>)}</Select>
      <label><span className="field-label">Price minimum</span><input className="dark-input" inputMode="decimal" type="number" min="0" value={priceMin} onChange={(event) => setPriceMin(event.target.value)} /></label>
      <label><span className="field-label">Price maximum</span><input className="dark-input" inputMode="decimal" type="number" min="0" value={priceMax} onChange={(event) => setPriceMax(event.target.value)} /></label>
      <label><span className="field-label">Rating at least</span><input className="dark-input" type="number" min="0" max="5" step="0.1" value={ratingMin} onChange={(event) => setRatingMin(event.target.value)} /></label>
      <label><span className="field-label">Reviews at least</span><input className="dark-input" type="number" min="0" value={reviewsMin} onChange={(event) => setReviewsMin(event.target.value)} /></label>
      <Select label="Sort by" value={sort} onChange={setSort}><option value="first_seen_at">First seen</option><option value="title">Title</option><option value="asin">ASIN</option><option value="price">Latest price</option><option value="rating">Latest rating</option><option value="review_count">Review count</option><option value="search_rank_position">Search rank</option><option value="final_score">Opportunity score</option></Select>
      <Select label="Sort order" value={order} onChange={(value) => setOrder(value as "asc" | "desc")}><option value="desc">Descending</option><option value="asc">Ascending</option></Select>
      <button className="secondary-button self-end" onClick={() => { setSearch(""); setNicheId(""); setKeywordId(""); setSellerId(""); setBrand(""); setFulfillment(""); setPriceCurrency(""); setPriceMin(""); setPriceMax(""); setRatingMin(""); setReviewsMin(""); setSort("first_seen_at"); setOrder("desc"); }}>Reset filters</button>
      {(priceMin || priceMax) && !priceCurrency && (filterOptions.data?.currencies.length ?? 0) > 1 && <p className="col-span-full text-[11px] text-amber-200">Choose a currency before applying price bounds across markets.</p>}
    </div>
    <RequestState state={state}>{(result) => <Panel title={`${formatNumber(result.total)} products`} description={`Page ${result.page} · latest parsed observation only`}><ProductTable products={result.items} />{!result.items.length && <EmptyState title="No products match these filters" description="Change or reset the filters. Missing snapshot measurements stay blank." icon={PackageCheck} />}<Pagination page={result.page} pageSize={result.page_size} total={result.total} onChange={setPage} /></Panel>}</RequestState>
  </>;
}

export function ProductDetailPage() {
  const [, params] = useRoute("/products/:id"); const id = Number(params?.id);
  const productState = useRemote(`product:${id}`, () => api.getProduct(id));
  const historyState = useRemote(`product-history:${id}`, () => api.getHistory(id));
  const [metricKey, setMetricKey] = useState("price"); const [nicheId, setNicheId] = useState(""); const [historyCurrency, setHistoryCurrency] = useState(""); const [bsrCategory, setBsrCategory] = useState("");
  if (productState.error) return <><Link href="/products" className="back-link">← Products</Link><ErrorState title={productState.error.message} onRetry={productState.retry} /></>;
  if (productState.loading || !productState.data) return <PageLoading />;
  const product = productState.data; const snapshot = product.current;
  const readBsr = (value: unknown): Array<{ rank: number; category: string }> => Array.isArray(value) ? value.flatMap((entry) => {
    if (!entry || typeof entry !== "object") return [];
    const rank = (entry as { rank?: unknown }).rank; const category = (entry as { category?: unknown }).category;
    return typeof rank === "number" && typeof category === "string" ? [{ rank, category }] : [];
  }) : [];
  const historyCurrencies = Array.from(new Set((historyState.data ?? []).filter((point) => point.price != null).map((point) => point.currency ?? "Unknown"))).sort();
  const bsrCategories = Array.from(new Set((historyState.data ?? []).flatMap((point) => readBsr(point.bsr).map((item) => item.category)))).sort();
  const history = (historyState.data ?? []).map((point) => {
    const entries = readBsr(point.bsr);
    const selectedBsr = bsrCategory ? entries.find((entry) => entry.category === bsrCategory) : bsrCategories.length <= 1 ? entries[0] : undefined;
    return { label: point.parsed_at, price: point.price, currency: point.currency, rating: point.rating, review_count: point.review_count, search_rank_position: point.search_rank_position, bsr_rank: selectedBsr?.rank ?? null, bsr_category: selectedBsr?.category ?? null, demand_score: point.opportunity?.demand_score, competition_score: point.opportunity?.competition_score, quality_gap_score: point.opportunity?.quality_gap_score, final_score: point.opportunity?.final_score, niche_name: point.niche_name, search_run_id: point.search_run_id };
  });
  const historicalMetricOptions: VisualMetric[] = [
    { ...chartMetric.price, types: ["line", "area", "bar"] },
    { ...chartMetric.rating, types: ["line", "area", "bar"] },
    { ...chartMetric.reviews, types: ["line", "area", "bar"] },
    { key: "search_rank_position", label: "Search rank position", format: "number", types: ["line", "area", "bar"] },
    { key: "bsr_rank", label: "BSR rank position", format: "number", types: ["line", "area", "bar"] },
    { key: "demand_score", label: "Demand score", format: "score", types: ["line", "area", "bar"] },
    { key: "competition_score", label: "Competition score", format: "score", types: ["line", "area", "bar"] },
    { key: "quality_gap_score", label: "Quality-gap score", format: "score", types: ["line", "area", "bar"] },
    { ...chartMetric.score, types: ["line", "area", "bar"] },
  ];
  const scopedHistory = nicheId ? history.filter((point) => point.niche_name === product.niches.find((item) => item.id === Number(nicheId))?.name) : history;
  const filteredHistory = scopedHistory.map((point) => ({
    ...point,
    price: historyCurrencies.length > 1 && (!historyCurrency || (point.currency ?? "Unknown") !== historyCurrency) ? null : point.price,
    bsr_rank: bsrCategories.length > 1 && (!bsrCategory || point.bsr_category !== bsrCategory) ? null : point.bsr_rank,
  }));
  return <><Link href="/products" className="back-link">← Product explorer</Link><PageHeader eyebrow="Product detail" title={product.title ?? product.asin} description={`${product.asin} · first seen ${formatDate(product.first_seen_at)} · latest snapshot ${formatDate(snapshot?.parsed_at)}`} actions={product.product_url ? <a className="secondary-button" href={product.product_url} target="_blank" rel="noreferrer"><ExternalLink size={13} /> Open product page</a> : undefined} />
    <section className="product-detail-hero"><div className="flex flex-wrap items-center gap-4"><ProductGlyph product={product} size="lg" /><div className="min-w-[220px] flex-1"><p className="font-mono text-[10px] uppercase tracking-[0.18em] text-cyan-300">{product.asin}</p><h2 className="mt-1 text-lg font-semibold text-white">{product.title ?? "Title unavailable"}</h2><p className="mt-1 text-xs text-slate-500">{product.brand ?? "Brand unavailable"} · {product.seller_name ?? "Seller unavailable"} · {product.fulfillment_type ?? "Fulfillment unknown"}</p><p className="mt-2 text-[11px] text-slate-600">{product.category_path.join(" / ") || "Category unavailable"}</p></div></div><div className="mt-4 flex flex-wrap gap-2">{product.niches.map((niche) => <Link className="fulfillment-badge" key={niche.id} href={`/niches/${niche.id}`}>{niche.name}</Link>)}</div></section>
    <div className="mt-5 space-y-5"><div className="space-y-5"><Panel title="Latest recorded snapshot" description="Snapshot values are time-varying; stable product fields are shown above"><div className="grid grid-cols-2 gap-px overflow-hidden bg-white/[0.07] sm:grid-cols-4">{[["Price", snapshot?.price === null || snapshot?.price === undefined ? "N/A" : formatCurrency(snapshot.price, snapshot.currency)], ["Rating", snapshot?.rating?.toFixed(1) ?? "N/A"], ["Review count", snapshot?.review_count === null || snapshot?.review_count === undefined ? "N/A" : formatCompact(snapshot.review_count)], ["Search rank", snapshot?.search_rank_position ?? "N/A"], ["Sponsored", snapshot?.is_sponsored == null ? "Unknown" : snapshot.is_sponsored ? "Yes" : "No"], ["Amazon’s Choice", snapshot?.is_amazons_choice == null ? "Unknown" : snapshot.is_amazons_choice ? "Yes" : "No"], ["Best Seller", snapshot?.is_best_seller == null ? "Unknown" : snapshot.is_best_seller ? "Yes" : "No"], ["Snapshot date", formatDate(snapshot?.parsed_at)]].map(([label, value]) => <div key={String(label)} className="min-w-0 bg-[#111820] p-3 sm:p-4"><p className="break-words text-[10px] uppercase tracking-[0.12em] text-slate-600">{label}</p><p className="mt-2 break-words text-[13px] font-medium text-slate-200">{value}</p></div>)}</div></Panel>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{[["Demand", snapshot?.opportunity?.demand_score], ["Competition", snapshot?.opportunity?.competition_score], ["Quality gap", snapshot?.opportunity?.quality_gap_score], ["Final score", snapshot?.opportunity?.final_score]].map(([label, score]) => <div className="metric-card" key={String(label)}><p className="text-[10px] uppercase tracking-[0.12em] text-slate-500">{label}</p><div className="mt-3"><ScoreChip score={typeof score === "number" ? score : null} large /></div></div>)}</div>
      {historyState.loading ? <PageLoading /> : historyState.error ? <ErrorState title={historyState.error.message} onRetry={historyState.retry} /> : (<Visualization title="Historical observations" description={metricKey === "price" && historyCurrencies.length > 1 ? (historyCurrency ? `Chronological ${historyCurrency} observations; null values remain gaps.` : "Select a currency to avoid combining prices from different currencies.") : metricKey === "bsr_rank" && bsrCategories.length > 1 ? (bsrCategory ? `Chronological BSR for ${bsrCategory}; null values remain gaps.` : "Select a BSR category before comparing rank positions.") : "Chronological snapshots; null values remain gaps and are not interpolated"} data={filteredHistory} labelKey="label" metrics={historicalMetricOptions} initialMetric={metricKey} initialType="line" types={["line", "area", "bar"]} height={360} onMetricChange={setMetricKey} onPointClick={(row) => toast.info(`Run #${row.search_run_id} | ${row.niche_name}`)} />)}
      <div className="grid gap-3 sm:grid-cols-2"><Select label="Niche scope" value={nicheId} onChange={setNicheId}><option value="">All recorded niches</option>{product.niches.map((niche) => <option key={niche.id} value={niche.id}>{niche.name}</option>)}</Select>{metricKey === "price" && historyCurrencies.length > 1 && <Select label="Price currency" value={historyCurrency} onChange={setHistoryCurrency}><option value="">Choose currency</option>{historyCurrencies.map((currency) => <option key={currency} value={currency}>{currency}</option>)}</Select>}{metricKey === "bsr_rank" && bsrCategories.length > 1 && <Select label="BSR category" value={bsrCategory} onChange={setBsrCategory}><option value="">Choose category</option>{bsrCategories.map((category) => <option key={category} value={category}>{category}</option>)}</Select>}</div>
    </div>
    <div className="space-y-5"><Panel title="Listing details" description="Fields are taken from the latest available snapshot"><div className="grid grid-cols-2 gap-px bg-white/[0.07] sm:grid-cols-3 lg:grid-cols-6">{[["Images", snapshot?.images_count], ["Bullet points", snapshot?.bullet_points_count], ["A+ content", snapshot?.has_a_plus_content == null ? null : snapshot.has_a_plus_content ? "Yes" : "No"], ["Variants", snapshot?.variant_count], ["BSR", snapshot?.bsr ? JSON.stringify(snapshot.bsr) : null], ["Weight / dimensions", snapshot?.weight_and_dimensions]].map(([label, value]) => <div key={String(label)} className="bg-[#111820] p-3"><p className="text-[10px] text-slate-600">{label}</p><p className="mt-1 break-words text-xs text-slate-300">{value === null || value === undefined ? "Unavailable" : String(value)}</p></div>)}</div></Panel>
        <Panel title="Observation history" description="Each row is tied to its source run and niche"><div className="data-table-wrap"><table className="data-table"><thead><tr><th>Parsed at</th><th>Niche</th><th>Run</th><th>Price</th><th>Rating</th><th>Reviews</th><th>BSR</th><th>Opportunity scores</th></tr></thead><tbody>{historyState.loading && <tr><td colSpan={8} className="p-4 text-xs text-slate-500">Loading observation history...</td></tr>}{(historyState.data ?? []).map((row) => { const bsr = readBsr(row.bsr)[0]; return <tr key={row.id}><td>{formatDate(row.parsed_at, true)}</td><td>{row.niche_name}</td><td><Link className="text-cyan-300" href={`/runs/${row.search_run_id}`}>#{row.search_run_id}</Link></td><td>{row.price == null ? "N/A" : formatCurrency(row.price, row.currency)}</td><td>{row.rating ?? "N/A"}</td><td>{row.review_count == null ? "N/A" : formatCompact(row.review_count)}</td><td>{bsr ? `#${formatCompact(bsr.rank)} ${bsr.category}` : "N/A"}</td><td><div className="grid min-w-[220px] grid-cols-2 gap-1.5">{[["Demand", row.opportunity?.demand_score], ["Competition", row.opportunity?.competition_score], ["Quality gap", row.opportunity?.quality_gap_score], ["Final", row.opportunity?.final_score]].map(([label, score]) => <div key={String(label)} className="flex min-w-0 flex-col items-start gap-1 rounded-md border border-white/[0.06] bg-white/[0.025] px-2 py-1.5"><span className="text-[9px] font-medium uppercase tracking-[0.08em] text-slate-500">{label}</span><ScoreChip score={typeof score === "number" ? score : null} /></div>)}</div></td></tr>; })}</tbody></table>{historyState.error && <p className="p-4 text-xs text-rose-300">{historyState.error.message}</p>}{!historyState.loading && !historyState.error && !historyState.data?.length && <EmptyState title="No historical observations" description="A trend will appear after this product has multiple stored snapshots." icon={TimerReset} />}</div></Panel>
      </div></div>
  </>;
}

export function SellersPage() {
  const [search, setSearch] = useState(""); const [page, setPage] = useState(1); const state = useRemote(`sellers:${search}:${page}`, () => api.getSellers(search, page));
  useEffect(() => { setPage(1); }, [search]);
  return <><PageHeader eyebrow="Workspace / Sellers" title="Seller explorer" description="Seller counts use distinct product and niche relationships." /><FilterBar search={search} onSearch={setSearch} placeholder="Search seller names" /><RequestState state={state}>{(result) => <Panel className="mt-5" title={`${formatNumber(result.total)} sellers`} description="Stable seller records"><div className="data-table-wrap"><table className="data-table"><thead><tr><th>Seller</th><th>Products</th><th>Niches</th><th>First seen</th><th /></tr></thead><tbody>{result.items.map((seller) => <tr key={seller.id}><td><Link href={`/sellers/${seller.id}`} className="text-xs text-slate-200 hover:text-cyan-300">{seller.name}</Link></td><td>{formatNumber(seller.product_count)}</td><td>{formatNumber(seller.niche_count)}</td><td>{formatDate(seller.first_seen_at)}</td><td><Link href={`/sellers/${seller.id}`} className="text-cyan-300">Open</Link></td></tr>)}</tbody></table>{!result.items.length && <EmptyState title="No sellers found" description="Seller records appear when scraper data includes seller names." icon={Store} />}</div><Pagination page={result.page} pageSize={result.page_size} total={result.total} onChange={setPage} /></Panel>}</RequestState></>;
}

export function SellerDetailPage() {
  const [, params] = useRoute("/sellers/:id"); const id = Number(params?.id); const [page, setPage] = useState(1); const state = useRemote(`seller:${id}:${page}`, () => api.getSeller(id, page));
  return <><Link href="/sellers" className="back-link">← Sellers</Link><RequestState state={state}>{(seller) => <><PageHeader eyebrow="Seller detail" title={seller.name} description={`First seen ${formatDate(seller.first_seen_at)} · ${formatNumber(seller.product_count)} associated products`} /><Panel title="Seller products" description="Products with their latest available observations"><ProductTable products={seller.products.items} />{!seller.products.items.length && <EmptyState title="No products for this seller" description="No product relationship is recorded." icon={PackageCheck} />}<Pagination page={seller.products.page} pageSize={seller.products.page_size} total={seller.products.total} onChange={setPage} /></Panel></>}</RequestState></>;
}

export function AnalyticsPage() {
  const [nicheId, setNicheId] = useState(""); const [startDate, setStartDate] = useState(""); const [endDate, setEndDate] = useState(""); const [currency, setCurrency] = useState("");
  const niches = useRemote("analytics-niches", () => api.getNiches()); const key = JSON.stringify([nicheId, startDate, endDate]);
  const state = useRemote(key, () => api.getAnalytics(nicheId ? Number(nicheId) : undefined, startDate || undefined, endDate || undefined));
  return <><PageHeader eyebrow="Workspace / Analytics" title="Market analytics" description="Explore stored observations and scoring components. These metrics describe scraped data, not revenue or profit." />
    <div className="panel mb-5 grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-5"><Select label="Niche" value={nicheId} onChange={setNicheId}><option value="">All niches</option>{niches.data?.map((niche) => <option key={niche.id} value={niche.id}>{niche.name}</option>)}</Select><label><span className="field-label">From date</span><input type="date" className="dark-input" value={startDate} onChange={(event) => setStartDate(event.target.value)} /></label><label><span className="field-label">To date</span><input type="date" className="dark-input" value={endDate} onChange={(event) => setEndDate(event.target.value)} /></label><Select label="Price currency" value={currency} onChange={setCurrency}><option value="">All currencies</option>{state.data?.currencies.map((item) => <option key={item} value={item}>{item}</option>)}</Select><button className="secondary-button self-end" onClick={() => { setNicheId(""); setStartDate(""); setEndDate(""); setCurrency(""); }}>Reset filters</button></div>
    <RequestState state={state}>{(result) => {
      const rows = result.items;
      const multipleCurrencies = result.currencies.length > 1;
      const scatterRows: ChartRow[] = rows.filter((row) => !currency || (row.currency ?? "Unknown") === currency).map((row) => ({ snapshot_id: row.snapshot_id, product_id: row.product_id, asin: row.asin, label: row.asin, price: multipleCurrencies && !currency ? null : row.price, currency: row.currency ?? "Unknown", rating: row.rating, review_count: row.review_count, search_rank_position: row.search_rank_position, demand_score: row.demand_score, competition_score: row.competition_score, quality_gap_score: row.quality_gap_score, final_score: row.final_score }));
      const priceCurrency = currency || (result.currencies.length === 1 ? result.currencies[0] : "");
      const dailyPrice = new Map(result.price_time_series.filter((row) => !priceCurrency || (row.currency ?? "Unknown") === priceCurrency).map((row) => [row.label, row.avg_price]));
      const timeRows: ChartRow[] = result.time_series.map((row) => ({ ...row, avg_price: multipleCurrencies && !priceCurrency ? null : (dailyPrice.get(row.label) ?? null), currency: priceCurrency }));
      const latestProductSnapshots = new Map<number, typeof rows[number]>();
      for (const row of rows) {
        const previous = latestProductSnapshots.get(row.product_id);
        if (!previous || row.parsed_at > previous.parsed_at || (row.parsed_at === previous.parsed_at && row.snapshot_id > previous.snapshot_id)) latestProductSnapshots.set(row.product_id, row);
      }
      const topProductsByScore = Array.from(latestProductSnapshots.values()).filter((row) => row.final_score !== null).sort((a, b) => (b.final_score ?? 0) - (a.final_score ?? 0)).slice(0, 10).map((row) => ({ product_id: row.product_id, label: row.asin, final_score: row.final_score }));
      const selectedPoint = (row: ChartRow) => { const productId = Number(row.product_id); if (productId) window.location.assign(`/products/${productId}`); };
      const badges = result.badges.flatMap((item) => [
        { label: `${item.label} · Yes`, count: item.yes_count ?? 0 },
        { label: `${item.label} · No`, count: item.no_count ?? 0 },
        { label: `${item.label} · Unknown`, count: item.unknown_count ?? 0 },
      ]);
      const metrics: VisualMetric[] = [
        { key: "avg_price", label: "Average price", format: "currency", currencyKey: "currency", types: ["line", "area", "bar"] },
        { key: "avg_rating", label: "Average rating", format: "rating", types: ["line", "area", "bar"] },
        { key: "avg_review_count", label: "Average review count", format: "number", types: ["line", "area", "bar"] },
        { key: "avg_search_rank", label: "Average search rank", format: "number", types: ["line", "area", "bar"] },
        { key: "avg_final_score", label: "Average final score", format: "score", types: ["line", "area", "bar"] },
        { key: "observations", label: "Snapshots", format: "number", types: ["line", "area", "bar"] },
      ];
      const yMetrics: VisualMetric[] = [
        { ...chartMetric.price }, { ...chartMetric.rating }, { ...chartMetric.reviews },
        { key: "demand_score", label: "Demand score", format: "score", types: ["scatter"] },
        { key: "competition_score", label: "Competition score", format: "score", types: ["scatter"] },
        { key: "quality_gap_score", label: "Quality-gap score", format: "score", types: ["scatter"] },
        { ...chartMetric.score },
      ];
      const xMetrics: VisualMetric[] = [...yMetrics];
      const qualityMetrics: VisualMetric[] = [chartMetric.count, { ...chartMetric.rating }, { ...chartMetric.score, types: ["line", "area", "bar", "horizontal"] }];
      return <>
        <div className="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><MetricCard label="Snapshots in range" value={formatNumber(result.total_returned)} icon={Database} accent="cyan" detail={result.truncated ? `Showing first ${formatNumber(result.limit)} rows in the table` : "Historical records in selected scope"} /><MetricCard label="Scored products" value={formatNumber(result.scored_products)} icon={Gauge} accent="violet" detail="Products with a scored snapshot in range" /><MetricCard label="Price observations" value={formatNumber(rows.filter((row) => row.price != null).length)} icon={Activity} accent="amber" detail="Within the returned observation set" /><MetricCard label="Unique products" value={formatNumber(result.unique_products)} icon={PackageCheck} accent="green" /></div>
        {result.truncated && <div className="mb-4 rounded-lg border border-amber-300/20 bg-amber-300/5 p-3 text-xs text-amber-200">This view is capped at {formatNumber(result.limit)} chronological snapshots. Narrow by niche or date to explore more precisely.</div>}
        <div className="grid gap-5 xl:grid-cols-2"><Visualization title="Observation metrics over time" description="Daily averages use recorded non-null values; choose a currency above for price." data={timeRows} labelKey="label" metrics={metrics} initialMetric="avg_rating" initialType="line" types={["line", "area", "bar"]} /><Visualization title="Metric relationships" description="Each point is one stored snapshot. Select metrics for both axes and open a product from a point." data={scatterRows} labelKey="label" metrics={yMetrics} xMetrics={xMetrics} types={["scatter"]} initialMetric="rating" initialType="scatter" onPointClick={selectedPoint} />
          <Visualization title="Demand score distribution" description="Stored demand scores, in ten-point bins" data={result.score_distributions.demand_score} metrics={[chartMetric.count]} types={["bar", "horizontal", "line", "area"]} /><Visualization title="Competition score distribution" description="Stored competition scores, in ten-point bins" data={result.score_distributions.competition_score} metrics={[chartMetric.count]} types={["bar", "horizontal", "line", "area"]} />
          <Visualization title="Quality-gap score distribution" description="Stored quality-gap scores, in ten-point bins" data={result.score_distributions.quality_gap_score} metrics={[chartMetric.count]} types={["bar", "horizontal", "line", "area"]} /><Visualization title="Final score distribution" description="Stored final scores, in ten-point bins" data={result.score_distributions.final_score} metrics={[chartMetric.count]} types={["bar", "horizontal", "line", "area"]} />
          <Visualization title="Price distribution" description="Latest product snapshots in 25-unit bins, separated by selected currency" data={result.price_distribution.filter((row) => !currency || row.currency === currency).map((row) => ({ label: `${row.bucket}–${row.bucket + 24} ${row.currency}`, count: row.count }))} metrics={[chartMetric.count]} types={["bar", "horizontal", "line", "area"]} /><Visualization title="Rating distribution" description="Latest product ratings grouped by half-star" data={result.rating_distribution.map((row) => ({ label: row.bucket.toFixed(1), count: row.count }))} metrics={[chartMetric.count]} types={["bar", "horizontal", "line", "area"]} />
          <Visualization title="Review-count distribution" description="Latest product review counts grouped into numeric ranges" data={result.review_distribution} metrics={[chartMetric.count]} types={["bar", "horizontal", "line", "area"]} /><Visualization title="Fulfillment type" description="Distinct products from their latest snapshot in range" data={result.fulfillment_distribution} metrics={[chartMetric.count]} types={["bar", "donut"]} initialType="donut" />
          <Visualization title="Products by brand" description="Distinct product IDs in the selected scope" data={result.products_by_brand} metrics={[chartMetric.count]} types={["bar", "horizontal"]} initialType="horizontal" /><Visualization title="Products by seller" description="Distinct product IDs in the selected scope" data={result.products_by_seller} metrics={[chartMetric.count]} types={["bar", "horizontal"]} initialType="horizontal" />
          <Visualization title="Sponsored and badge proportions" description="Known yes/no flags are separated from NULL values" data={badges} metrics={[chartMetric.count]} types={["bar", "horizontal"]} initialType="bar" /><Visualization title="Search-rank distribution" description="Stored search rank positions grouped in ten-position bins; lower rank values are earlier" data={result.search_rank_distribution.map((row) => ({ label: `${row.bucket}–${row.bucket + 9}`, count: row.count }))} metrics={[chartMetric.count]} types={["bar", "horizontal", "line", "area"]} />
          <Visualization title="BSR by category" description="Only successfully parsed rank/category values are included" data={result.bsr_by_category.map((row) => ({ ...row, avg_rank: row.avg_rank }))} metrics={[{ key: "avg_rank", label: "Average BSR position", format: "number", types: ["bar", "horizontal"] }, chartMetric.count]} types={["bar", "horizontal"]} initialMetric="avg_rank" initialType="horizontal" />
          <Visualization title="Image count vs listing quality" description="Latest observations grouped by stored image count" data={result.images_vs_quality.map((row) => ({ ...row, label: String(row.label) }))} metrics={qualityMetrics} types={["bar", "horizontal", "line", "area"]} /><Visualization title="Bullet points vs listing quality" description="Latest observations grouped by stored bullet-point count" data={result.bullets_vs_quality.map((row) => ({ ...row, label: String(row.label) }))} metrics={qualityMetrics} types={["bar", "horizontal", "line", "area"]} />
          <Visualization title="Top products by final score" description="Latest scored snapshot per unique ASIN. Select a bar to open its product." data={topProductsByScore} metrics={[chartMetric.score]} types={["horizontal"]} initialType="horizontal" onPointClick={selectedPoint} />
        </div>
        <div className="mt-5"><ProductComparison rows={rows} /></div>
        <Panel className="mt-5" title="Filtered snapshot dataset" description="CSV exports the actual observations returned for the selected filters" action={<button className="secondary-button" onClick={() => downloadCsv(rows as unknown as Array<Record<string, unknown>>, "nichescope-snapshots.csv")}><Download size={13} /> Export CSV</button>}><div className="data-table-wrap"><table className="data-table"><thead><tr><th>Date</th><th>Niche</th><th>ASIN / product</th><th>Price</th><th>Rating</th><th>Reviews</th><th>Rank</th><th>Demand</th><th>Competition</th><th>Quality gap</th><th>Final</th></tr></thead><tbody>{rows.slice(0, 100).map((row) => <tr key={row.snapshot_id}><td>{formatDate(row.parsed_at, true)}</td><td>{row.niche_name}</td><td><Link href={`/products/${row.product_id}`} className="text-cyan-300">{row.asin}</Link><span className="product-name ml-2 text-slate-500">{row.title}</span></td><td>{row.price == null ? "N/A" : formatCurrency(row.price, row.currency)}</td><td>{row.rating ?? "N/A"}</td><td>{row.review_count == null ? "N/A" : formatCompact(row.review_count)}</td><td>{row.search_rank_position ?? "N/A"}</td><td>{row.demand_score ?? "N/A"}</td><td>{row.competition_score ?? "N/A"}</td><td>{row.quality_gap_score ?? "N/A"}</td><td>{row.final_score ?? "N/A"}</td></tr>)}</tbody></table>{!rows.length && <EmptyState title="No observations in this range" description="Try a wider date range or another niche." icon={Database} />}</div></Panel>
      </>;
    }}</RequestState>
  </>;
}

export function OpportunitiesPage() {
  const niches = useRemote("opportunity-niches", () => api.getNiches()); const runsState = useRemote("opportunity-runs", () => api.getRuns({ page_size: 100 }));
  const [nicheId, setNicheId] = useState(""); const [runId, setRunId] = useState("");
  const nicheRuns = runsState.data?.items.filter((run) => run.niche_id === Number(nicheId)) ?? [];
  useEffect(() => { if (!nicheRuns.some((run) => run.id === Number(runId))) setRunId(nicheRuns[0] ? String(nicheRuns[0].id) : ""); }, [nicheId, runsState.data?.items.length]);
  const key = `${nicheId}:${runId}`; const state = useRemote(key, () => nicheId && runId ? fetch(`/api/niches/${nicheId}/runs/${runId}/opportunities`).then((response) => { if (!response.ok) throw new Error("Unable to load rankings"); return response.json() as Promise<Product[]>; }) : Promise.resolve([]));
  return <><PageHeader eyebrow="Workspace / Opportunities" title="Opportunity rankings" description="Rank products by scores attached to snapshots from the selected search run." /><div className="filter-bar"><select className="filter-select" value={nicheId} onChange={(event) => setNicheId(event.target.value)} aria-label="Select niche"><option value="">Select niche</option>{niches.data?.map((niche) => <option key={niche.id} value={niche.id}>{niche.name}</option>)}</select><select className="filter-select" value={runId} onChange={(event) => setRunId(event.target.value)} aria-label="Select search run"><option value="">Select run</option>{nicheRuns.map((run) => <option key={run.id} value={run.id}>#{run.id} · {run.keyword ?? "keyword unavailable"}</option>)}</select><button className="secondary-button" onClick={() => { setNicheId(""); setRunId(""); }}>Reset</button></div><RequestState state={state}>{(products) => <Panel className="mt-5" title={`${products.filter((product) => product.current?.opportunity).length} scored products`} description="Unscored products are preserved after scored products; the score is joined by snapshot ID"><div className="data-table-wrap"><table className="data-table"><thead><tr><th>Product</th><th>Seller</th><th>Price</th><th>Rating</th><th>Demand</th><th>Competition</th><th>Quality gap</th><th>Final score</th></tr></thead><tbody>{products.map((product) => <tr key={product.id}><td><Link href={`/products/${product.id}`} className="group flex min-w-[220px] flex-col gap-1"><span className="product-name text-cyan-300 group-hover:text-cyan-200" title={product.title ?? product.asin}>{product.title ?? product.asin}</span><span className="font-mono text-[9px] tracking-[0.08em] text-slate-600">{product.asin}</span></Link></td><td>{product.seller_name ?? "N/A"}</td><td>{product.current?.price == null ? "N/A" : formatCurrency(product.current.price, product.current.currency)}</td><td>{product.current?.rating ?? "N/A"}</td><td>{product.current?.opportunity?.demand_score ?? "N/A"}</td><td>{product.current?.opportunity?.competition_score ?? "N/A"}</td><td>{product.current?.opportunity?.quality_gap_score ?? "N/A"}</td><td><ScoreChip score={product.current?.opportunity?.final_score ?? null} /></td></tr>)}</tbody></table>{!products.length && <EmptyState title="No run data available" description="Choose a niche and run with recorded product snapshots." icon={Gauge} />}</div></Panel>}</RequestState></>;
}

export function RunsPage() {
  const searchParams = new URLSearchParams(window.location.search);
  const [status, setStatus] = useState(searchParams.get("status") ?? ""); const [nicheId, setNicheId] = useState(""); const [keywordId, setKeywordId] = useState("");
  const [startDate, setStartDate] = useState(searchParams.get("start_date") ?? ""); const [endDate, setEndDate] = useState(searchParams.get("end_date") ?? ""); const [page, setPage] = useState(1);
  const filters: RunFilters = { page, page_size: 25, status: status ? status as RunStatus : undefined, niche_id: nicheId ? Number(nicheId) : undefined, keyword_id: keywordId ? Number(keywordId) : undefined, start_date: startDate || undefined, end_date: endDate || undefined };
  const state = useRemote(JSON.stringify(filters), () => api.getRuns(filters)); const niches = useRemote("run-niches", () => api.getNiches()); const filterOptions = useRemote("run-filter-options", () => api.getProductFilters());
  useEffect(() => { setPage(1); }, [status, nicheId, keywordId, startDate, endDate]);
  return <><PageHeader eyebrow="Operations / Runs" title="Search run history" description="Pipeline state and counts come directly from search_runs. Only success, partial, failed, and running statuses are accepted." actions={<Link href="/scraper" className="primary-button"><Play size={13} /> Start a run</Link>} /><div className="panel mb-5 grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-5"><Select label="Status" value={status} onChange={setStatus}><option value="">All statuses</option><option value="success">Success</option><option value="partial">Partial</option><option value="failed">Failed</option><option value="running">Running</option></Select><Select label="Niche" value={nicheId} onChange={setNicheId}><option value="">All niches</option>{niches.data?.map((niche) => <option key={niche.id} value={niche.id}>{niche.name}</option>)}</Select><Select label="Keyword" value={keywordId} onChange={setKeywordId}><option value="">All keywords</option>{filterOptions.data?.keywords.map((item) => <option key={item.id} value={item.id}>{item.text}</option>)}</Select><label><span className="field-label">From date</span><input type="date" className="dark-input" value={startDate} onChange={(event) => setStartDate(event.target.value)} /></label><label><span className="field-label">To date</span><input type="date" className="dark-input" value={endDate} onChange={(event) => setEndDate(event.target.value)} /></label><button className="secondary-button" onClick={() => { setStatus(""); setNicheId(""); setKeywordId(""); setStartDate(""); setEndDate(""); }}>Reset filters</button></div><RequestState state={state}>{(result) => <Panel title={`${formatNumber(result.total)} search runs`} description="Newest stored timestamp first"><RunTable runs={result.items} />{!result.items.length && <EmptyState title="No runs match these filters" description="Clear the filters or start a scraper run." icon={Activity} />}<Pagination page={result.page} pageSize={result.page_size} total={result.total} onChange={setPage} /></Panel>}</RequestState></>;
}

export function RunDetailPage() {
  const [, params] = useRoute("/runs/:id"); const id = Number(params?.id); const state = useRemote(`run:${id}`, () => api.getRun(id));
  return <><Link href="/runs" className="back-link">← Run history</Link><RequestState state={state}>{(run) => <><PageHeader eyebrow="Search run detail" title={`Run #${run.id}`} description={`${run.niche_name} · ${run.keyword ?? "Keyword unavailable"} · ${formatDate(run.run_timestamp, true)}`} actions={<StatusPill status={run.status} />} /><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><MetricCard label="Pages scraped" value={formatNumber(run.pages_scraped)} icon={Database} accent="cyan" /><MetricCard label="Products found" value={formatNumber(run.products_found)} icon={PackageCheck} accent="violet" /><MetricCard label="Scrape errors" value={formatNumber(run.error_count)} icon={AlertTriangle} accent="amber" /><MetricCard label="Progress" value={run.status === "running" ? "In progress" : run.status} icon={Activity} accent="green" detail="No percentage is inferred" /></div><Panel className="mt-5" title="Pipeline state" description="Progress fields as reported by the pipeline"><div className="grid gap-4 p-5 sm:grid-cols-2"><div><p className="field-label">Current stage</p><p className="text-sm text-slate-200">{run.current_stage ?? "Not reported"}</p></div><div><p className="field-label">Current task</p><p className="text-sm text-slate-200">{run.current_task ?? "Not reported"}</p></div><div className="sm:col-span-2"><p className="field-label">Notes</p><p className="whitespace-pre-wrap text-xs text-slate-400">{run.notes ?? "No notes recorded."}</p></div></div></Panel><Panel className="mt-5" title={`Scrape errors (${run.errors.length})`} description="Errors are related to this run through search_run_id"><div className="data-table-wrap"><table className="data-table"><thead><tr><th>Time</th><th>Type</th><th>Message</th><th>URL</th><th>Attempt</th></tr></thead><tbody>{run.errors.map((error) => <tr key={error.id}><td>{formatDate(error.occurred_at, true)}</td><td>{error.error_type ?? "Unknown"}</td><td className="whitespace-normal">{error.error_message ?? "No message"}</td><td className="max-w-[250px] truncate">{error.url ?? "N/A"}</td><td>{error.attempt_number ?? "N/A"}</td></tr>)}</tbody></table>{!run.errors.length && <EmptyState title="No scrape errors" description="This run has no associated error rows." icon={Check} />}</div></Panel></>}</RequestState></>;
}

export function ErrorsPage() {
  const [runId, setRunId] = useState(""); const [page, setPage] = useState(1); const state = useRemote(`${runId}:${page}`, () => api.getErrors(runId ? Number(runId) : undefined, page, 50));
  return <><PageHeader eyebrow="Operations / Errors" title="Scrape errors" description="Errors are linked to their search runs and shown with stored type, URL, attempt, and timestamp." /><div className="filter-bar"><input className="dark-input max-w-[220px]" type="number" min="1" value={runId} onChange={(event) => { setRunId(event.target.value); setPage(1); }} placeholder="Filter by run ID" aria-label="Filter by run ID" /><button className="secondary-button" onClick={() => setRunId("")}>Reset</button></div><RequestState state={state}>{(result) => <Panel className="mt-5" title={`${formatNumber(result.total)} errors`}><div className="data-table-wrap"><table className="data-table"><thead><tr><th>Occurred</th><th>Run</th><th>Niche / keyword</th><th>Error type</th><th>Message</th><th>URL</th><th>Attempt</th></tr></thead><tbody>{result.items.map((error) => <tr key={error.id}><td>{formatDate(error.occurred_at, true)}</td><td>{error.search_run_id ? <Link href={`/runs/${error.search_run_id}`} className="text-cyan-300">#{error.search_run_id}</Link> : "N/A"}</td><td>{error.niche_name ?? "N/A"} · {error.keyword ?? "N/A"}</td><td>{error.error_type ?? "Unknown"}</td><td className="whitespace-normal">{error.error_message ?? "No message"}</td><td className="max-w-[240px] truncate">{error.url ?? "N/A"}</td><td>{error.attempt_number ?? "N/A"}</td></tr>)}</tbody></table>{!result.items.length && <EmptyState title="No scrape errors" description="No errors match the current run filter." icon={Check} />}</div><Pagination page={result.page} pageSize={result.page_size} total={result.total} onChange={setPage} /></Panel>}</RequestState></>;
}

export function SchedulesPage() {
  const state = useRemote<Schedule[]>("schedules", () => api.getSchedules());
  async function removeSchedule(id: number) {
    try { await api.deleteSchedule(id); toast.success("Demand schedule removed"); state.retry(); }
    catch (error) { toast.error(error instanceof Error ? error.message : "Could not remove schedule"); }
  }
  return <><PageHeader eyebrow="Operations / Schedules" title="Demand refresh schedules" description="The dashboard worker launches the existing scraper pipeline twice each day. Times use India Standard Time." actions={<Link href="/demand" className="primary-button"><Target size={13} /> Demand tracker</Link>} /><RequestState state={state}>{(items) => <Panel title={`${items.length} schedules`} description="The worker claims each time slot once and skips a niche and keyword pair while its previous run is still active."><div className="data-table-wrap"><table className="data-table"><thead><tr><th>Niche</th><th>Keyword</th><th>Daily run times</th><th>Limits</th><th>Last triggered</th><th>Active</th><th /></tr></thead><tbody>{items.map((item) => <tr key={item.id}><td><Link className="text-cyan-300" href={`/niches/${item.niche_id}`}>{item.niche_name}</Link></td><td>{item.keyword}</td><td className="font-mono text-xs">{item.run_times.split(",").join(" · ")} <span className="text-slate-600">{item.timezone}</span></td><td>{item.pages} pages · {formatNumber(item.products)} products</td><td>{formatDate(item.last_triggered_at, true)}</td><td>{item.is_active ? "Active" : "Inactive"}</td><td><button className="secondary-button" onClick={() => void removeSchedule(item.id)}>Remove</button></td></tr>)}</tbody></table>{!items.length && <EmptyState title="No demand schedules" description="Add a twice daily refresh from the Demand Tracker page." icon={Clock3} />}</div></Panel>}</RequestState></>;
}

export function DemandTrackerPage() {
  const niches = useRemote<Niche[]>("demand-tracker-niches", () => api.getNiches());
  const [nicheId, setNicheId] = useState(""); const [keywordId, setKeywordId] = useState("");
  const [demandPage, setDemandPage] = useState(1);
  const [pages, setPages] = useState("10"); const [products, setProducts] = useState("100");
  const [morningTime, setMorningTime] = useState("08:00"); const [eveningTime, setEveningTime] = useState("20:00");
  const [busy, setBusy] = useState(false); const [backfillBusy, setBackfillBusy] = useState(false);
  const [activeRunId, setActiveRunId] = useState<number | null>(null);
  const [backfill, setBackfill] = useState<DemandBackfillJob | null>(null);
  const selectedNiche = niches.data?.find((item) => item.id === Number(nicheId));
  const demand = useRemote<DemandTrackerData>(`demand:${nicheId}:${demandPage}`, () => api.getDemand(nicheId ? Number(nicheId) : undefined, demandPage));
  useEffect(() => {
    if (!nicheId && demand.data?.selected_niche) setNicheId(String(demand.data.selected_niche.id));
  }, [nicheId, demand.data?.selected_niche?.id]);
  useEffect(() => {
    if (!selectedNiche?.keywords.some((item) => item.id === Number(keywordId))) {
      setKeywordId(selectedNiche?.keywords[0] ? String(selectedNiche.keywords[0].id) : "");
    }
  }, [nicheId, selectedNiche?.keywords.length]);
  useEffect(() => { void api.getDemandBackfill().then(setBackfill).catch(() => undefined); }, []);
  const backfillActive = backfill?.status === "queued" || backfill?.status === "running";
  useEffect(() => {
    if (!backfillActive) return;
    const timer = window.setInterval(() => { void api.getDemandBackfill().then(setBackfill).catch(() => undefined); }, 3500);
    return () => window.clearInterval(timer);
  }, [backfillActive]);
  useEffect(() => {
    if (!activeRunId) return;
    let live = true; let timer: number | undefined;
    const poll = async () => {
      try {
        const run = await api.getRun(activeRunId);
        if (!live) return;
        if (run.status === "running") timer = window.setTimeout(() => void poll(), 3000);
        else { setActiveRunId(null); demand.retry(); toast.success(`Demand snapshot saved in run #${activeRunId}`); }
      } catch { if (live) timer = window.setTimeout(() => void poll(), 5000); }
    };
    void poll();
    return () => { live = false; if (timer) window.clearTimeout(timer); };
  }, [activeRunId]);

  async function startDemandScrape() {
    if (!nicheId || !keywordId) return;
    setBusy(true);
    try {
      const run = await api.startScrape({ nicheId: Number(nicheId), keywordId: Number(keywordId), pages: Number(pages), products: Number(products), recurring: false, frequency: "daily" });
      setActiveRunId(run.runId);
      toast.success(`Demand refresh started as run #${run.runId}`);
    } catch (error) { toast.error(error instanceof Error ? error.message : "Could not start demand refresh"); }
    finally { setBusy(false); }
  }
  async function saveSchedule() {
    if (!nicheId || !keywordId || morningTime === eveningTime) return;
    setBusy(true);
    try {
      await api.createDemandSchedule({ nicheId: Number(nicheId), keywordId: Number(keywordId), pages: Number(pages), products: Number(products), runTimes: `${morningTime},${eveningTime}`, timezone: "Asia/Kolkata" });
      toast.success("Two daily demand refreshes are scheduled");
    } catch (error) { toast.error(error instanceof Error ? error.message : "Could not save schedule"); }
    finally { setBusy(false); }
  }
  async function runHistoricalBackfill() {
    setBackfillBusy(true);
    try {
      const job = await api.startDemandBackfill(); setBackfill(job);
      toast.success(job.already_active ? "Historical scoring is already running" : "Historical demand scoring queued");
    } catch (error) { toast.error(error instanceof Error ? error.message : "Could not start historical scoring"); }
    finally { setBackfillBusy(false); }
  }

  return <>
    <PageHeader eyebrow="Workspace / Demand" title="Demand tracker" description="Track unique ASINs by niche, refresh review counts through the scraper, and see demand scores as review history accumulates." actions={<Link href="/schedules" className="secondary-button"><TimerReset size={13} /> Schedules</Link>} />
    {niches.data?.length === 0 ? <EmptyState title="No niches are configured" description="Create a niche and keyword before collecting demand observations." icon={Database} /> :
      <div className="grid gap-5 xl:grid-cols-[0.82fr_1.18fr]">
        <Panel title="Demand scraper" description="Manual refreshes use the same ASIN-deduplicating scraper and snapshot history as other runs.">
          <div className="space-y-4 p-5">
            <Select label="Niche" value={nicheId} onChange={(value) => { setNicheId(value); setDemandPage(1); }}><option value="">Select niche</option>{niches.data?.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</Select>
            <Select label="Keyword" value={keywordId} onChange={setKeywordId}><option value="">Select keyword</option>{selectedNiche?.keywords.map((item) => <option key={item.id} value={item.id}>{item.text}</option>)}</Select>
            <div className="grid grid-cols-2 gap-3"><label><span className="field-label">Pages per run</span><input className="dark-input" type="number" min="1" max="100" value={pages} onChange={(event) => setPages(event.target.value)} /></label><label><span className="field-label">Product limit</span><input className="dark-input" type="number" min="1" max="10000" value={products} onChange={(event) => setProducts(event.target.value)} /></label></div>
            <button className="primary-button w-full justify-center" disabled={busy || !nicheId || !keywordId || Number(pages) < 1 || Number(products) < 1} onClick={() => void startDemandScrape()}><Play size={13} fill="currentColor" />{busy ? "Working…" : "Collect fresh demand data"}</button>
            <div className="border-t border-white/[0.07] pt-4">
              <p className="text-xs font-medium text-slate-300">Twice daily schedule <span className="ml-1 text-[10px] text-slate-600">Asia/Kolkata</span></p>
              <div className="mt-3 grid grid-cols-2 gap-3"><label><span className="field-label">First run</span><input className="dark-input" type="time" value={morningTime} onChange={(event) => setMorningTime(event.target.value)} /></label><label><span className="field-label">Second run</span><input className="dark-input" type="time" value={eveningTime} onChange={(event) => setEveningTime(event.target.value)} /></label></div>
              <button className="secondary-button mt-3 w-full justify-center" disabled={busy || !nicheId || !keywordId || morningTime === eveningTime || Number(pages) < 1 || Number(products) < 1} onClick={() => void saveSchedule()}><TimerReset size={13} /> Save two daily runs</button>
              <p className="mt-2 text-[10px] leading-4 text-slate-600">Each slot creates one search run while the dashboard API is running. A slot is claimed once, and the worker skips it if that niche and keyword already have a running scrape.</p>
            </div>
          </div>
        </Panel>
        <Panel title="Historical scoring" description="Recalculate each completed snapshot using only observations available at that snapshot time.">
          <div className="p-5">
            <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-sm font-medium text-slate-200">Review count + review velocity</p><p className="mt-1 text-xs text-slate-500">70% normalized review count · 30% reviews gained per day · niche relative</p></div><button className="secondary-button" disabled={backfillBusy || backfillActive} onClick={() => void runHistoricalBackfill()}><RefreshCw size={13} className={backfillActive ? "animate-spin" : ""} />{backfillActive ? "Scoring history…" : "Score historical runs"}</button></div>
            {backfill && <div className="mt-5 rounded-lg border border-white/[0.07] bg-white/[0.02] p-4"><div className="flex items-center justify-between gap-3"><span className="text-xs text-slate-300">{backfill.status === "queued" ? "Queued" : backfill.status === "running" ? "Recalculating snapshots" : backfill.status === "completed" ? "Backfill complete" : "Backfill encountered errors"}</span><span className="font-mono text-[11px] text-slate-500">{backfill.processed_runs}/{backfill.total_runs} runs</span></div><div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/[0.06]"><div className="h-full rounded-full bg-cyan-400 transition-all" style={{ width: `${backfill.total_runs ? Math.min(100, backfill.processed_runs * 100 / backfill.total_runs) : backfill.status === "completed" ? 100 : 0}%` }} /></div><p className="mt-2 text-[10px] text-slate-600">{formatNumber(backfill.products_scored)} product snapshots scored{backfill.error_message ? ` · ${backfill.error_message}` : ""}</p></div>}
            <div className="mt-4 grid gap-2 text-[11px] leading-5 text-slate-500 sm:grid-cols-3"><p>Unique products stay keyed by ASIN.</p><p>Every scrape adds an observation to its run.</p><p>Scores stay pending until two usable review observations exist.</p></div>
          </div>
        </Panel>
      </div>}
    <RequestState state={demand}>{(data) => <>
      {data.selected_niche && <div className="mt-5 flex flex-wrap items-end justify-between gap-3"><div><p className="field-label">Tracking niche</p><Select label="" value={nicheId || String(data.selected_niche.id)} onChange={(value) => { setNicheId(value); setDemandPage(1); }} className="mt-1"><option value="">Select niche</option>{data.niches.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</Select></div><div className="flex items-center gap-3"><p className="text-[10px] text-slate-600">Latest observation: {formatDate(data.summary?.latest_observation, true)}</p><button className="secondary-button" onClick={demand.retry}><RefreshCw size={12} /> Refresh</button></div></div>}
      {!data.selected_niche ? <EmptyState title="No demand observations yet" description="Choose a niche and collect fresh demand data to start the tracker." icon={Target} /> : <>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><MetricCard label="Unique products" value={formatNumber(data.summary?.product_count)} icon={PackageCheck} accent="cyan" detail="Deduplicated by ASIN" /><MetricCard label="Scored products" value={formatNumber(data.summary?.scored_products)} icon={Target} accent="violet" detail="Enough review history" /><MetricCard label="Coverage" value={`${data.summary?.coverage_percent ?? 0}%`} icon={Gauge} accent="green" detail="Latest observations with a score" /><MetricCard label="Latest observation" value={formatDate(data.summary?.latest_observation)} icon={Activity} accent="amber" detail={formatDate(data.summary?.latest_observation, true)} /></div>
        <div className="mt-5">{data.time_series.some((row) => row.average_demand_score !== null) ? <Visualization title="Average demand score by run" description="Historical scores use only the product review observations available at each run." data={data.time_series.map((row) => ({ ...row, label: new Date(row.label).toLocaleDateString("en-US", { month: "short", day: "numeric" }) }))} metrics={[{ key: "average_demand_score", label: "Average demand score", format: "score", types: ["line", "area"] }]} types={["area", "line"]} initialType="area" height={280} csvName="demand-trend" /> : <Panel title="Demand history" description="A trend line appears once products have enough review observations."><div className="flex min-h-[220px] items-center justify-center p-5"><EmptyState title="Waiting for repeat observations" description="Demand scores appear after a product has at least two usable review snapshots. Keep the same niche and keyword on the daily schedule to build its history." icon={Activity} /></div></Panel>}</div>
        <Panel className="mt-5" title={`${formatNumber(data.total)} products in ${data.selected_niche.name}`} description="Each product appears once. A missing score means the review history is not usable yet.">
          <div className="data-table-wrap"><table className="data-table"><thead><tr><th>Product</th><th>ASIN</th><th>Latest reviews</th><th>Review observations</th><th>Demand score</th><th>Freshness</th></tr></thead><tbody>{data.items.map((item) => <tr key={item.product_id}><td className="min-w-[230px] whitespace-normal"><Link href={`/products/${item.product_id}`} className="product-name hover:text-cyan-300">{item.title ?? item.asin}</Link></td><td className="font-mono text-[10px] text-slate-500">{item.asin}</td><td>{formatCompact(item.review_count)}</td><td>{formatNumber(item.review_observations)}</td><td><div className="flex items-center gap-2"><ScoreChip score={item.demand_score} />{item.demand_score == null && <span className="text-[10px] text-slate-600">{item.score_status}</span>}</div></td><td className="text-[10px] text-slate-500">{formatDate(item.parsed_at, true)}</td></tr>)}</tbody></table>{!data.items.length && <EmptyState title="No products observed in this niche" description="Run the demand scraper to collect the first review snapshot." icon={Database} />}</div>
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onChange={setDemandPage} />
        </Panel>
      </>}
    </>}</RequestState>
  </>;
}

export function ScraperPage() {
  const niches = useRemote("scraper-niches", () => api.getNiches()); const [nicheId, setNicheId] = useState(""); const [keywordId, setKeywordId] = useState("");
  const [pages, setPages] = useState("10"); const [products, setProducts] = useState("100"); const [runId, setRunId] = useState<number | null>(null); const [run, setRun] = useState<SearchRun | null>(null); const [busy, setBusy] = useState(false); const [pollError, setPollError] = useState("");
  const selectedNiche = niches.data?.find((item) => item.id === Number(nicheId));
  useEffect(() => { if (!selectedNiche?.keywords.some((item) => item.id === Number(keywordId))) setKeywordId(selectedNiche?.keywords[0] ? String(selectedNiche.keywords[0].id) : ""); }, [nicheId, selectedNiche?.keywords.length]);
  useEffect(() => {
    if (!runId) return;
    let active = true; let timer: number | undefined;
    const poll = async () => {
      try {
        const value = await api.getRun(runId);
        if (!active) return;
        setRun(value); setPollError("");
        if (value.status === "running") timer = window.setTimeout(() => void poll(), 2500);
      } catch (error) { if (active) setPollError(error instanceof Error ? error.message : "Could not read run state"); }
    };
    void poll(); return () => { active = false; if (timer) window.clearTimeout(timer); };
  }, [runId]);
  async function start() {
    if (!nicheId || !keywordId) return;
    setBusy(true); setPollError("");
    try { const result = await api.startScrape({ nicheId: Number(nicheId), keywordId: Number(keywordId), pages: Number(pages), products: Number(products), recurring: false, frequency: "daily" }); setRunId(result.runId); toast.success(`Started search run #${result.runId}`); }
    catch (error) { toast.error(error instanceof Error ? error.message : "Could not start scraper"); }
    finally { setBusy(false); }
  }
  return <><PageHeader eyebrow="Operations / Scraper" title="Scraper control center" description="Starts the existing Python pipeline and reads run state from search_runs." actions={<Link href="/demand" className="secondary-button"><Target size={13} /> Demand tracker</Link>} />{niches.data?.length === 0 ? <EmptyState title="No niches are configured" description="The scraper starts from existing niche and keyword IDs. Create them through the project’s existing data setup first." icon={Database} /> : <div className="grid gap-5 xl:grid-cols-[0.8fr_1.2fr]"><Panel title="Start a pipeline run" description="The configured pages and product limits are passed to the existing scraper"><div className="space-y-4 p-5"><Select label="Niche" value={nicheId} onChange={setNicheId}><option value="">Select niche</option>{niches.data?.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</Select><Select label="Keyword" value={keywordId} onChange={setKeywordId}><option value="">Select keyword</option>{selectedNiche?.keywords.map((item) => <option key={item.id} value={item.id}>{item.text}</option>)}</Select><div className="grid grid-cols-2 gap-3"><label><span className="field-label">Pages</span><input className="dark-input" type="number" min="1" max="100" value={pages} onChange={(event) => setPages(event.target.value)} /></label><label><span className="field-label">Product limit</span><input className="dark-input" type="number" min="1" max="10000" value={products} onChange={(event) => setProducts(event.target.value)} /></label></div><button className="primary-button w-full justify-center" disabled={busy || !nicheId || !keywordId || Number(pages) < 1 || Number(products) < 1} onClick={() => void start()}><Play size={14} fill="currentColor" />{busy ? "Starting…" : "Start scrape"}</button><p className="text-[10px] leading-5 text-slate-600">Set recurring demand refreshes on the Demand Tracker page. Schedules run in India Standard Time.</p></div></Panel><Panel title="Run status" description="Only stored progress fields are shown"><div className="p-5">{run ? <><div className="flex items-center justify-between border-b border-white/[0.07] pb-4"><div><p className="font-mono text-lg text-cyan-300">Run #{run.id}</p><p className="mt-1 text-xs text-slate-500">{run.niche_name} · {run.keyword ?? "Keyword unavailable"}</p></div><StatusPill status={run.status} /></div><div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4"><div><p className="field-label">Pages scraped</p><p>{run.pages_scraped ?? "N/A"}</p></div><div><p className="field-label">Products found</p><p>{run.products_found ?? "N/A"}</p></div><div><p className="field-label">Current stage</p><p>{run.current_stage ?? "Not reported"}</p></div><div><p className="field-label">Current task</p><p>{run.current_task ?? "Not reported"}</p></div></div><Link className="mt-5 inline-block text-xs text-cyan-300" href={`/runs/${run.id}`}>Open run details</Link></> : <EmptyState title="No run selected" description="Start a scrape to monitor its actual pipeline state." icon={Activity} />}{pollError && <p className="mt-3 text-xs text-rose-300">{pollError}</p>}</div></Panel></div>}</>;
}

export function SystemPage() {
  const state = useRemote("system-check", () => fetch("/api/health").then(async (response) => { if (!response.ok) throw new Error("Dashboard API is unavailable"); return response.json() as Promise<{ status: string; database: string }>; }));
  return <><PageHeader eyebrow="System" title="System status" description="The dashboard API checks the configured SQLite connection using a read-only connection." /><RequestState state={state}>{(health) => <div className="grid gap-4 sm:grid-cols-2"><div className="health-card"><div className="health-icon"><Server size={16} /></div><p className="mt-4 text-sm font-medium text-slate-200">Dashboard API</p><p className="mt-2 text-xs text-emerald-300">{health.status}</p></div><div className="health-card"><div className="health-icon"><Database size={16} /></div><p className="mt-4 text-sm font-medium text-slate-200">SQLite database</p><p className="mt-2 break-all font-mono text-xs text-slate-500">{health.database}</p></div></div>}</RequestState></>;
}

export function SettingsPage() {
  const { settings, updateSettings, resetSettings } = useSettings(); const [name, setName] = useState(settings.displayName); const [tagline, setTagline] = useState(settings.tagline); const [productName, setProductName] = useState(settings.productName);
  return <><PageHeader eyebrow="System / Settings" title="Dashboard preferences" description="These presentation preferences are stored in this browser and do not change scraper or scoring data." /><Panel title="Workspace identity" description="Local browser preferences"><div className="grid gap-4 p-5 sm:grid-cols-2"><label><span className="field-label">Product name</span><input className="dark-input" value={productName} onChange={(event) => setProductName(event.target.value)} /></label><label><span className="field-label">Display name</span><input className="dark-input" value={name} onChange={(event) => setName(event.target.value)} /></label><label className="sm:col-span-2"><span className="field-label">Tagline</span><input className="dark-input" value={tagline} onChange={(event) => setTagline(event.target.value)} /></label><div className="flex gap-2"><button className="primary-button" onClick={() => { updateSettings({ displayName: name, tagline, productName }); toast.success("Preferences saved in this browser"); }}>Save preferences</button><button className="secondary-button" onClick={() => { resetSettings(); setName("Arjun Shah"); setTagline("Amazon Product Research and Market Intelligence"); setProductName("NicheScope"); }}>Reset</button></div></div></Panel></>;
}

export function LoginPage() {
  return <div className="login-shell"><div className="login-card"><div className="login-brand grid place-items-center rounded-xl bg-cyan-300/10 text-cyan-200"><Database size={20} /></div><h1 className="mt-5 text-xl font-semibold text-white">NicheScope</h1><p className="mt-2 text-sm leading-6 text-slate-500">Authentication is not configured for this local dashboard API. Continue to the dashboard to inspect the project’s SQLite data.</p><Link href="/overview" className="primary-button mt-5">Open dashboard</Link></div></div>;
}

export function NotFoundPage() {
  return <div className="empty-state"><AlertTriangle size={22} className="text-amber-300" /><h1 className="mt-4 text-lg text-white">Page not found</h1><p className="mt-2 text-xs text-slate-500">The requested dashboard page does not exist.</p><Link className="mt-4 text-xs text-cyan-300" href="/overview">Return to overview</Link></div>;
}
