import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "wouter";
import { AlertTriangle, Check, CircleAlert, CircleCheck, LoaderCircle, RefreshCw, ShieldCheck, Wrench, X } from "lucide-react";
import { toast } from "sonner";
import { api, type EnvironmentOperation, type EnvironmentResponse, type EnvironmentSnapshot } from "@/lib/api";
import {
  createEnvironmentReminderState,
  environmentIssueFingerprint,
  FIRST_RUN_STORAGE_KEY,
  isEnvironmentReminderDismissed,
  REMINDER_INTERVAL_MS,
  REMINDER_STORAGE_KEY,
  shouldShowFirstRunSetup,
} from "@/lib/environment-reminder";

interface EnvironmentContextValue {
  environment: EnvironmentSnapshot | null;
  operation: EnvironmentOperation | null;
  loading: boolean;
  connectionError: string | null;
  refresh: () => Promise<EnvironmentResponse | null>;
  verify: () => Promise<void>;
  initialize: (repair?: boolean) => Promise<void>;
}

const EnvironmentContext = createContext<EnvironmentContextValue | null>(null);

export function EnvironmentProvider({ children }: { children: ReactNode }) {
  const [environment, setEnvironment] = useState<EnvironmentSnapshot | null>(null);
  const [operation, setOperation] = useState<EnvironmentOperation | null>(null);
  const [loading, setLoading] = useState(true);
  const [connectionError, setConnectionError] = useState<string | null>(null);

  const accept = useCallback((response: EnvironmentResponse) => {
    setEnvironment(response.environment);
    setOperation(response.operation);
    setConnectionError(null);
    setLoading(false);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const response = await api.getEnvironment();
      accept(response);
      return response;
    } catch (error) {
      setConnectionError(error instanceof Error ? error.message : "Could not check the local environment.");
      setLoading(false);
      return null;
    }
  }, [accept]);

  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    const poll = async () => {
      const response = await refresh();
      if (!active) return;
      const delay = response === null ? 5000 : response.operation?.status === "running" ? 1200 : 60_000;
      timer = window.setTimeout(() => void poll(), delay);
    };
    void poll();
    return () => {
      active = false;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [operation?.status, refresh]);

  const verify = useCallback(async () => {
    setLoading(true);
    try {
      accept(await api.checkEnvironment());
      toast.success("Environment check completed");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Could not verify the local environment.";
      setConnectionError(message);
      setLoading(false);
      toast.error(message);
    }
  }, [accept]);

  const initialize = useCallback(async (repair = false) => {
    try {
      accept(await api.initializeEnvironment(repair));
      toast.info(repair ? "Environment repair started" : "Environment setup started");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Could not start environment setup.";
      setConnectionError(message);
      toast.error(message);
    }
  }, [accept]);

  const value = useMemo(() => ({
    environment, operation, loading, connectionError, refresh, verify, initialize,
  }), [environment, operation, loading, connectionError, refresh, verify, initialize]);

  return <EnvironmentContext.Provider value={value}>{children}</EnvironmentContext.Provider>;
}

function useEnvironment() {
  const context = useContext(EnvironmentContext);
  if (!context) throw new Error("EnvironmentProvider is missing.");
  return context;
}

function savedReminder(): string | null {
  try {
    return window.localStorage.getItem(REMINDER_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function EnvironmentNotice() {
  const { environment, connectionError } = useEnvironment();
  const [clock, setClock] = useState(Date.now());
  const fingerprint = environmentIssueFingerprint(environment, connectionError);
  const hasIssue = Boolean(connectionError || (environment && !environment.ready));
  const hidden = hasIssue && isEnvironmentReminderDismissed(fingerprint, savedReminder(), clock);

  useEffect(() => {
    if (environment?.ready) {
      try { window.localStorage.removeItem(REMINDER_STORAGE_KEY); } catch { /* healthy state hides the notice for this session */ }
    }
  }, [environment?.ready]);

  useEffect(() => {
    if (!hidden) return;
    let until = Date.now() + REMINDER_INTERVAL_MS;
    try {
      const parsed = JSON.parse(savedReminder() ?? "null") as { until?: number } | null;
      if (typeof parsed?.until === "number") until = parsed.until;
    } catch { /* show the reminder if saved browser state is unavailable */ }
    const timer = window.setTimeout(() => setClock(Date.now()), Math.max(0, until - Date.now()));
    return () => window.clearTimeout(timer);
  }, [hidden, fingerprint, clock]);

  if (!hasIssue || hidden) return null;
  const critical = Boolean(connectionError || environment?.issues.some((issue) => {
    const item = environment.components.find((component) => component.id === issue.id);
    return item?.required;
  }));
  const message = connectionError
    ? "The dashboard could not verify scraper readiness."
    : `Scraping is paused: ${environment?.issues[0]?.message ?? "A required component needs attention."}`;

  function dismiss() {
    try {
      window.localStorage.setItem(REMINDER_STORAGE_KEY, createEnvironmentReminderState(fingerprint));
    } catch { /* the notice remains available until the environment is repaired */ }
    setClock(Date.now());
  }

  return <div className={`mx-4 mt-3 flex items-start gap-3 rounded-lg border px-4 py-3 sm:mx-6 ${critical ? "border-amber-300/20 bg-amber-300/[0.06]" : "border-cyan-300/20 bg-cyan-300/[0.05]"}`} role="status">
    <AlertTriangle size={16} className={`mt-0.5 shrink-0 ${critical ? "text-amber-300" : "text-cyan-300"}`} />
    <div className="min-w-0 flex-1">
      <p className="text-xs font-semibold text-slate-200">{critical ? "Scraper setup needs attention" : "Environment warning"}</p>
      <p className="mt-1 text-[11px] leading-5 text-slate-400">{message}</p>
    </div>
    <Link href="/settings#environment-setup" className="secondary-button shrink-0">Open setup</Link>
    <button type="button" onClick={dismiss} className="rounded p-1 text-slate-500 hover:bg-white/5 hover:text-slate-200" aria-label="Remind me later"><X size={14} /></button>
  </div>;
}

function StatusIcon({ status }: { status: string }) {
  if (status === "ready") return <CircleCheck size={15} className="shrink-0 text-emerald-300" />;
  if (status === "running") return <LoaderCircle size={15} className="shrink-0 animate-spin text-cyan-300" />;
  if (status === "pending") return <span className="h-[15px] w-[15px] shrink-0 rounded-full border border-slate-700" />;
  return <CircleAlert size={15} className="shrink-0 text-amber-300" />;
}

function EnvironmentSetupCard({ onClose }: { onClose?: () => void }) {
  const { environment, operation, loading, connectionError, verify, initialize } = useEnvironment();
  const running = operation?.status === "running";
  const ready = environment?.ready === true;
  const needsRepair = Boolean(environment && !environment.ready);
  const currentStage = operation?.stages.find((stage) => stage.status === "running");

  return <section className="overflow-hidden rounded-xl border border-white/[0.08] bg-[#111820] shadow-2xl" aria-labelledby="environment-setup-title">
    <div className="flex items-start gap-4 border-b border-white/[0.07] p-5 sm:p-6">
      <div className="grid h-10 w-10 shrink-0 place-items-center rounded-lg border border-cyan-300/15 bg-cyan-300/[0.07] text-cyan-200"><ShieldCheck size={19} /></div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <h2 id="environment-setup-title" className="text-sm font-semibold text-white">{ready ? "Environment is ready" : "Prepare your local scraper"}</h2>
          {environment && <span className={`rounded-full px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wider ${ready ? "bg-emerald-300/10 text-emerald-300" : "bg-amber-300/10 text-amber-200"}`}>{ready ? "Ready" : "Setup required"}</span>}
        </div>
        <p className="mt-1.5 max-w-2xl text-xs leading-5 text-slate-400">{ready
          ? "Folders, Python packages, database migrations, saved settings, and Chromium have passed their readiness checks."
          : "This setup checks local folders and configuration, prepares the SQLite schema, and installs or verifies the Playwright browser used by scraping."}</p>
      </div>
      {onClose && <button type="button" onClick={onClose} className="rounded-md p-1.5 text-slate-500 hover:bg-white/5 hover:text-slate-200" aria-label="Close setup"><X size={17} /></button>}
    </div>

    <div className="grid gap-5 p-5 sm:p-6 lg:grid-cols-[1.1fr_0.9fr]">
      <div>
        <div className="mb-3 flex items-center justify-between gap-2">
          <h3 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">Required components</h3>
          {environment && <span className="text-[10px] text-slate-600">Checked {new Date(environment.checked_at).toLocaleTimeString()}</span>}
        </div>
        {loading && !environment ? <div className="flex items-center gap-2 py-5 text-xs text-slate-500"><LoaderCircle size={14} className="animate-spin" /> Checking local environment…</div> : <div className="divide-y divide-white/[0.06] rounded-lg border border-white/[0.06]">
          {(environment?.components ?? []).map((component) => <div key={component.id} className="flex items-start gap-3 px-3 py-3">
            <StatusIcon status={component.status} />
            <div className="min-w-0 flex-1">
              <p className="text-xs font-medium text-slate-200">{component.name}</p>
              <p className="mt-1 text-[10px] leading-4 text-slate-500">{component.message}</p>
            </div>
            <span className={`shrink-0 text-[9px] font-semibold uppercase tracking-wider ${component.status === "ready" ? "text-emerald-300" : "text-amber-200"}`}>
              {component.status === "ready" ? "Ready" : component.status === "unknown" ? "Verify" : "Action needed"}
            </span>
          </div>)}
          {!environment && !loading && <div className="px-3 py-4 text-xs text-slate-500">Readiness is not available yet.</div>}
        </div>}
      </div>

      <div className="space-y-4">
        <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-4">
          <div className="flex items-center gap-2"><Wrench size={14} className="text-cyan-300" /><h3 className="text-xs font-semibold text-slate-200">Setup activity</h3></div>
          {operation ? <>
            <div className="mt-3 flex items-start justify-between gap-3"><p className="text-[11px] leading-5 text-slate-400">{running ? (currentStage ? `${currentStage.name}: ${currentStage.message}` : operation.message) : operation.message}</p><span className="shrink-0 font-mono text-[10px] text-cyan-200">{operation.progress}%</span></div>
            <div className="progress-track mt-2"><div className={`progress-fill ${operation.status === "failed" ? "progress-fill-amber" : operation.status === "completed" ? "progress-fill-green" : "progress-fill-cyan"}`} style={{ width: `${operation.progress}%` }} /></div>
            <div className="mt-3 space-y-2">
              {operation.stages.map((stage) => <div key={stage.id} className="flex items-center gap-2">
                <StatusIcon status={stage.status} />
                <span className="text-[10px] text-slate-400">{stage.name}</span>
                {stage.status === "error" && <span className="ml-auto text-[9px] text-rose-300">Failed</span>}
              </div>)}
            </div>
            {operation.error && <p className="mt-3 rounded-md border border-rose-300/15 bg-rose-300/[0.05] p-2.5 text-[10px] leading-4 text-rose-200" role="alert">{operation.error}</p>}
          </> : <p className="mt-2 text-[11px] leading-5 text-slate-500">Setup checks each component in order and reports failures here. Existing data and valid settings are kept.</p>}
          {connectionError && <p className="mt-3 text-[10px] leading-4 text-rose-300" role="alert">{connectionError}</p>}
        </div>

        <div className="flex flex-wrap gap-2">
          <button type="button" className="primary-button" disabled={running || loading} onClick={() => void initialize(false)}>
            {running ? <LoaderCircle size={13} className="animate-spin" /> : <Check size={13} />}
            {running ? "Setting up…" : ready ? "Initialize / verify" : "Initialize environment"}
          </button>
          <button type="button" className="secondary-button" disabled={running || loading} onClick={() => void verify()}><RefreshCw size={13} /> Verify</button>
          <button type="button" className="secondary-button" disabled={running || loading || !needsRepair} onClick={() => void initialize(true)}><Wrench size={13} /> Repair environment</button>
        </div>
        <p className="text-[10px] leading-4 text-slate-600">Repair reinstalls Chromium when needed and backs up invalid saved settings before restoring defaults. If the database schema is incomplete, it takes a timestamped SQLite backup before adding missing schema; existing rows are kept.</p>
      </div>
    </div>
  </section>;
}

export function EnvironmentMaintenance() {
  return <div id="environment-setup" className="scroll-mt-6"><EnvironmentSetupCard /></div>;
}

export function FirstRunSetup() {
  const { environment } = useEnvironment();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!environment) return;
    if (environment.ready) {
      setOpen(false);
      return;
    }
    let seen = false;
    try { seen = window.localStorage.getItem(FIRST_RUN_STORAGE_KEY) === "1"; } catch { /* show onboarding when browser storage is unavailable */ }
    if (shouldShowFirstRunSetup(environment.ready, seen)) {
      setOpen(true);
      try { window.localStorage.setItem(FIRST_RUN_STORAGE_KEY, "1"); } catch { /* the dialog remains dismissible */ }
    }
  }, [environment?.ready]);

  if (!open || !environment || environment.ready) return null;
  return <div className="fixed inset-0 z-[100] grid place-items-center overflow-y-auto bg-[#070b10]/85 p-4 backdrop-blur-sm" role="presentation">
    <div className="my-auto w-full max-w-4xl" role="dialog" aria-modal="true" aria-labelledby="environment-setup-title">
      <EnvironmentSetupCard onClose={() => setOpen(false)} />
      <p className="mt-3 text-center text-[10px] text-slate-500">You can continue to the dashboard and return to Environment Setup &amp; Maintenance in Settings at any time.</p>
    </div>
  </div>;
}
