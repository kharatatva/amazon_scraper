import { useEffect, useMemo, useState } from "react";
import { Activity } from "lucide-react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Download } from "lucide-react";
import type { AnalyticsPoint } from "@/lib/domain";
import { EmptyState, Panel } from "@/components/dashboard";
import { formatCompact, formatCurrency, formatNumber } from "@/lib/format";

const metrics = [
  { key: "price", label: "Price", unit: "currency" },
  { key: "rating", label: "Rating", unit: "rating" },
  { key: "review_count", label: "Review count", unit: "number" },
  { key: "search_rank_position", label: "Search rank", unit: "number" },
  { key: "demand_score", label: "Demand score", unit: "score" },
  { key: "competition_score", label: "Competition score", unit: "score" },
  { key: "quality_gap_score", label: "Quality-gap score", unit: "score" },
  { key: "final_score", label: "Final opportunity score", unit: "score" },
] as const;
const colors = ["#67e8f9", "#a78bfa", "#fbbf24", "#4ade80"];

export function ProductComparison({ rows }: { rows: AnalyticsPoint[] }) {
  const [selected, setSelected] = useState<number[]>([]);
  const [metricKey, setMetricKey] = useState<(typeof metrics)[number]["key"]>("rating");
  const [kind, setKind] = useState<"line" | "area" | "bar">("line");
  const [currency, setCurrency] = useState("");
  const [search, setSearch] = useState("");
  const metric = metrics.find((item) => item.key === metricKey) ?? metrics[0];
  const products = useMemo(() => {
    const map = new Map<number, { id: number; asin: string; title: string }>();
    for (const row of rows) map.set(row.product_id, { id: row.product_id, asin: row.asin, title: row.title ?? row.asin });
    return Array.from(map.values()).sort((a, b) => a.title.localeCompare(b.title));
  }, [rows]);
  const chartableProducts = useMemo(() => {
    const counts = new Map<number, number>();
    for (const row of rows) {
      if (row[metricKey] !== null && row[metricKey] !== undefined) counts.set(row.product_id, (counts.get(row.product_id) ?? 0) + 1);
    }
    return products.filter((product) => counts.has(product.id)).sort((a, b) => (counts.get(b.id) ?? 0) - (counts.get(a.id) ?? 0) || a.title.localeCompare(b.title));
  }, [products, rows, metricKey]);
  useEffect(() => {
    setSelected((current) => {
      const availableIds = new Set(chartableProducts.map((product) => product.id));
      const retained = current.filter((id) => availableIds.has(id)).slice(0, 4);
      const next = [...retained];
      for (const product of chartableProducts) {
        if (next.length >= 2) break;
        if (!next.includes(product.id)) next.push(product.id);
      }
      return next;
    });
  }, [chartableProducts]);
  const visibleProducts = products.filter((item) => `${item.asin} ${item.title}`.toLowerCase().includes(search.toLowerCase())).slice(0, 100);
  const productNames = new Map(products.map((item) => [item.id, `${item.title} · ${item.asin}`]));
  const displayNames = new Map(products.map((item) => [item.id, `${item.title.length > 36 ? `${item.title.slice(0, 33)}…` : item.title} · ${item.asin}`]));
  const productCurrencies = Array.from(new Set(rows.filter((row) => selected.includes(row.product_id) && row.price != null).map((row) => row.currency ?? "Unknown"))).sort();
  const formatAxisValue = (value: unknown) => {
    const number = Number(value);
    if (!Number.isFinite(number)) return String(value ?? "");
    if (metric.unit === "currency") return formatCurrency(number, currency || (productCurrencies.length === 1 ? productCurrencies[0] : null));
    if (metric.unit === "rating") return number.toFixed(1);
    if (metric.unit === "score") return number.toFixed(0);
    return formatCompact(number);
  };
  const seriesRows = useMemo(() => {
    const dates = new Map<string, Map<number, AnalyticsPoint>>();
    for (const row of rows) {
      if (!selected.includes(row.product_id) || (metricKey === "price" && currency && (row.currency ?? "Unknown") !== currency)) continue;
      const day = row.parsed_at.slice(0, 10);
      const dayRows = dates.get(day) ?? new Map<number, AnalyticsPoint>();
      const previous = dayRows.get(row.product_id);
      if (!previous || row.parsed_at > previous.parsed_at || (row.parsed_at === previous.parsed_at && row.snapshot_id > previous.snapshot_id)) dayRows.set(row.product_id, row);
      dates.set(day, dayRows);
    }
    return Array.from(dates.entries()).sort((a, b) => a[0].localeCompare(b[0])).map(([label, dayRows]) => {
      const result: Record<string, string | number | null> = { label };
      for (const id of selected) result[`p_${id}`] = dayRows.get(id)?.[metricKey] ?? null;
      return result;
    });
  }, [rows, selected, metricKey, currency]);
  const hasSelectedValues = seriesRows.some((row) => selected.some((id) => row[`p_${id}`] !== null && row[`p_${id}`] !== undefined));
  function toggle(id: number) {
    setSelected((current) => current.includes(id) ? current.filter((item) => item !== id) : current.length >= 4 ? current : [...current, id]);
  }
  function exportCsv() {
    const headers = ["date", ...selected.map((id) => productNames.get(id) ?? String(id))];
    const csv = [headers, ...seriesRows.map((row) => [row.label, ...selected.map((id) => row[`p_${id}`])])]
      .map((row) => row.map((value) => `"${String(value ?? "").replaceAll('"', '""')}"`).join(",")).join("\r\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = `nichescope-${metricKey}-comparison.csv`; anchor.click(); URL.revokeObjectURL(url);
  }
  const chart = (() => {
    const common = <><Tooltip contentStyle={{ background: "#111820", border: "1px solid #ffffff18", borderRadius: 8, color: "#dbe4ee", fontSize: 11 }} labelStyle={{ color: "#94a3b8" }} formatter={(value: unknown, name: string) => {
      const productId = Number(name.replace("p_", "")); const row = rows.find((item) => item.product_id === productId);
      const numeric = value == null ? null : Number(value);
      const formatted = numeric == null ? "No observation" : metric.unit === "currency" ? formatCurrency(numeric, currency || row?.currency) : metric.unit === "rating" ? `${numeric.toFixed(1)} / 5` : metric.unit === "score" ? numeric.toFixed(2) : formatNumber(numeric);
      return [formatted, productNames.get(productId) ?? name];
    }} /><CartesianGrid stroke="#ffffff0b" vertical={false} /><Legend wrapperStyle={{ color: "#94a3b8", fontSize: 10 }} formatter={(value) => displayNames.get(Number(String(value).replace(/^p_/, ""))) ?? String(value)} /><XAxis dataKey="label" tick={{ fill: "#64748b", fontSize: 10 }} axisLine={false} tickLine={false} interval="preserveStartEnd" minTickGap={24} /><YAxis tickFormatter={formatAxisValue} tick={{ fill: "#64748b", fontSize: 10 }} axisLine={false} tickLine={false} />{selected.map((id, index) => {
      const key = `p_${id}`; const color = colors[index % colors.length];
      return kind === "area" ? <Area key={key} dataKey={key} name={key} type="monotone" stroke={color} fill={color} fillOpacity={0.12} connectNulls={false} isAnimationActive={false} />
        : kind === "bar" ? <Bar key={key} dataKey={key} name={key} fill={color} isAnimationActive={false} />
        : <Line key={key} dataKey={key} name={key} type="monotone" stroke={color} strokeOpacity={0.9} strokeWidth={2} dot={seriesRows.length <= 60 ? { r: 2, fill: "#111820", stroke: color, strokeWidth: 1.5 } : false} connectNulls={false} isAnimationActive={false} />;
    })}</>;
    if (kind === "area") return <AreaChart data={seriesRows}>{common}</AreaChart>;
    if (kind === "bar") return <BarChart data={seriesRows}>{common}</BarChart>;
    return <LineChart data={seriesRows}>{common}</LineChart>;
  })();

  return <Panel title="Compare product histories" description="Two products with recorded values are selected when the view opens. Missing dates remain gaps; no observations are interpolated." action={<button type="button" className="secondary-button" disabled={!selected.length || !seriesRows.length} onClick={exportCsv}><Download size={13} /> Export CSV</button>}>
    <div className="grid gap-4 p-5 lg:grid-cols-[0.8fr_1.2fr]"><div className="space-y-3"><div className="flex items-center justify-between"><label className="text-xs text-slate-400">Products</label><span className="text-[10px] text-slate-600">{selected.length} selected · up to 4</span></div><input className="dark-input" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Find product by title or ASIN" aria-label="Search comparison products" /><div className="max-h-52 space-y-1 overflow-y-auto rounded-lg border border-white/[0.07] p-2">{visibleProducts.map((item) => <label key={item.id} className="flex cursor-pointer items-start gap-2 rounded px-2 py-1.5 text-[11px] text-slate-400 hover:bg-white/[0.03]"><input type="checkbox" checked={selected.includes(item.id)} disabled={!selected.includes(item.id) && selected.length >= 4} onChange={() => toggle(item.id)} /><span className="min-w-0"><span className="product-name block truncate" title={item.title}>{item.title}</span><span className="font-mono text-[10px] text-slate-600">{item.asin}</span></span></label>)}{!visibleProducts.length && <p className="p-3 text-xs text-slate-600">No products in the selected range.</p>}</div><div className="grid grid-cols-2 gap-2"><label className="flex flex-col gap-1 text-[10px] text-slate-500">Metric<select className="filter-select" value={metricKey} onChange={(event) => setMetricKey(event.target.value as typeof metricKey)}>{metrics.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}</select></label><label className="flex flex-col gap-1 text-[10px] text-slate-500">Chart type<select className="filter-select" value={kind} onChange={(event) => setKind(event.target.value as typeof kind)}><option value="line">Line</option><option value="area">Area</option><option value="bar">Bar</option></select></label>{metricKey === "price" && productCurrencies.length > 1 && <label className="col-span-2 flex flex-col gap-1 text-[10px] text-slate-500">Currency<select className="filter-select" value={currency} onChange={(event) => setCurrency(event.target.value)}><option value="">Choose one currency</option>{productCurrencies.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>}</div></div><div className="h-[320px] min-w-0">{selected.length < 2 ? <EmptyState title={chartableProducts.length < 2 ? "Not enough products to compare" : "Select another product"} description={chartableProducts.length < 2 ? "At least two products need observations in this metric and date range." : "Choose a second product to compare their stored observations."} icon={Activity} /> : !hasSelectedValues ? <EmptyState title="No values for this metric" description="The selected products do not have recorded values for this metric in the selected dates." icon={Activity} /> : metricKey === "price" && productCurrencies.length > 1 && !currency ? <EmptyState title="Choose a currency" description="Prices in different currencies are not compared on the same axis." icon={Activity} /> : <ResponsiveContainer width="100%" height="100%">{chart}</ResponsiveContainer>}</div></div>
  </Panel>;
}
