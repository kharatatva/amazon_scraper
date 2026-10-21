import { Link, useLocation } from "wouter";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Bell,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  ClipboardList,
  Copy,
  Database,
  ExternalLink,
  Gauge,
  Layers3,
  LayoutDashboard,
  Menu,
  PackageSearch,
  PanelLeftClose,
  PanelLeftOpen,
  Play,
  Plus,
  Radar,
  Search,
  Server,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Store,
  TerminalSquare,
  Target,
  TimerReset,
  TrendingDown,
  TrendingUp,
  Users,
  X,
  Zap,
} from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Area, AreaChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useSettings } from "@/contexts/SettingsContext";
import type { HistoryPoint, Product, RunStatus, SearchRun } from "@/lib/domain";
import { formatCompact, formatCurrency, formatDate, formatNumber, scoreTone } from "@/lib/format";

const navGroups = [
  {
    label: "Workspace",
    items: [
      { href: "/overview", label: "Overview", icon: LayoutDashboard },
      { href: "/niches", label: "Niche explorer", icon: Radar },
      { href: "/opportunities", label: "Opportunities", icon: Zap },
      { href: "/products", label: "Products", icon: PackageSearch },
      { href: "/sellers", label: "Sellers", icon: Store },
      { href: "/analytics", label: "Analytics", icon: BarChart3 },
    ],
  },
  {
    label: "Operations",
    items: [
      { href: "/scraper", label: "Scraper control", icon: TerminalSquare },
      { href: "/demand", label: "Demand tracker", icon: Target },
      { href: "/runs", label: "Run history", icon: ClipboardList },
      { href: "/schedules", label: "Scheduled niches", icon: TimerReset },
    ],
  },
  {
    label: "System",
    items: [
      { href: "/system", label: "System health", icon: Server },
      { href: "/errors", label: "Errors", icon: AlertTriangle },
      { href: "/settings", label: "Settings", icon: Settings2 },
    ],
  },
];

export function AppSidebar({ collapsed, onToggle, mobileOpen, onClose }: { collapsed: boolean; onToggle: () => void; mobileOpen: boolean; onClose: () => void }) {
  const [location] = useLocation();
  const { settings } = useSettings();
  return (
    <>
      {mobileOpen && <button aria-label="Close navigation" onClick={onClose} className="fixed inset-0 z-40 bg-black/60 lg:hidden" />}
      <aside className={`sidebar ${collapsed ? "sidebar-collapsed" : ""} ${mobileOpen ? "sidebar-mobile-open" : ""}`}>
        <div className="flex h-full flex-col">
          <div className="flex h-[76px] items-center border-b border-white/[0.07] px-5">
            <Link href="/overview" className="group flex min-w-0 items-center gap-3" onClick={onClose}>
              <div className="brand-mark"><span className="brand-mark-dot" /><span className="brand-mark-line" /></div>
              {!collapsed && <div className="min-w-0"><p className="font-display truncate text-[15px] font-bold tracking-tight text-white">{settings.productName}</p><p className="truncate text-[10px] font-medium uppercase tracking-[0.19em] text-slate-500">{settings.tagline}</p></div>}
            </Link>
            <button onClick={onClose} className="ml-auto rounded-md p-1.5 text-slate-500 hover:bg-white/5 hover:text-white lg:hidden"><X size={18} /></button>
          </div>
          <nav className="scrollbar-thin flex-1 space-y-7 overflow-y-auto px-3 py-6">
            {navGroups.map((group) => (
              <div key={group.label}>
                {!collapsed && <p className="mb-2 px-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-600">{group.label}</p>}
                <div className="space-y-1">
                  {group.items.map((item) => {
                    const active = location === item.href || (item.href !== "/overview" && location.startsWith(item.href));
                    return <Link key={item.href} href={item.href} onClick={onClose} className={`sidebar-link ${active ? "sidebar-link-active" : ""}`} title={collapsed ? item.label : undefined}>
                      <item.icon size={17} strokeWidth={active ? 2.2 : 1.7} />
                      {!collapsed && <span>{item.label}</span>}
                      {!collapsed && active && <span className="ml-auto h-1.5 w-1.5 rounded-full bg-cyan-300 shadow-[0_0_10px_rgba(103,232,249,0.9)]" />}
                    </Link>;
                  })}
                </div>
              </div>
            ))}
          </nav>
          <div className={`border-t border-white/[0.07] p-3 ${collapsed ? "flex justify-center" : ""}`}>
            <div className={`status-card ${collapsed ? "justify-center px-0" : ""}`}>
              <Database size={13} className="text-cyan-300" />
              {!collapsed && <><span className="text-[11px] font-medium text-slate-300">Project SQLite API</span><span className="ml-auto text-[10px] text-slate-600">LOCAL</span></>}
            </div>
            <button className={`mt-2 flex items-center gap-2 rounded-lg px-2.5 py-2 text-slate-500 transition hover:bg-white/5 hover:text-slate-200 ${collapsed ? "mx-auto" : "w-full"}`} onClick={onToggle} title={collapsed ? "Expand sidebar" : "Collapse sidebar"}>
              {collapsed ? <PanelLeftOpen size={16} /> : <><PanelLeftClose size={16} /><span className="text-[11px]">Collapse sidebar</span></>}
            </button>
          </div>
        </div>
      </aside>
    </>
  );
}

export function TopBar({ onMenu }: { onMenu: () => void }) {
  const { settings } = useSettings();
  return <header className="topbar">
    <button aria-label="Open navigation" onClick={onMenu} className="mr-3 rounded-lg p-2 text-slate-400 hover:bg-white/5 hover:text-white lg:hidden"><Menu size={19} /></button>
    <div className="hidden items-center gap-2 text-xs text-slate-500 sm:flex"><span className="font-medium text-slate-300">Workspace</span><ChevronRight size={13} /><span>Amazon research</span></div>
    <div className="ml-auto flex items-center gap-2 sm:gap-3">
      <GlobalSearch />
      <button className="icon-btn"><Bell size={16} /><span className="notification-dot" /></button>
      <div className="h-5 w-px bg-white/10" />
      <button className="flex items-center gap-2 rounded-lg px-1.5 py-1 text-left hover:bg-white/5"><div className="avatar">{settings.displayName.split(" ").map((part) => part[0]).join("").slice(0, 2)}</div><span className="hidden text-xs font-medium text-slate-300 sm:inline">{settings.displayName}</span><ChevronDown size={14} className="text-slate-600" /></button>
    </div>
  </header>;
}

function GlobalSearch() {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [results, setResults] = useState<Array<{ type: string; title: string; meta: string; href: string; icon: typeof Radar }>>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const [, navigate] = useLocation();

  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        inputRef.current?.focus();
        setOpen(true);
      }
    };
    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, []);

  const normalized = query.trim().toLowerCase();
  useEffect(() => {
    if (!normalized) { setResults([]); return; }
    let active = true;
    Promise.all([api.getNiches(normalized), api.getProducts({ search: normalized, page_size: 5 }), api.getRuns({ page_size: 10 })])
      .then(([niches, products, runs]) => {
        if (!active) return;
        const matches = [
          ...niches.slice(0, 3).map((niche) => ({ type: "Niche", title: niche.name, meta: `${niche.product_count ?? 0} products · ${niche.keywords.length} keywords`, href: `/niches/${niche.id}`, icon: Radar })),
          ...products.items.slice(0, 4).map((product) => ({ type: "Product", title: product.title ?? product.asin, meta: `${product.asin} · ${product.brand ?? "Brand unavailable"}`, href: `/products/${product.id}`, icon: PackageSearch })),
          ...runs.items.filter((run) => `#${run.id} ${run.niche_name} ${run.keyword ?? ""} ${run.status}`.toLowerCase().includes(normalized)).slice(0, 3).map((run) => ({ type: "Run", title: `Run #${run.id} · ${run.niche_name}`, meta: `${run.keyword ?? "Keyword unavailable"} · ${run.status}`, href: `/runs/${run.id}`, icon: ClipboardList })),
        ];
        setResults(matches.slice(0, 7));
      }).catch(() => { if (active) setResults([]); });
    return () => { active = false; };
  }, [normalized]);

  const goTo = (href: string) => {
    navigate(href);
    setQuery("");
    setOpen(false);
  };

  return <div className={`global-search ${open && normalized ? "global-search-open" : ""}`}>
    <Search size={14} className="text-slate-500" />
    <input ref={inputRef} value={query} onChange={(event) => { setQuery(event.target.value); setOpen(true); }} onFocus={() => setOpen(true)} onKeyDown={(event) => { if (event.key === "Escape") { setOpen(false); inputRef.current?.blur(); } if (event.key === "Enter" && results[0]) goTo(results[0].href); }} placeholder="Search niches, products, runs" aria-label="Search niches, products, and runs" />
    <kbd>⌘ K</kbd>
    {open && normalized && <div className="global-search-results">
      {results.length > 0 ? <>{results.map((result) => <button type="button" key={`${result.type}-${result.href}`} className="global-search-result" onMouseDown={(event) => event.preventDefault()} onClick={() => goTo(result.href)}><span className="global-search-result-icon"><result.icon size={14} /></span><span className="min-w-0 flex-1 text-left"><span className="block truncate text-xs font-medium text-slate-200">{result.title}</span><span className="mt-0.5 block truncate text-[10px] text-slate-600">{result.meta}</span></span><span className="global-search-result-type">{result.type}</span></button>)}</> : <div className="px-3 py-4 text-center text-[11px] text-slate-600">No niches, products, or runs match “{query}”.</div>}
      <div className="border-t border-white/[0.06] px-3 py-2 text-[10px] text-slate-600">Press <span className="font-mono text-slate-400">Enter</span> to open the first match · <span className="font-mono text-slate-400">Esc</span> to close</div>
    </div>}
  </div>;
}

export function DashboardLayout({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  return <div className="app-shell"><AppSidebar collapsed={collapsed} onToggle={() => setCollapsed((value) => !value)} mobileOpen={mobileOpen} onClose={() => setMobileOpen(false)} /><div className={`main-shell ${collapsed ? "main-shell-expanded" : ""}`}><TopBar onMenu={() => setMobileOpen(true)} /><main className="page-content">{children}</main></div></div>;
}

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow?: string; title: string; description?: string; actions?: ReactNode }) {
  return <div className="page-header"><div><div className="mb-2 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.2em] text-cyan-400/80">{eyebrow && <><span>{eyebrow}</span><span className="h-px w-5 bg-cyan-400/40" /></>}</div><h1 className="font-display text-[26px] font-semibold tracking-[-0.03em] text-white sm:text-[30px]">{title}</h1>{description && <p className="mt-2 max-w-2xl text-[13px] leading-6 text-slate-500">{description}</p>}</div>{actions && <div className="mt-4 flex items-center gap-2 sm:mt-0">{actions}</div>}</div>;
}

export function Panel({ children, className = "", title, description, action }: { children: ReactNode; className?: string; title?: string; description?: string; action?: ReactNode }) {
  return <section className={`panel ${className}`}>{(title || action) && <div className="panel-header"><div className="min-w-0 flex-1">{title && <h2 className="break-words text-[13px] font-semibold leading-5 text-slate-200">{title}</h2>}{description && <p className="mt-1 text-[11px] leading-5 text-slate-600">{description}</p>}</div>{action}</div>}{children}</section>;
}

export function MetricCard({ label, value, change, changeLabel, icon: Icon, accent = "cyan", detail }: { label: string; value: string; change?: number | null; changeLabel?: string; icon: typeof Activity; accent?: "cyan" | "violet" | "amber" | "green"; detail?: string }) {
  return <div className="metric-card"><div className="flex items-start justify-between"><div className={`metric-icon metric-icon-${accent}`}><Icon size={17} /></div>{change !== undefined && <span className={`metric-change ${change === null ? "metric-change-muted" : change >= 0 ? "metric-change-positive" : "metric-change-negative"}`}>{change === null ? "—" : `${change >= 0 ? "+" : ""}${change}%`}<span className="ml-1 text-[10px] font-normal text-slate-600">{changeLabel}</span></span>}</div><p className="mt-4 text-[11px] font-medium uppercase tracking-[0.12em] text-slate-500">{label}</p><p className="metric-value">{value}</p>{detail && <p className="mt-1 text-[11px] text-slate-600">{detail}</p>}</div>;
}

export function StatusPill({ status }: { status: RunStatus | "Idle" | "Healthy" | "Warning" | "Error" | "Unknown" }) {
  const config: Record<string, { label: string; cls: string }> = {
    success: { label: "Success", cls: "status-success" }, partial: { label: "Partial", cls: "status-partial" }, failed: { label: "Failed", cls: "status-failed" }, running: { label: "Running", cls: "status-running" }, Idle: { label: "Idle", cls: "status-idle" }, Healthy: { label: "Healthy", cls: "status-success" }, Warning: { label: "Warning", cls: "status-partial" }, Error: { label: "Error", cls: "status-failed" }, Unknown: { label: "Unknown", cls: "status-idle" },
  };
  const item = config[status] ?? config.Unknown;
  return <span className={`status-pill ${item.cls}`}><span className="status-pill-dot" />{item.label}</span>;
}

export function ScoreChip({ score, label, large = false }: { score: number | null; label?: string; large?: boolean }) {
  if (score === null || score === undefined) return <span className="score-na">N/A</span>;
  return <span className={`score-chip ${scoreTone(score)} ${large ? "score-chip-large" : ""}`}>{label && <span className="mr-1.5 text-[10px] font-normal opacity-60">{label}</span>}{score.toFixed(1)}</span>;
}

export function ProductGlyph({ product, size = "md" }: { product: Product; size?: "sm" | "md" | "lg" }) {
  const palette = ["#123c45", "#3d2949", "#493b1e", "#1e3c34", "#44313a", "#203952"];
  const color = palette[product.id % palette.length];
  return <div className={`product-glyph product-glyph-${size}`} style={{ background: `linear-gradient(145deg, ${color}, #111820)` }}>{product.thumbnail_url ? <img src={product.thumbnail_url} alt="" loading="lazy" className="h-full w-full object-contain bg-white" /> : <><span>{product.brand?.slice(0, 1) ?? "P"}</span><div className="product-glyph-wave" /></>}</div>;
}

export function EmptyState({ title, description, icon: Icon = PackageSearch }: { title: string; description: string; icon?: typeof PackageSearch }) {
  return <div className="empty-state"><Icon size={20} className="text-slate-600" /><p className="mt-3 text-sm font-medium text-slate-300">{title}</p><p className="mt-1 max-w-xs text-center text-xs leading-5 text-slate-600">{description}</p></div>;
}

export function ErrorState({ title = "Unable to load this view.", onRetry }: { title?: string; onRetry?: () => void }) {
  return <div className="empty-state"><AlertTriangle size={20} className="text-amber-400" /><p className="mt-3 text-sm font-medium text-slate-300">{title}</p><button onClick={onRetry} className="mt-3 text-xs font-medium text-cyan-400 hover:text-cyan-300">Retry</button></div>;
}

export function ProgressBar({ value, color = "cyan" }: { value: number; color?: "cyan" | "green" | "amber" }) {
  return <div className="progress-track"><div className={`progress-fill progress-fill-${color}`} style={{ width: `${Math.max(0, Math.min(100, value))}%` }} /></div>;
}

export function ProductTable({ products, limit }: { products: Product[]; limit?: number }) {
  const visible = limit ? products.slice(0, limit) : products;
  return <div className="data-table-wrap"><table className="data-table"><thead><tr><th>Product</th><th>ASIN</th><th>Seller</th><th>Fulfillment</th><th>Category</th><th>First seen</th><th>Latest price</th><th>Rating</th><th>Reviews</th><th>BSR</th><th>Search rank</th><th>Snapshot flags</th><th>Images</th><th>Bullets</th><th>A+ content</th><th>Variants</th><th>Opportunity scores</th><th>Product URL</th><th /></tr></thead><tbody>{visible.map((product) => { const snapshot = product.current; const bsr = snapshot?.bsr?.[0] as { rank?: number; category?: string } | undefined; const flags = snapshot ? [["Sponsored", snapshot.is_sponsored], ["Choice", snapshot.is_amazons_choice], ["Best seller", snapshot.is_best_seller]].map(([label, value]) => `${label}: ${value == null ? "?" : value ? "Yes" : "No"}`).join(" · ") : "N/A"; return <tr key={product.id} className="group"><td><Link href={`/products/${product.id}`} className="flex min-w-[220px] items-center gap-3"><ProductGlyph product={product} size="sm" /><div className="min-w-0"><p className="product-name truncate" title={product.title ?? undefined}>{product.title ?? "Title unavailable"}</p><p className="mt-0.5 truncate text-[10px] text-slate-600">{product.brand ?? "Brand unavailable"}</p></div></Link></td><td><button className="copy-button" onClick={() => { void navigator.clipboard?.writeText(product.asin); toast.success("ASIN copied", { description: product.asin }); }}>{product.asin}<Copy size={11} /></button></td><td className="text-xs text-slate-400">{product.seller_name ?? "Unavailable"}</td><td><span className="fulfillment-badge">{product.fulfillment_type ?? "Unknown"}</span></td><td className="max-w-[210px] truncate text-xs text-slate-400">{product.category_path.join(" / ") || "Unavailable"}</td><td className="whitespace-nowrap text-[11px] text-slate-500">{formatDate(product.first_seen_at)}</td><td className="font-mono text-xs text-slate-300">{snapshot?.price !== null && snapshot?.price !== undefined ? formatCurrency(snapshot.price, snapshot.currency) : "N/A"}</td><td className="font-mono text-xs text-slate-300">{snapshot?.rating?.toFixed(1) ?? "N/A"}</td><td className="font-mono text-xs text-slate-400">{snapshot?.review_count !== null && snapshot?.review_count !== undefined ? formatCompact(snapshot.review_count) : "N/A"}</td><td className="max-w-[180px] truncate text-xs text-slate-400">{bsr?.rank ? `#${formatCompact(bsr.rank)} · ${bsr.category ?? "Category unavailable"}` : "N/A"}</td><td className="font-mono text-xs text-slate-400">{snapshot?.search_rank_position ?? "N/A"}</td><td className="max-w-[250px] whitespace-normal text-[10px] text-slate-400">{flags}</td><td className="font-mono text-xs">{snapshot?.images_count ?? "N/A"}</td><td className="font-mono text-xs">{snapshot?.bullet_points_count ?? "N/A"}</td><td className="text-xs">{snapshot?.has_a_plus_content == null ? "N/A" : snapshot.has_a_plus_content ? "Yes" : "No"}</td><td className="font-mono text-xs">{snapshot?.variant_count ?? "N/A"}</td><td><ScoreChip score={snapshot?.opportunity?.final_score ?? null} /><p className="mt-1 whitespace-nowrap text-[9px] text-slate-600">D {snapshot?.opportunity?.demand_score ?? "N/A"} | C {snapshot?.opportunity?.competition_score ?? "N/A"} | Q {snapshot?.opportunity?.quality_gap_score ?? "N/A"}</p></td><td>{product.product_url ? <a className="text-xs text-cyan-300" href={product.product_url} target="_blank" rel="noreferrer">Open</a> : "N/A"}</td><td><Link href={`/products/${product.id}`} className="rounded p-1 text-slate-600 opacity-0 transition hover:bg-white/5 hover:text-cyan-300 group-hover:opacity-100"><ChevronRight size={15} /></Link></td></tr>; })}</tbody></table></div>;
}

export function RunTable({ runs, limit }: { runs: SearchRun[]; limit?: number }) {
  const visible = limit ? runs.slice(0, limit) : runs;
  return <div className="data-table-wrap"><table className="data-table"><thead><tr><th>Run</th><th>Niche</th><th>Keyword</th><th>Time</th><th>Status</th><th>Stage / task</th><th>Pages</th><th>Products</th><th>Errors</th><th>Notes</th><th /></tr></thead><tbody>{visible.map((run) => <tr key={run.id} className="group"><td><Link href={`/runs/${run.id}`} className="font-mono text-xs font-semibold text-cyan-300 hover:text-cyan-200">#{run.id}</Link></td><td className="text-xs text-slate-300">{run.niche_name}</td><td className="max-w-[180px] truncate text-xs text-slate-500">{run.keyword ?? "N/A"}</td><td className="whitespace-nowrap text-[11px] text-slate-500">{formatDate(run.run_timestamp, true)}</td><td><StatusPill status={run.status} /></td><td className="max-w-[220px] truncate text-xs text-slate-500">{[run.current_stage, run.current_task].filter(Boolean).join(" · ") || "N/A"}</td><td className="font-mono text-xs text-slate-400">{run.pages_scraped ?? "N/A"}</td><td className="font-mono text-xs text-slate-400">{run.products_found ?? "N/A"}</td><td className="font-mono text-xs text-slate-400">{run.error_count}</td><td className="max-w-[220px] truncate text-xs text-slate-500" title={run.notes ?? undefined}>{run.notes ?? "N/A"}</td><td><Link href={`/runs/${run.id}`} className="rounded p-1 text-slate-600 opacity-0 transition hover:bg-white/5 hover:text-cyan-300 group-hover:opacity-100"><ChevronRight size={15} /></Link></td></tr>)}</tbody></table></div>;
}

export function HistoryChart({ data, label, color = "#67e8f9", prefix = "", inverse = false, emptyMessage = "Not enough historical observations yet." }: { data: HistoryPoint[]; label: string; color?: string; prefix?: string; inverse?: boolean; emptyMessage?: string }) {
  if (data.length === 0) return <div className="flex h-[220px] items-center justify-center"><EmptyState title="History unavailable" description={emptyMessage} icon={TimerReset} /></div>;
  return <div className="h-[220px] w-full"><ResponsiveContainer width="100%" height="100%"><LineChart data={data} margin={{ top: 12, right: 8, left: -18, bottom: 0 }}><defs><linearGradient id={`fill-${label}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={color} stopOpacity={0.22} /><stop offset="100%" stopColor={color} stopOpacity={0} /></linearGradient></defs><CartesianGrid stroke="#ffffff0b" vertical={false} /><XAxis dataKey="date" axisLine={false} tickLine={false} tick={{ fill: "#64748b", fontSize: 10 }} dy={8} /><YAxis reversed={inverse} axisLine={false} tickLine={false} tick={{ fill: "#64748b", fontSize: 10 }} tickFormatter={(value) => `${prefix}${formatCompact(value)}`} width={45} /><Tooltip contentStyle={{ background: "#131a22", border: "1px solid #ffffff16", borderRadius: 8, fontSize: 11, color: "#cbd5e1" }} labelStyle={{ color: "#94a3b8", marginBottom: 4 }} formatter={(value: number) => [`${prefix}${formatNumber(value)}`, label]} /><Area type="monotone" dataKey="value" stroke="none" fill={`url(#fill-${label})`} /><Line type="monotone" dataKey="value" stroke={color} strokeWidth={2} dot={{ r: 2.5, fill: "#131a22", stroke: color, strokeWidth: 1.5 }} activeDot={{ r: 4, fill: color, stroke: "#0b0f14", strokeWidth: 2 }} /></LineChart></ResponsiveContainer></div>;
}

export function Sparkline({ values, color = "#67e8f9" }: { values: number[]; color?: string }) {
  const data = values.map((value, index) => ({ index, value }));
  return <div className="h-9 w-24"><ResponsiveContainer width="100%" height="100%"><AreaChart data={data}><defs><linearGradient id={`spark-${color.replace("#", "")}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={color} stopOpacity={0.25} /><stop offset="100%" stopColor={color} stopOpacity={0} /></linearGradient></defs><Area type="monotone" dataKey="value" stroke={color} strokeWidth={1.5} fill={`url(#spark-${color.replace("#", "")})`} /></AreaChart></ResponsiveContainer></div>;
}

export function ScoreBreakdown({ scores }: { scores: { demand: number | null; competition: number | null; quality: number | null; final: number | null } }) {
  const rows = [{ label: "Demand", value: scores.demand, icon: Gauge, note: "Review count + velocity" }, { label: "Competition", value: scores.competition, icon: Users, note: "Top 3 review concentration" }, { label: "Quality gap", value: scores.quality, icon: ShieldCheck, note: "Listing quality + rating gap" }];
  return <div className="space-y-4">{rows.map((row) => <div key={row.label}><div className="mb-1.5 flex items-center gap-2"><row.icon size={13} className="text-slate-500" /><span className="text-xs font-medium text-slate-300">{row.label}</span><span className="ml-auto"><ScoreChip score={row.value} /></span></div><ProgressBar value={row.value ?? 0} color={row.label === "Competition" ? "green" : row.label === "Quality gap" ? "amber" : "cyan"} /><p className="mt-1 text-[10px] text-slate-600">{row.note}{row.value === null && " · Insufficient data"}</p></div>)}<div className="mt-5 border-t border-white/[0.07] pt-4"><div className="flex items-end justify-between"><div><p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-600">Final opportunity</p><p className="mt-1 text-[10px] text-slate-600">Backend score · not recalculated in UI</p></div><ScoreChip score={scores.final} large /></div></div></div>;
}

export function FilterBar({ search, onSearch, placeholder = "Search by name, ASIN or seller" }: { search: string; onSearch: (value: string) => void; placeholder?: string }) {
  return <div className="filter-bar"><div className="relative min-w-0 flex-1"><Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-600" /><input value={search} onChange={(event) => onSearch(event.target.value)} placeholder={placeholder} className="input-search" /></div><button className="filter-button"><SlidersHorizontal size={14} /> <span className="hidden sm:inline">Filters</span></button><button className="filter-button"><Settings2 size={14} /><span className="hidden sm:inline">Columns</span></button></div>;
}

export function SectionTabs({ tabs, active, onChange }: { tabs: string[]; active: string; onChange: (tab: string) => void }) {
  return <div className="section-tabs">{tabs.map((tab) => <button key={tab} onClick={() => onChange(tab)} className={`section-tab ${active === tab ? "section-tab-active" : ""}`}>{tab}</button>)}</div>;
}

export function DevModeBanner() {
  return <div className="dev-banner"><Database size={13} /><span>SQLite data source</span><span className="hidden sm:inline text-slate-600">·</span><span className="hidden sm:inline text-slate-500">Dashboard values come from the configured project database.</span></div>;
}

export const IconMap = { Activity, AlertTriangle, BarChart3, Bell, ClipboardList, Database, Gauge, Layers3, LayoutDashboard, PackageSearch, Play, Plus, Radar, Search, Server, ShieldCheck, Store, TerminalSquare, TrendingDown, TrendingUp, Users, Zap };
