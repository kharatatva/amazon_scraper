import { useId, useMemo, useState } from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from "recharts";
import { Download } from "lucide-react";
import { formatCompact, formatCurrency, formatNumber } from "@/lib/format";
import { EmptyState, Panel } from "@/components/dashboard";

export type ChartRow = Record<string, string | number | boolean | null | undefined>;
export type ChartKind = "line" | "area" | "bar" | "horizontal" | "donut" | "scatter";
export type MetricFormat = "number" | "currency" | "rating" | "score" | "percent";
export interface VisualMetric {
  key: string;
  label: string;
  format?: MetricFormat;
  currencyKey?: string;
  types: ChartKind[];
}

const palette = ["#67e8f9", "#a78bfa", "#fbbf24", "#4ade80", "#fb7185", "#60a5fa", "#f472b6"];

function formatted(value: unknown, metric?: VisualMetric, row?: ChartRow) {
  if (value === null || value === undefined || value === "") return "Unavailable";
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  switch (metric?.format) {
    case "currency": return formatCurrency(number, metric.currencyKey && row ? String(row[metric.currencyKey] ?? "") : null);
    case "rating": return `${number.toFixed(1)} / 5`;
    case "score": return number.toFixed(2);
    case "percent": return `${number.toFixed(1)}%`;
    default: return formatNumber(number);
  }
}

function downloadCsv(rows: ChartRow[], keys: string[], filename: string) {
  const quote = (value: unknown) => `"${String(value ?? "").replaceAll('"', '""')}"`;
  const csv = [keys.map(quote).join(","), ...rows.map((row) => keys.map((key) => quote(row[key])).join(","))].join("\r\n");
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  link.download = `${filename.replace(/[^a-z0-9_-]+/gi, "-").toLowerCase()}.csv`;
  link.click();
  URL.revokeObjectURL(link.href);
}

export function Visualization({
  title, description, data, labelKey = "label", metrics, types, initialMetric,
  initialType, xMetrics, onPointClick, onMetricChange, height = 280, csvName = title,
}: {
  title: string; description?: string; data: ChartRow[]; labelKey?: string;
  metrics: VisualMetric[]; types?: ChartKind[]; initialMetric?: string; initialType?: ChartKind;
  xMetrics?: VisualMetric[]; onPointClick?: (row: ChartRow) => void; onMetricChange?: (key: string) => void; height?: number; csvName?: string;
}) {
  const areaFillId = `chart-area-${useId().replaceAll(":", "")}`;
  const [metricKey, setMetricKey] = useState(initialMetric ?? metrics[0]?.key ?? "count");
  const metric = metrics.find((item) => item.key === metricKey) ?? metrics[0];
  const [kind, setKind] = useState<ChartKind>(initialType ?? types?.[0] ?? metric?.types[0] ?? "bar");
  const [xKey, setXKey] = useState(xMetrics?.[0]?.key ?? metrics[0]?.key ?? "");
  const scatterMetrics = (xMetrics ?? metrics).filter((item) => item.key !== metric?.key);
  const xMetric = scatterMetrics.find((item) => item.key === xKey) ?? scatterMetrics[0];
  const allowedTypes = useMemo(() => (types ?? metric?.types ?? ["bar"]).filter((item) => metric?.types.includes(item)), [types, metric]);
  const hasNumericValue = (value: unknown) => value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));
  const validRows = data.filter((row) => {
    if (kind === "scatter") return hasNumericValue(row[xMetric?.key ?? ""]) && hasNumericValue(row[metric?.key ?? ""]);
    if (row[labelKey] === null || row[labelKey] === undefined) return false;
    if (kind === "line" || kind === "area") return true;
    return hasNumericValue(row[metric?.key ?? ""]);
  });
  const categoryAxis = kind === "horizontal" ? <YAxis type="category" dataKey={labelKey} width={112} tick={{ fill: "#94a3b8", fontSize: 10 }} axisLine={false} tickLine={false} /> : <XAxis dataKey={labelKey} tick={{ fill: "#64748b", fontSize: 10 }} axisLine={false} tickLine={false} interval="preserveStartEnd" minTickGap={24} />;
  const axisFormatter = (value: unknown, selectedMetric?: VisualMetric) => {
    const number = Number(value);
    if (!Number.isFinite(number)) return String(value ?? "");
    if (selectedMetric?.format === "currency") {
      const currency = selectedMetric.currencyKey && validRows[0] ? String(validRows[0][selectedMetric.currencyKey] ?? "") : null;
      return formatCurrency(number, currency);
    }
    if (selectedMetric?.format === "rating") return number.toFixed(1);
    if (selectedMetric?.format === "score") return number.toFixed(0);
    if (selectedMetric?.format === "percent") return `${number.toFixed(0)}%`;
    return formatCompact(number);
  };
  const valueAxis = kind === "horizontal" ? <XAxis type="number" tickFormatter={(value) => axisFormatter(value, metric)} tick={{ fill: "#64748b", fontSize: 10 }} axisLine={false} tickLine={false} /> : <YAxis tickFormatter={(value) => axisFormatter(value, metric)} tick={{ fill: "#64748b", fontSize: 10 }} axisLine={false} tickLine={false} width={64} />;
  const chartClick = (event: unknown) => {
    if (!onPointClick || !event || typeof event !== "object") return;
    const payload = (event as { activePayload?: Array<{ payload?: ChartRow }> }).activePayload?.[0]?.payload;
    if (payload) onPointClick(payload);
  };
  const commonTooltip = <Tooltip contentStyle={{ background: "#111820", border: "1px solid #ffffff18", borderRadius: 8, color: "#dbe4ee", fontSize: 11 }} labelStyle={{ color: "#94a3b8" }} formatter={(value: unknown, name: unknown, item: { payload?: ChartRow }) => { const nameText = String(name ?? metric?.label); const selectedMetric = kind === "scatter" && nameText === xMetric?.label ? xMetric : metric; return [formatted(value, selectedMetric, item.payload), nameText]; }} />;

  return <Panel title={title} description={description} action={<button type="button" className="secondary-button" onClick={() => downloadCsv(data, Array.from(new Set([labelKey, ...metrics.map((item) => item.key), ...(xMetrics ?? []).map((item) => item.key)])), csvName)} aria-label={`Export ${title} chart data as CSV`}><Download size={13} /> CSV</button>}>
    <div className="flex flex-wrap items-center gap-2 px-5 pt-4">
      {metrics.length > 1 && <label className="flex items-center gap-2 text-[10px] text-slate-500">Y metric<select className="filter-select" value={metric?.key} onChange={(event) => { const nextKey = event.target.value; setMetricKey(nextKey); onMetricChange?.(nextKey); const next = metrics.find((item) => item.key === nextKey); if (next && !next.types.includes(kind)) setKind((types ?? next.types).find((type) => next.types.includes(type)) ?? next.types[0] ?? "bar"); if (nextKey === xKey) setXKey((xMetrics ?? metrics).find((item) => item.key !== nextKey)?.key ?? ""); }} aria-label={`Y axis metric for ${title}`}>{metrics.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}</select></label>}
      {kind === "scatter" && <label className="flex items-center gap-2 text-[10px] text-slate-500">X metric<select className="filter-select" value={xMetric?.key ?? ""} onChange={(event) => setXKey(event.target.value)} aria-label={`X axis metric for ${title}`}>{scatterMetrics.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}</select></label>}
      <label className="ml-auto flex items-center gap-2 text-[10px] text-slate-500">Chart<select className="filter-select" value={kind} onChange={(event) => setKind(event.target.value as ChartKind)} aria-label={`Chart type for ${title}`}>{allowedTypes.map((type) => <option key={type} value={type}>{type === "horizontal" ? "Horizontal bar" : type === "donut" ? "Donut" : type[0].toUpperCase() + type.slice(1)}</option>)}</select></label>
      <span className="w-full text-[10px] text-slate-600">{kind === "scatter" ? `X: ${xMetric?.label ?? "Unavailable"} · Y: ${metric?.label ?? "Unavailable"}` : `Value: ${metric?.label ?? "Unavailable"}`}</span>
    </div>
    {validRows.length === 0 || !validRows.some((row) => kind === "scatter" ? hasNumericValue(row[metric?.key ?? ""]) : hasNumericValue(row[metric?.key ?? ""])) ? <EmptyState title="No chart data available" description="The selected metric has no recorded values for these filters." /> : <div className="w-full px-3 pb-4 pt-3" style={{ height }} onClick={chartClick}>
      <ResponsiveContainer width="100%" height="100%">
        {kind === "line" ? <LineChart data={validRows} margin={{ top: 8, right: 12, bottom: 8, left: 0 }} onClick={onPointClick ? chartClick : undefined}>{commonTooltip}<CartesianGrid stroke="#ffffff0b" vertical={false} />{categoryAxis}{valueAxis}<Line dataKey={metric?.key} name={metric?.label} type="monotone" stroke="#67e8f9" strokeOpacity={0.92} strokeWidth={2} dot={validRows.length <= 60 ? { r: 2.5, fill: "#111820", stroke: "#67e8f9", strokeWidth: 1.5 } : false} connectNulls={false} activeDot={{ r: 5 }} /></LineChart>
          : kind === "area" ? <AreaChart data={validRows} margin={{ top: 8, right: 12, bottom: 8, left: 0 }} onClick={onPointClick ? chartClick : undefined}><defs><linearGradient id={areaFillId} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#67e8f9" stopOpacity={0.24} /><stop offset="100%" stopColor="#67e8f9" stopOpacity={0.015} /></linearGradient></defs>{commonTooltip}<CartesianGrid stroke="#ffffff0b" vertical={false} />{categoryAxis}{valueAxis}<Area dataKey={metric?.key} name={metric?.label} type="monotone" stroke="#67e8f9" strokeOpacity={0.92} strokeWidth={2} fill={`url(#${areaFillId})`} fillOpacity={1} dot={validRows.length <= 60 ? { r: 2, fill: "#111820", stroke: "#67e8f9", strokeWidth: 1.5 } : false} activeDot={{ r: 5 }} connectNulls={false} /></AreaChart>
            : kind === "bar" || kind === "horizontal" ? <BarChart data={validRows} layout={kind === "horizontal" ? "vertical" : "horizontal"} margin={{ top: 8, right: 12, bottom: 8, left: 0 }} onClick={onPointClick ? chartClick : undefined}>{commonTooltip}<CartesianGrid stroke="#ffffff0b" vertical={false} />{categoryAxis}{valueAxis}<Bar dataKey={metric?.key} name={metric?.label} fill="#67e8f9" radius={kind === "horizontal" ? [0, 4, 4, 0] : [4, 4, 0, 0]}>{validRows.map((row, index) => <Cell key={`${String(row[labelKey])}-${index}`} fill={palette[index % palette.length]} cursor={onPointClick ? "pointer" : undefined} onClick={() => onPointClick?.(row)} />)}</Bar></BarChart>
              : kind === "donut" ? <PieChart>{commonTooltip}<Legend wrapperStyle={{ color: "#94a3b8", fontSize: 10 }} /><Pie data={validRows} dataKey={metric?.key} nameKey={labelKey} innerRadius="53%" outerRadius="78%" paddingAngle={2} onClick={(entry) => onPointClick?.(entry as ChartRow)}>{validRows.map((row, index) => <Cell key={`${String(row[labelKey])}-${index}`} fill={palette[index % palette.length]} cursor={onPointClick ? "pointer" : undefined} />)}</Pie></PieChart>
                : <ScatterChart margin={{ top: 12, right: 18, bottom: 12, left: 4 }}>{commonTooltip}<CartesianGrid stroke="#ffffff0b" /><XAxis type="number" dataKey={xMetric?.key} name={xMetric?.label} tick={{ fill: "#64748b", fontSize: 10 }} tickFormatter={(value) => axisFormatter(value, xMetric)} label={{ value: xMetric?.label, position: "insideBottom", offset: -8, fill: "#64748b", fontSize: 10 }} /><YAxis type="number" dataKey={metric?.key} name={metric?.label} tick={{ fill: "#64748b", fontSize: 10 }} tickFormatter={(value) => axisFormatter(value, metric)} label={{ value: metric?.label, angle: -90, position: "insideLeft", fill: "#64748b", fontSize: 10 }} /><Scatter data={validRows} fill="#67e8f9" onClick={(entry) => onPointClick?.(entry as ChartRow)} /></ScatterChart>}
      </ResponsiveContainer>
    </div>}
  </Panel>;
}

export const chartMetric = {
  price: { key: "price", label: "Price", format: "currency", currencyKey: "currency", types: ["line", "area", "bar", "scatter"] } satisfies VisualMetric,
  rating: { key: "rating", label: "Rating", format: "rating", types: ["line", "area", "bar", "scatter"] } satisfies VisualMetric,
  reviews: { key: "review_count", label: "Review count", format: "number", types: ["line", "area", "bar", "scatter"] } satisfies VisualMetric,
  score: { key: "final_score", label: "Final opportunity score", format: "score", types: ["bar", "horizontal", "scatter"] } satisfies VisualMetric,
  count: { key: "count", label: "Count", format: "number", types: ["bar", "horizontal", "donut", "line", "area"] } satisfies VisualMetric,
} as const;
